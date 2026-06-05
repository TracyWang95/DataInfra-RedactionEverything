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
  constructor(code) {
    super('startup failed');
    this.code = code;
  }
}

const PUBLIC_STARTUP_MESSAGES = {
  config: 'Missing required local configuration. Check .env and .env.example.',
  wsl: 'Could not resolve WSL IP. Start from Windows with WSL available.',
  service: 'A required local service was not ready before timeout. Inspect logs/dev-session.log.',
  warmup: 'Model warmup failed. Inspect logs/warmup.log and service logs.',
  venv: 'Missing Windows project venv. Create the project .venv once, then run npm run dev again.',
  platform: 'This local hybrid profile must be started from Windows.',
  generic: 'startup failed; inspect logs/dev-session.log and per-service logs for details.',
};

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
  if (!value) throw new PublicStartupError('config');
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

const env = {
  ...process.env,
  ...fileEnv,
  PYTHONUNBUFFERED: '1',
  CUDA_VISIBLE_DEVICES: fileEnv.CUDA_VISIBLE_DEVICES || process.env.CUDA_VISIBLE_DEVICES || '0',
  OCR_VL_BACKEND: fileEnv.OCR_VL_BACKEND || 'vllm-server',
  OCR_VLLM_URL: fileEnv.OCR_VLLM_URL || 'http://127.0.0.1:8118/v1',
  OCR_VL_API_MODEL_NAME: fileEnv.OCR_VL_API_MODEL_NAME || 'PaddleOCR-VL-1.6-0.9B',
};

const wslHost = process.platform === 'win32' ? getWslHost() : '127.0.0.1';
env.WSL_MODEL_HOST = wslHost;
env.HAS_TEXT_RUNTIME = env.HAS_TEXT_RUNTIME || 'vllm';
env.HAS_TEXT_VLLM_BASE_URL = preferWslUrl(env.HAS_TEXT_VLLM_BASE_URL, 8080, '/v1');
env.OCR_BASE_URL = preferWslUrl(env.OCR_BASE_URL, 8082);
env.LOCATE_ANYTHING_ENABLED = env.LOCATE_ANYTHING_ENABLED || '1';
env.VISUAL_FEATURES_BASE_URL = preferWslUrl(env.VISUAL_FEATURES_BASE_URL, Number(env.LOCATE_ANYTHING_PORT || 8090));
const winEnv = { ...env, PYTHONPATH: backendDir };

const windowsVenv = env.WINDOWS_VENV_DIR || '.venv';
const windowsPython = env.WINDOWS_PYTHON || path.join(repoRoot, windowsVenv, 'Scripts', 'python.exe');
const appPython = path.posix.join(required('VENV_DIR'), 'bin', 'python');
const vllmPython = path.posix.join(required('VLLM_VENV_DIR'), 'bin', 'python');
const vllmBin = path.posix.join(required('VLLM_VENV_DIR'), 'bin', 'vllm');
const locatePort = env.LOCATE_ANYTHING_PORT || '8090';
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

winEnv.PATH = [...nvidiaDllDirs(), path.dirname(windowsPython), process.env.PATH || ''].join(path.delimiter);

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

async function waitPort(port, label, timeoutMs = 240000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const ok = await new Promise((resolve) => {
      const socket = net.createConnection({ host: '127.0.0.1', port, timeout: 1000 });
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
    if (ok) return;
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  throw new PublicStartupError('service');
}

async function waitJson(url, predicate, label, timeoutMs = 240000) {
  const start = Date.now();
  let last = '';
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
  throw new PublicStartupError('service');
}

async function startVllmServices() {
  const wslRoot = winToWsl(repoRoot);
  const cuda = shellQuote(env.CUDA_VISIBLE_DEVICES || '0');
  spawnWsl(
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
  await waitJson(`http://${wslHost}:8118/v1/models`, (body) => Array.isArray(body.data), 'paddle-vllm', 720000);

  spawnWsl(
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
  await waitJson(`http://${wslHost}:8080/v1/models`, (body) => Array.isArray(body.data), 'has-text-vllm', 720000);
}

async function startOcrWrapper() {
  const wslBackend = winToWsl(backendDir);
  const cuda = shellQuote(env.CUDA_VISIBLE_DEVICES || '0');
  spawnWsl(
    'ocr-wrapper',
    [
      `cd ${shellQuote(wslBackend)} &&`,
      `CUDA_VISIBLE_DEVICES=${cuda}`,
      `PYTHONPATH=${shellQuote(wslBackend)}`,
      `OCR_VL_BACKEND=${shellQuote(env.OCR_VL_BACKEND || 'vllm-server')}`,
      `OCR_VLLM_URL=${shellQuote(env.OCR_VLLM_URL || 'http://127.0.0.1:8118/v1')}`,
      `OCR_VL_API_MODEL_NAME=${shellQuote(env.OCR_VL_API_MODEL_NAME || 'PaddleOCR-VL-1.6-0.9B')}`,
      wslEnvVar('OCR_MAX_IMAGE_SIDE', '2048'),
      wslEnvVar('OCR_MAX_NEW_TOKENS', '2048'),
      wslEnvVar('OCR_VL_WARMUP', '1'),
      wslEnvVar('OCR_STRUCTURE_ENABLED', '0'),
      wslEnvVar('OCR_STRUCTURE_PRIMARY', '0'),
      wslEnvVar('OCR_STRUCTURE_WARMUP', '0'),
      wslEnvVar('OCR_STRUCTURE_RELEASE_AFTER_REQUEST', '0'),
      `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=${shellQuote(env.PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK || 'True')}`,
      shellQuote(appPython),
      'scripts/ocr_server.py',
    ].join(' '),
  );
  await waitJson(`http://${wslHost}:8082/health`, (body) => body.ready === true, 'ocr-wrapper', 720000);
}

async function startLocateAnything() {
  const wslRoot = winToWsl(repoRoot);
  const wslBackend = winToWsl(backendDir);
  const cuda = shellQuote(env.CUDA_VISIBLE_DEVICES || '0');
  const locateDeps = env.LOCATE_ANYTHING_DEPS || '/home/tracy/.cache/datainfra-redaction/locateanything-hf-deps';
  const locatePythonPath = [locateDeps, path.posix.join(wslBackend, 'scripts'), wslBackend].join(':');
  spawnWsl(
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
  await waitJson(`http://${wslHost}:${locatePort}/health`, (body) => body.ready === true, 'locateanything', 720000);
}

async function runWarmup() {
  console.log('[dev] running warmup');
  const child = spawnLogged('warmup', windowsPython, ['scripts/warmup_models.py'], { cwd: backendDir, env: winEnv });
  await new Promise((resolve, reject) => {
    child.on('exit', (code) =>
      code === 0 ? resolve() : reject(new PublicStartupError('warmup')),
    );
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
  ensureWindowsVenv();

  await startVllmServices();

  if ((env.LOCATE_ANYTHING_ENABLED || '1') !== '0') {
    await startLocateAnything();
  }

  await startOcrWrapper();

  await waitJson(`${env.VISUAL_FEATURES_BASE_URL || `http://127.0.0.1:${locatePort}`}/health`, (body) => body.ready === true, 'visual-features', 180000);

  spawnLogged('backend', windowsPython, ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000'], {
    cwd: backendDir,
    env: winEnv,
  });
  await waitJson('http://127.0.0.1:8000/health/services', (body) => body.all_online === true, 'backend', 180000);

  await runWarmup();

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
  for (const child of children.reverse()) {
    if (!child.killed) child.kill('SIGTERM');
  }
  setTimeout(() => process.exit(code), children.length ? 1500 : 0);
}

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

main().catch(() => {
  console.error(`[dev] ${PUBLIC_STARTUP_MESSAGES.generic}`);
  shutdown(1);
});
