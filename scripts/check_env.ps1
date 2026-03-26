$ErrorActionPreference = "SilentlyContinue"

function Write-Check($name, $ok, $detail = "") {
  if ($ok) {
    Write-Host "[OK]  $name $detail" -ForegroundColor Green
  } else {
    Write-Host "[ERR] $name $detail" -ForegroundColor Red
  }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Legal Redaction 环境检查" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ========== 基础命令 ==========
Write-Host ">> 基础环境" -ForegroundColor Yellow
Write-Check "python" (Get-Command python -ErrorAction SilentlyContinue) ""
Write-Check "node" (Get-Command node -ErrorAction SilentlyContinue) ""
Write-Check "npm" (Get-Command npm -ErrorAction SilentlyContinue) ""
Write-Host ""

# ========== CUDA / NVIDIA ==========
Write-Host ">> GPU 环境" -ForegroundColor Yellow
$nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidia) {
  Write-Check "nvidia-smi" $true ""
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | ForEach-Object { Write-Host "   GPU: $_" }
} else {
  Write-Check "nvidia-smi" $false "(未找到 NVIDIA 驱动)"
}
Write-Host ""

# ========== 模型文件（提示用户自行确认路径） ==========
Write-Host ">> 模型文件（请根据实际路径调整）" -ForegroundColor Yellow
Write-Host "   请确保以下文件存在："
Write-Host "   - llama-server 可执行文件"
Write-Host "   - HaS NER .gguf（见 start_has.ps1）"
Write-Host "   - HaS Image: backend\models\has_image\sensitive_seg_best.pt（或 HAS_IMAGE_WEIGHTS）"
Write-Host ""

# ========== 端口占用 ==========
Write-Host ">> 服务端口" -ForegroundColor Yellow

function Check-Port($port, $name) {
  $p = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  Write-Check $name ($null -ne $p) "(port $port)"
}

Check-Port 8081 "HaS Image (YOLO) 服务"
Check-Port 8080 "HaS NER 服务"
Check-Port 8000 "后端 API"
Check-Port 3000 "前端"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  检查完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
