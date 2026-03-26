# HaS 模型服务启动脚本
# 使用 llama.cpp 运行 HaS 4.0 0.6B GGUF 模型

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  HaS 本地模型服务启动脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$MODEL_PATH = ".\models\has\has_4.0_0.6B.gguf"
$PORT = 8080

# 检查模型文件
if (-Not (Test-Path $MODEL_PATH)) {
    Write-Host "错误: 模型文件不存在: $MODEL_PATH" -ForegroundColor Red
    Write-Host "请先下载模型: huggingface-cli download xuanwulab/HaS_4.0_0.6B_GGUF has_4.0_0.6B.gguf --local-dir .\models\has" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "模型路径: $MODEL_PATH" -ForegroundColor Green
Write-Host "服务端口: $PORT" -ForegroundColor Green
Write-Host ""

# 检查 llama-server 是否存在
$LLAMA_SERVER = $null

# 尝试常见的 llama.cpp 安装位置
$possiblePaths = @(
    "llama-server",
    "llama-server.exe",
    "$env:USERPROFILE\.llama\llama-server.exe",
    "C:\llama.cpp\build\bin\Release\llama-server.exe",
    "C:\llama.cpp\llama-server.exe"
)

foreach ($path in $possiblePaths) {
    if (Get-Command $path -ErrorAction SilentlyContinue) {
        $LLAMA_SERVER = $path
        break
    }
    if (Test-Path $path) {
        $LLAMA_SERVER = $path
        break
    }
}

if (-Not $LLAMA_SERVER) {
    Write-Host "错误: 找不到 llama-server" -ForegroundColor Red
    Write-Host ""
    Write-Host "请安装 llama.cpp:" -ForegroundColor Yellow
    Write-Host "  方法1 (推荐): pip install llama-cpp-python[server]" -ForegroundColor Cyan
    Write-Host "  方法2: 从 https://github.com/ggerganov/llama.cpp/releases 下载预编译版本" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "或者使用 Python 启动:" -ForegroundColor Yellow
    Write-Host "  python -m llama_cpp.server --model $MODEL_PATH --host 0.0.0.0 --port $PORT" -ForegroundColor Cyan
    exit 1
}

Write-Host "使用 llama-server: $LLAMA_SERVER" -ForegroundColor Green
Write-Host ""
Write-Host "启动服务中..." -ForegroundColor Yellow
Write-Host "服务地址: http://127.0.0.1:$PORT/v1" -ForegroundColor Green
Write-Host ""

# 启动服务
& $LLAMA_SERVER -m $MODEL_PATH --host 0.0.0.0 --port $PORT
