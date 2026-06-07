# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

# Legacy Windows helper for starting only the HaS Text service with llama-server.
# The main supported dev entry is still `npm run dev:models` from WSL/Linux.

$ErrorActionPreference = "Stop"

$CanonicalModelName = "HaS_Text_0209_0.6B_Q4_K_M.gguf"
$UpstreamModelName = "has_4.0_0.6B.gguf"
$Port = if ($env:HAS_TEXT_PORT) { [int]$env:HAS_TEXT_PORT } else { 8080 }
$HostName = if ($env:HAS_TEXT_HOST) { $env:HAS_TEXT_HOST } else { "0.0.0.0" }
$ContextLength = if ($env:HAS_TEXT_N_CTX) { [int]$env:HAS_TEXT_N_CTX } else { 8192 }
$GpuLayers = if ($env:HAS_TEXT_N_GPU_LAYERS) { [int]$env:HAS_TEXT_N_GPU_LAYERS } else { -1 }

$CandidateModels = @()
if ($env:HAS_MODEL_PATH) {
    $CandidateModels += $env:HAS_MODEL_PATH
}
$CandidateModels += @(
    (Join-Path $PSScriptRoot "models\has\$CanonicalModelName"),
    "D:\has_models\$CanonicalModelName",
    (Join-Path $PSScriptRoot "models\has\$UpstreamModelName")
)

$ModelPath = $CandidateModels | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  HaS Text local model service" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if (-Not $ModelPath) {
    Write-Host ""
    Write-Host "ERROR: HaS Text model file was not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Expected project filename:" -ForegroundColor Yellow
    Write-Host "  $CanonicalModelName" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Recommended setup is documented in docs/MODELS.md." -ForegroundColor Yellow
    Write-Host "Typical Windows/WSL target: D:\has_models\$CanonicalModelName" -ForegroundColor Cyan
    Write-Host "Docker target: backend\models\has\$CanonicalModelName" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "If you only have the upstream file, rename or copy:" -ForegroundColor Yellow
    Write-Host "  $UpstreamModelName -> $CanonicalModelName" -ForegroundColor Cyan
    exit 1
}

$LlamaServer = $null
$PossiblePaths = @(
    "llama-server",
    "llama-server.exe",
    "$env:USERPROFILE\.llama\llama-server.exe",
    "C:\llama.cpp\build\bin\Release\llama-server.exe",
    "C:\llama.cpp\llama-server.exe"
)

foreach ($PathCandidate in $PossiblePaths) {
    if (Get-Command $PathCandidate -ErrorAction SilentlyContinue) {
        $LlamaServer = $PathCandidate
        break
    }
    if (Test-Path -LiteralPath $PathCandidate) {
        $LlamaServer = $PathCandidate
        break
    }
}

if (-Not $LlamaServer) {
    Write-Host ""
    Write-Host "ERROR: llama-server was not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install llama.cpp or run the supported Python helper instead:" -ForegroundColor Yellow
    Write-Host "  python backend\scripts\start_has_python.py" -ForegroundColor Cyan
    exit 1
}

Write-Host ""
Write-Host "Model path: $ModelPath" -ForegroundColor Green
Write-Host "Server URL: http://${HostName}:$Port/v1" -ForegroundColor Green
Write-Host "Context length: $ContextLength" -ForegroundColor Green
Write-Host "GPU layers: $GpuLayers (-1 = all layers; 0 = CPU/debug only)" -ForegroundColor Green
Write-Host "Using llama-server: $LlamaServer" -ForegroundColor Green
Write-Host ""

& $LlamaServer -m $ModelPath --host $HostName --port $Port --ctx-size $ContextLength --n-gpu-layers $GpuLayers
