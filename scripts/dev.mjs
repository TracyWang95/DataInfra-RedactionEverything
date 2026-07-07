#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import { createWriteStream, existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const backendDir = path.join(repoRoot, 'backend');
const frontendDir = path.join(repoRoot, 'frontend');
const logsDir = path.join(repoRoot, 'logs');
mkdirSync(logsDir, { recursive: true });

class PublicStartupError extends Error {
  constructor(code, detail = '') {
    super('startup failed');
    this.code = code;
    this.detail = detail;
  }
}

const PUBLIC_STARTUP_MESSAGES = {
  config: 'Missing required local configuration. Check .env and .env.example.',
  wsl: 'Could not resolve WSL IP. Start from Windows with WSL available.',
  service: 'A required local service was not ready before timeout. Inspect the matching logs/<service>.log.',
  port: 'A required port is already in use, likely by a previous session. Run "npm run stop" first.',
  warmup: 'Model warmup failed. Inspect logs/warmup.log and service logs.',
  venv: 'Missing Windows project venv. Create the project .venv once, then run npm run dev again.',
  platform: 'This local hybrid profile must be started from Windows.',
  generic: 'startup failed; inspect the logs/<service>.log files for details.',
};

// WSL-side process cleanup used by shutdown(). KEEP IN SYNC with the identical
// sequence in scripts/stop-dev.mjs (each file maintains its own copy; update
// both together). Patterns match process features instead of absolute venv
// paths so they work on any machine. The [x] first-character bracket prevents
// pkill -f from matching this very `bash -lc` command line (a self-kill would
// abort the sequence midway). "[v]llm serve" covers all three vLLM servers
// (8118 paddle / 8080 has-text / 8091 locate-lm).
const WSL_KILL_SEQUENCE = [
  'set +e',
  'pkill -TERM -f "[v]llm serve" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[P]addlePaddle/PaddleOCR-VL" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[H]aS_4.0_0.6B" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[l]ocate_qwen2_model" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[s]cripts/ocr_server.py" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[l]ocate_anything_server.py" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[l]ocate_anything_eval.py" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[l]ocate_anything_tile_eval.py" >/dev/null 2>&1 || true',
  'sleep 2',
  'pkill -KILL -f "[v]llm serve" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[P]addlePaddle/PaddleOCR-VL" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[H]aS_4.0_0.6B" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[l]ocate_qwen2_model" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[s]cripts/ocr_server.py" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[l]ocate_anything_server.py" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[l]ocate_anything_eval.py" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[l]ocate_anything_tile_eval.py" >/dev/null 2>&1 || true',
  'for port in 8080 8082 8090 8091 8118; do command -v fuser >/dev/null 2>&1 && fuser -k "${port}/tcp" >/dev/null 2>&1 || true; done',
].join('; ');

function parseEnv(filePath) {
  if (!existsSync(filePath)) return {};
  const values = {};
  for (const raw of readFileSync(filePath, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

function splitArgs(value) {
  if (!value) return [];
  const matches = String(value).match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g) || [];
  return matches.map((item) => item.replace(/^["']|["']$/g, ''));
}

function winToWsl(value) {
  const match = String(value).match(/^([A-Za-z]):[\\/](.*)$/);
  if (!match) return String(value).replace(/\\/g, '/');
  return `/mnt/${match[1].toLowerCase()}/${match[2].replace(/\\/g, '/')}`;
}

function wslToWin(value) {
  const match = String(value).match(/^\/mnt\/([a-zA-Z])\/(.*)$/);
  if (!match) return value;
  return `${match[1].toUpperCase()}:\\${match[2].replace(/\//g, '\\')}`;
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function wslEnvVar(name, fallback = '') {
  const value = env[name] ?? fallback;
  return `${name}=${shellQuote(value)}`;
}

function required(name) {
  const value = env[name];
  if (!value) throw new PublicStartupError('config', `missing ${name} (set it in .env)`);
  return value;
}

function getWslHost() {
  const result = spawnSync('wsl.exe', ['-e', 'bash', '-lc', "hostname -I | awk '{print $1}'"], {
    encoding: 'utf8',
  });
  const match = (result.stdout || '').match(/\b\d{1,3}(?:\.\d{1,3}){3}\b/);
  if (!match) {
    throw new PublicStartupError('wsl');
  }
  return match[0];
}

function preferWslUrl(value, port, suffix = '') {
  const raw = String(value || '').trim();
  if (!raw || /^https?:\/\/(127\.0\.0\.1|localhost)(:|\/|$)/i.test(raw)) {
    return `http://${wslHost}:${port}${suffix}`;
  }
  return raw;
}

const fileEnv = {
  ...parseEnv(path.join(backendDir, '.env')),
  ...parseEnv(path.join(repoRoot, '.env')),
};

// NOTE: .env file values intentionally take precedence over inherited shell
// variables (spread order below). The project .env files are the single source
// of truth for this local hybrid profile, so a stale exported variable in the
// calling shell cannot silently redirect a service.
const env = {
  ...process.env,
  ...fileEnv,
  PYTHONUNBUFFERED: '1',
  CUDA_VISIBLE_DEVICES: fileEnv.CUDA_VISIBLE_DEVICES || process.env.CUDA_VISIBLE_DEVICES || '0',
  OCR_VL_BACKEND: fileEnv.OCR_VL_BACKEND || 'vllm-server',
  OCR_VLLM_URL: fileEnv.OCR_VLLM_URL || 'http://127.0.0.1:8118/v1',
  OCR_VL_API_MODEL_NAME: fileEnv.OCR_VL_API_MODEL_NAME || 'PaddleOCR-VL-1.6-0.9B',
};

// Values that need WSL or .env resolution are initialized in initRuntimeConfig()
// (called from main()) so that failures route through main().catch and map to a
// PUBLIC_STARTUP_MESSAGES code. A top-level throw would bypass that handler.
let wslHost = '127.0.0.1';
let winEnv = { ...env, PYTHONPATH: backendDir };
let appPython = '';
let vllmPython = '';
let vllmBin = '';

const windowsVenv = env.WINDOWS_VENV_DIR || '.venv';
const windowsPython = env.WINDOWS_PYTHON || path.join(repoRoot, windowsVenv, 'Scripts', 'python.exe');
const locatePort = env.LOCATE_ANYTHING_PORT || '8090';
// PaddleOCR-VL is optional. Default OFF: the text path uses PP-StructureV3,
// so the heavy VL model is not started, freeing GPU memory for HaS / LocateAnything.
const ocrVlEnabled = !['0', 'false', 'no', 'off', ''].includes(
  String(env.OCR_VL_ENABLED ?? '0').trim().toLowerCase(),
);
const children = [];

function nvidiaDllDirs() {
  const root = path.join(path.dirname(path.dirname(windowsPython)), 'Lib', 'site-packages', 'nvidia');
  if (!existsSync(root)) return [];
  const dirs = [];
  for (const child of readdirSync(root, { withFileTypes: true })) {
    if (!child.isDirectory()) continue;
    const bin = path.join(root, child.name, 'bin');
    if (existsSync(bin)) dirs.push(bin);
  }
  return dirs;
}

function initRuntimeConfig() {
  wslHost = process.platform === 'win32' ? getWslHost() : '127.0.0.1';
  env.WSL_MODEL_HOST = wslHost;
  env.HAS_TEXT_RUNTIME = env.HAS_TEXT_RUNTIME || 'vllm';
  env.HAS_TEXT_VLLM_BASE_URL = preferWslUrl(env.HAS_TEXT_VLLM_BASE_URL, 8080, '/v1');
  env.OCR_BASE_URL = preferWslUrl(env.OCR_BASE_URL, 8082);
  env.LOCATE_ANYTHING_ENABLED = env.LOCATE_ANYTHING_ENABLED || '1';
  env.VISUAL_FEATURES_BASE_URL = preferWslUrl(env.VISUAL_FEATURES_BASE_URL, Number(env.LOCATE_ANYTHING_PORT || 8090));
  appPython = path.posix.join(required('VENV_DIR'), 'bin', 'python');
  vllmPython = path.posix.join(required('VLLM_VENV_DIR'), 'bin', 'python');
  vllmBin = path.posix.join(required('VLLM_VENV_DIR'), 'bin', 'vllm');
  winEnv = { ...env, PYTHONPATH: backendDir };
  winEnv.OCR_VL_ENABLED = ocrVlEnabled ? '1' : '0';
  winEnv.PATH = [...nvidiaDllDirs(), path.dirname(windowsPython), process.env.PATH || ''].join(path.delimiter);
}

function logPath(name) {
  return path.join(logsDir, `${name}.log`);
}

function pipe(name, stream, out) {
  let buffer = '';
  stream.on('data', (chunk) => {
    buffer += chunk.toString();
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || '';
    for (const line of lines) {
      const text = `[${name}] ${line}\n`;
      process.stdout.write(text);
      out.write(text);
    }
  });
}

function spawnLogged(name, command, args, options = {}) {
  const out = createWriteStream(logPath(name), { flags: 'a' });
  out.write(`\n\n===== ${new Date().toISOString()} ${command} ${args.join(' ')} =====\n`);
  const child = spawn(command, args, {
    cwd: options.cwd || repoRoot,
    env: options.env || winEnv,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  children.push(child);
  // Resolves when the process exits; lets waitJson fail fast on early crashes
  // instead of polling a dead service until timeout.
  child.exited = new Promise((resolve) => {
    child.on('exit', (code, signal) => resolve({ code, signal }));
    child.on('error', () => resolve({ code: null, signal: null }));
  });
  pipe(name, child.stdout, out);
  pipe(name, child.stderr, out);
  child.on('exit', (code, signal) => {
    const message = `[dev] ${name} exited code=${code ?? ''} signal=${signal ?? ''}\n`;
    process.stdout.write(message);
    out.write(message);
  });
  child.on('error', () => {
    const msg = `[dev] ${name} failed to start\n`;
    process.stdout.write(msg);
    out.write(msg);
  });
  console.log(`[dev] started ${name} pid=${child.pid}`);
  return child;
}

function spawnWsl(name, command) {
  return spawnLogged(name, 'wsl.exe', ['-e', 'bash', '-lc', command], { cwd: repoRoot, env: process.env });
}

function probePort(host, port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port, timeout: 1000 });
    socket.on('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.on('timeout', () => {
      socket.destroy();
      resolve(false);
    });
    socket.on('error', () => resolve(false));
  });
}

// One-shot pre-spawn check: a listener on the target port means a previous
// session (or its corpse) is still holding it; starting on top of it would make
// waitJson probe the wrong process.
async function ensurePortFree(port, label, host = '127.0.0.1') {
  if (await probePort(host, port)) {
    throw new PublicStartupError('port', `port ${port} (${label}) is already in use; run "npm run stop" first`);
  }
}

async function waitPort(port, label, timeoutMs = 240000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await probePort('127.0.0.1', port)) return;
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  throw new PublicStartupError('service', `${label} did not open port ${port} before timeout`);
}

async function waitJson(url, predicate, label, timeoutMs = 240000, child = null) {
  let last = '';
  const poll = async () => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      try {
        const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
        if (response.ok) {
          const body = await response.json();
          if (!predicate || predicate(body)) return body;
          last = JSON.stringify(body).slice(0, 240);
        } else {
          last = `${response.status} ${response.statusText}`;
        }
      } catch {
        last = 'request failed';
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new PublicStartupError('service', `${label} not ready before timeout; last health response: ${last || 'none'}`);
  };
  if (!child || !child.exited) return poll();
  // Fail fast when the service process dies before reporting ready.
  const crashed = child.exited.then(({ code, signal }) => {
    throw new PublicStartupError(
      'service',
      `${label} exited (code=${code ?? ''} signal=${signal ?? ''}) before becoming ready; inspect logs/${label}.log`,
    );
  });
  crashed.catch(() => {}); // surfaced via race during startup; ignore later exits
  return Promise.race([poll(), crashed]);
}

async function startVllmServices() {
  const wslRoot = winToWsl(repoRoot);
  const cuda = shellQuote(env.CUDA_VISIBLE_DEVICES || '0');

  await ensurePortFree(8080, 'has-text-vllm', wslHost);
  const hasTextVllm = spawnWsl(
    'has-text-vllm',
    [
      `cd ${shellQuote(wslRoot)} &&`,
      `CUDA_VISIBLE_DEVICES=${cuda}`,
      shellQuote(vllmPython),
      shellQuote(vllmBin),
      'serve',
      shellQuote(required('HAS_TEXT_HF_MODEL_PATH')),
      '--host 0.0.0.0 --port 8080',
      `--served-model-name ${shellQuote(env.HAS_TEXT_MODEL_NAME || 'HaS_4.0_0.6B')}`,
      '--trust-remote-code',
      ...splitArgs(env.HAS_TEXT_VLLM_EXTRA_ARGS).map(shellQuote),
    ].join(' '),
  );
  await waitJson(`http://${wslHost}:8080/v1/models`, (body) => Array.isArray(body.data), 'has-text-vllm', 720000, hasTextVllm);

  // LocateAnything Qwen2 text backbone served by vLLM (prompt-embeds). The
  // LocateAnything service (8090) runs the MoonViT vision tower locally and
  // posts stitched image+text embeds here. Only started in vLLM mode.
  if ((env.LOCATE_ANYTHING_ENABLED || '1') !== '0' && (env.LOCATE_ANYTHING_VLLM_URL || '').trim()) {
    const locateLmModel = env.LOCATE_ANYTHING_LM_MODEL_DIR || '/mnt/d/has_models/locate_qwen2_model';
    await ensurePortFree(8091, 'locate-lm-vllm', wslHost);
    const locateLmVllm = spawnWsl(
      'locate-lm-vllm',
      [
        `cd ${shellQuote(wslRoot)} &&`,
        `CUDA_VISIBLE_DEVICES=${cuda}`,
        'HF_HUB_OFFLINE=1',
        'PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True',
        shellQuote(vllmPython),
        shellQuote(vllmBin),
        'serve',
        shellQuote(locateLmModel),
        `--served-model-name ${shellQuote(env.LOCATE_ANYTHING_VLLM_MODEL || 'locate_qwen2_model')}`,
        '--host 0.0.0.0 --port 8091',
        '--enable-prompt-embeds',
        ...splitArgs(env.LOCATE_ANYTHING_LM_VLLM_EXTRA_ARGS).map(shellQuote),
      ].join(' '),
    );
    await waitJson(`http://${wslHost}:8091/v1/models`, (body) => Array.isArray(body.data), 'locate-lm-vllm', 720000, locateLmVllm);
  }

  // PaddleOCR-VL last: vLLM's KV sizing charges concurrent residents against
  // its own budget window, and the LocateAnything LM (the largest engine) only
  // initializes cleanly when 8118 is not yet resident. The steady-state mix
  // fits; the order is what makes the cold start deterministic.
  if (ocrVlEnabled) {
    await ensurePortFree(8118, 'paddle-vllm', wslHost);
    const paddleVllm = spawnWsl(
      'paddle-vllm',
      [
        `cd ${shellQuote(wslRoot)} &&`,
        `CUDA_VISIBLE_DEVICES=${cuda}`,
        shellQuote(vllmPython),
        shellQuote(vllmBin),
        'serve PaddlePaddle/PaddleOCR-VL-1.6',
        '--host 0.0.0.0 --port 8118',
        '--served-model-name PaddleOCR-VL-1.6-0.9B',
        '--trust-remote-code',
        ...splitArgs(env.VLLM_EXTRA_ARGS).map(shellQuote),
      ].join(' '),
    );
    await waitJson(`http://${wslHost}:8118/v1/models`, (body) => Array.isArray(body.data), 'paddle-vllm', 720000, paddleVllm);
  } else {
    console.log('[dev] PaddleOCR-VL (8118) skipped: text path uses PP-StructureV3 (set OCR_VL_ENABLED=1 to enable VL)');
  }
}

async function startOcrWrapper() {
  const wslBackend = winToWsl(backendDir);
  const cuda = shellQuote(env.CUDA_VISIBLE_DEVICES || '0');
  await ensurePortFree(8082, 'ocr-wrapper', wslHost);
  const ocrWrapper = spawnWsl(
    'ocr-wrapper',
    [
      `cd ${shellQuote(wslBackend)} &&`,
      `CUDA_VISIBLE_DEVICES=${cuda}`,
      `PYTHONPATH=${shellQuote(wslBackend)}`,
      `OCR_VL_ENABLED=${shellQuote(ocrVlEnabled ? '1' : '0')}`,
      `OCR_VL_BACKEND=${shellQuote(ocrVlEnabled ? (env.OCR_VL_BACKEND || 'vllm-server') : '')}`,
      `OCR_VLLM_URL=${shellQuote(env.OCR_VLLM_URL || 'http://127.0.0.1:8118/v1')}`,
      `OCR_VL_API_MODEL_NAME=${shellQuote(env.OCR_VL_API_MODEL_NAME || 'PaddleOCR-VL-1.6-0.9B')}`,
      wslEnvVar('OCR_MAX_IMAGE_SIDE', '2048'),
      wslEnvVar('OCR_MAX_NEW_TOKENS', '2048'),
      wslEnvVar('OCR_VL_WARMUP', ocrVlEnabled ? '1' : '0'),
      wslEnvVar('OCR_STRUCTURE_ENABLED', '1'),
      wslEnvVar('OCR_STRUCTURE_PRIMARY', '1'),
      wslEnvVar('OCR_STRUCTURE_WARMUP', '1'),
      wslEnvVar('OCR_STRUCTURE_RELEASE_AFTER_REQUEST', '0'),
      `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=${shellQuote(env.PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK || 'True')}`,
      shellQuote(appPython),
      'scripts/ocr_server.py',
    ].join(' '),
  );
  await waitJson(`http://${wslHost}:8082/health`, (body) => body.ready === true, 'ocr-wrapper', 720000, ocrWrapper);
}

async function startLocateAnything() {
  const wslRoot = winToWsl(repoRoot);
  const wslBackend = winToWsl(backendDir);
  const cuda = shellQuote(env.CUDA_VISIBLE_DEVICES || '0');
  const locateDeps = env.LOCATE_ANYTHING_DEPS || '/home/tracy/.cache/datainfra-redaction/locateanything-hf-deps';
  const locatePythonPath = [locateDeps, path.posix.join(wslBackend, 'scripts'), wslBackend].join(':');
  await ensurePortFree(Number(locatePort), 'locateanything', wslHost);
  const locateAnything = spawnWsl(
    'locateanything',
    [
      `cd ${shellQuote(wslRoot)} &&`,
      `CUDA_VISIBLE_DEVICES=${cuda}`,
      'HF_HUB_OFFLINE=1',
      'PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True',
      wslEnvVar('LOCATE_ANYTHING_MODEL_NAME', 'LocateAnything-3B'),
      wslEnvVar('LOCATE_ANYTHING_MAX_IMAGE_SIDE', '1280'),
      wslEnvVar('LOCATE_ANYTHING_SIGNATURE_MAX_IMAGE_SIDE', '1280'),
      wslEnvVar('LOCATE_ANYTHING_SIGNATURE_TILE_MAX_IMAGE_SIDE', '1280'),
      wslEnvVar('LOCATE_ANYTHING_MAX_NEW_TOKENS', '8192'),
      wslEnvVar('LOCATE_ANYTHING_GENERATION_MODE', 'hybrid'),
      wslEnvVar('LOCATE_ANYTHING_FAST_FIRST', '1'),
      wslEnvVar('LOCATE_ANYTHING_FAST_FIRST_FALLBACK_ON_EMPTY', '1'),
      wslEnvVar('LOCATE_ANYTHING_SIGNATURE_TILE_FALLBACK_MAX_TILES', '1'),
      wslEnvVar('LOCATE_ANYTHING_TEMPERATURE', '0.7'),
      wslEnvVar('LOCATE_ANYTHING_VLLM_URL', ''),
      wslEnvVar('LOCATE_ANYTHING_VLLM_MODEL', 'locate_qwen2_model'),
      `PYTHONPATH=${shellQuote(locatePythonPath)}`,
      shellQuote(vllmPython),
      'backend/scripts/locate_anything_server.py',
      '--model',
      shellQuote(env.LOCATE_ANYTHING_MODEL || '/mnt/d/has_models/LocateAnything-3B-HF'),
      '--backend',
      shellQuote(env.LOCATE_ANYTHING_BACKEND || 'hf'),
      '--host',
      '0.0.0.0',
      '--port',
      shellQuote(locatePort),
      '--dtype',
      shellQuote(env.LOCATE_ANYTHING_DTYPE || 'bfloat16'),
    ].join(' '),
  );
  await waitJson(`http://${wslHost}:${locatePort}/health`, (body) => body.ready === true, 'locateanything', 720000, locateAnything);
}

async function runWarmup() {
  console.log('[dev] running warmup (best-effort)');
  const child = spawnLogged('warmup', windowsPython, ['scripts/warmup_models.py'], { cwd: backendDir, env: winEnv });
  // Warmup is a pre-load optimization, not a readiness gate: every service was
  // already confirmed online via waitJson before this. A slow cold inference
  // (e.g. the 3B LocateAnything first /detect) must NOT tear down a healthy
  // stack, so treat warmup as best-effort and continue regardless of exit code.
  await new Promise((resolve) => {
    child.on('exit', (code) => {
      if (code !== 0) {
        console.log(`[dev] warmup exited code=${code}; continuing (models are up, first request may be slower)`);
      }
      resolve();
    });
    child.on('error', () => resolve());
  });
}

function ensureWindowsVenv() {
  if (!existsSync(windowsPython)) {
    throw new PublicStartupError('venv');
  }
}

async function main() {
  if (process.platform !== 'win32') {
    throw new PublicStartupError('platform');
  }
  initRuntimeConfig();
  ensureWindowsVenv();

  await startVllmServices();

  if ((env.LOCATE_ANYTHING_ENABLED || '1') !== '0') {
    await startLocateAnything();
  }

  await startOcrWrapper();

  if ((env.LOCATE_ANYTHING_ENABLED || '1') !== '0') {
    await waitJson(`${env.VISUAL_FEATURES_BASE_URL || `http://127.0.0.1:${locatePort}`}/health`, (body) => body.ready === true, 'visual-features', 180000);
  }

  await ensurePortFree(8000, 'backend');
  const backendChild = spawnLogged('backend', windowsPython, ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000'], {
    cwd: backendDir,
    env: winEnv,
  });
  await waitJson('http://127.0.0.1:8000/health/services', (body) => body.all_online === true, 'backend', 180000, backendChild);

  await runWarmup();

  await ensurePortFree(3000, 'frontend');
  const frontendCommand = process.platform === 'win32' ? 'cmd.exe' : 'npm';
  const frontendArgs =
    process.platform === 'win32'
      ? ['/d', '/s', '/c', 'npm run dev -- --host 0.0.0.0 --port 3000 --strictPort']
      : ['run', 'dev', '--', '--host', '0.0.0.0', '--port', '3000', '--strictPort'];
  spawnLogged('frontend', frontendCommand, frontendArgs, {
    cwd: frontendDir,
    env: process.env,
  });
  await waitPort(3000, 'frontend', 120000);

  console.log('[dev] ready: http://localhost:3000');
  await new Promise(() => {});
}

function shutdown(code = 0) {
  if (children.length > 0 && process.platform === 'win32') {
    // SIGTERM on the wsl.exe relay never reaches the Linux-side vllm/ocr
    // processes; they would keep the GPU allocated and OOM the next start.
    // Run the same cleanup as scripts/stop-dev.mjs first. Skipped when nothing
    // was spawned (e.g. a port-in-use abort) so a healthy session started from
    // another terminal is not torn down.
    console.log('[dev] stopping WSL model services...');
    spawnSync('wsl.exe', ['-e', 'bash', '-lc', WSL_KILL_SEQUENCE], { stdio: 'ignore' });
  }
  for (const child of children.reverse()) {
    if (!child.pid || child.killed) continue;
    if (process.platform === 'win32') {
      // taskkill /T kills the whole process tree (e.g. cmd.exe -> npm -> vite),
      // which child.kill('SIGTERM') cannot do on Windows.
      spawnSync('taskkill', ['/T', '/F', '/PID', String(child.pid)], { stdio: 'ignore' });
    } else {
      child.kill('SIGTERM');
    }
  }
  process.exit(code);
}

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

main().catch((err) => {
  const code = err instanceof PublicStartupError ? err.code : 'generic';
  console.error(`[dev] ${PUBLIC_STARTUP_MESSAGES[code] || PUBLIC_STARTUP_MESSAGES.generic}`);
  if (err instanceof PublicStartupError) {
    if (err.detail) console.error(`[dev] detail: ${err.detail}`);
  } else {
    console.error(err);
  }
  shutdown(1);
});
