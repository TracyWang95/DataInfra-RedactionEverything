#!/usr/bin/env node
import { spawnSync } from 'node:child_process';

const ports = [3000, 8000, 8080, 8081, 8082, 8090, 8120, 8130];

// WSL-side process cleanup. KEEP IN SYNC with the identical WSL_KILL_SEQUENCE
// in scripts/dev.mjs (shutdown() runs the same sequence on Ctrl+C; update both
// together). Patterns match process features instead of absolute venv paths so
// they work on any machine. The [x] first-character bracket prevents pkill -f
// from matching this very `bash -lc` command line (a self-kill would abort the
// sequence midway). "[v]llm serve" covers all vLLM servers
// (8118 paddle / 8080 has-text / 8120 glm-vllm).
const WSL_KILL_SEQUENCE = [
  'set +e',
  'pkill -TERM -f "[v]llm serve" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[P]addlePaddle/PaddleOCR-VL" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[H]aS_4.0_0.6B" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[g]lm-fp8" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[s]cripts/ocr_server.py" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[g]lm_visual_server.py" >/dev/null 2>&1 || true',
  'pkill -TERM -f "[h]as_image_server.py" >/dev/null 2>&1 || true',
  'sleep 2',
  'pkill -KILL -f "[v]llm serve" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[P]addlePaddle/PaddleOCR-VL" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[H]aS_4.0_0.6B" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[g]lm-fp8" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[s]cripts/ocr_server.py" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[g]lm_visual_server.py" >/dev/null 2>&1 || true',
  'pkill -KILL -f "[h]as_image_server.py" >/dev/null 2>&1 || true',
  'for port in 8080 8081 8082 8090 8120 8130; do command -v fuser >/dev/null 2>&1 && fuser -k "${port}/tcp" >/dev/null 2>&1 || true; done',
].join('; ');

function run(command, args) {
  spawnSync(command, args, { stdio: 'inherit' });
}

if (process.platform === 'win32') {
  run('wsl.exe', ['-e', 'bash', '-lc', WSL_KILL_SEQUENCE]);

  run('powershell.exe', [
    '-NoProfile',
    '-Command',
    [
      "$ErrorActionPreference='SilentlyContinue'",
      `$ports=@(${ports.join(',')})`,
      'foreach($port in $ports){',
      '  Get-NetTCPConnection -LocalPort $port -State Listen | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ } | ForEach-Object { Stop-Process -Id $_ -Force }',
      '}',
      "$targets=Get-CimInstance Win32_Process | Where-Object {",
      "  ($_.Name -eq 'node.exe' -and $_.CommandLine -match 'scripts[\\\\/]dev\\.mjs') -or",
      "  ($_.Name -eq 'cmd.exe' -and $_.CommandLine -match 'node scripts[\\\\/]dev\\.mjs') -or",
      "  ($_.Name -eq 'llama-server.exe' -and $_.CommandLine -match '--port 8090') -or",
      "  ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'uvicorn app\\.main:app') -or",
      "  ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'glm_visual_server\\.py') -or",
      "  ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'has_image_server\\.py') -or",
      "  ($_.Name -eq 'node.exe' -and $_.CommandLine -match 'vite' -and $_.CommandLine -match '--port 3000')",
      '}',
      '$targets | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }',
    ].join('\n'),
  ]);
} else {
  run('bash', [
    '-lc',
    [
      'pkill -f "vllm serve|scripts/ocr_server.py|scripts/glm_visual_server.py|scripts/has_image_server.py|uvicorn app.main:app|vite --host|llama-server" >/dev/null 2>&1 || true',
      'for port in 3000 8000 8080 8081 8082 8090 8120 8130; do command -v fuser >/dev/null 2>&1 && fuser -k "${port}/tcp" >/dev/null 2>&1 || true; done',
    ].join('; '),
  ]);
}

console.log('[stop] done');
