#!/usr/bin/env node
import { spawnSync } from 'node:child_process';

const ports = [3000, 8000, 8080, 8082, 8090, 8118];

function run(command, args) {
  spawnSync(command, args, { stdio: 'inherit' });
}

if (process.platform === 'win32') {
  run('wsl.exe', [
    '-e',
    'bash',
    '-lc',
    [
      'set +e',
      'pkill -TERM -f "/home/tracy/.cache/datainfra-redaction/.venv-vllm/bin/vllm" >/dev/null 2>&1 || true',
      'pkill -TERM -f "PaddlePaddle/PaddleOCR-VL" >/dev/null 2>&1 || true',
      'pkill -TERM -f "HaS_4.0_0.6B" >/dev/null 2>&1 || true',
      'pkill -TERM -f "scripts/ocr_server.py" >/dev/null 2>&1 || true',
      'pkill -TERM -f "locate_anything_server.py" >/dev/null 2>&1 || true',
      'pkill -TERM -f "locate_anything_eval.py" >/dev/null 2>&1 || true',
      'pkill -TERM -f "locate_anything_tile_eval.py" >/dev/null 2>&1 || true',
      'pkill -TERM -f "locateanything_load_sleep.py" >/dev/null 2>&1 || true',
      'sleep 2',
      'pkill -KILL -f "/home/tracy/.cache/datainfra-redaction/.venv-vllm/bin/vllm" >/dev/null 2>&1 || true',
      'pkill -KILL -f "PaddlePaddle/PaddleOCR-VL" >/dev/null 2>&1 || true',
      'pkill -KILL -f "HaS_4.0_0.6B" >/dev/null 2>&1 || true',
      'pkill -KILL -f "scripts/ocr_server.py" >/dev/null 2>&1 || true',
      'pkill -KILL -f "locate_anything_server.py" >/dev/null 2>&1 || true',
      'pkill -KILL -f "locate_anything_eval.py" >/dev/null 2>&1 || true',
      'pkill -KILL -f "locate_anything_tile_eval.py" >/dev/null 2>&1 || true',
      'pkill -KILL -f "locateanything_load_sleep.py" >/dev/null 2>&1 || true',
      'for port in 8080 8082 8090 8118; do command -v fuser >/dev/null 2>&1 && fuser -k "${port}/tcp" >/dev/null 2>&1 || true; done',
    ].join('; '),
  ]);

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
      "  ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'locate_anything_server\\.py') -or",
      "  ($_.Name -eq 'node.exe' -and $_.CommandLine -match 'vite' -and $_.CommandLine -match '--port 3000')",
      '}',
      '$targets | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }',
    ].join('\n'),
  ]);
} else {
  run('bash', [
    '-lc',
    [
      'pkill -f "vllm serve|scripts/ocr_server.py|uvicorn app.main:app|vite --host|llama-server" >/dev/null 2>&1 || true',
      'for port in 3000 8000 8080 8082 8090 8118; do command -v fuser >/dev/null 2>&1 && fuser -k "${port}/tcp" >/dev/null 2>&1 || true; done',
    ].join('; '),
  ]);
}

console.log('[stop] done');
