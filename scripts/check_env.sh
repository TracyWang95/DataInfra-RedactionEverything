#!/bin/bash

# Legal Redaction 环境检查脚本（Linux/macOS）

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

check() {
  if [ $2 -eq 0 ]; then
    echo -e "${GREEN}[OK]${NC}  $1 $3"
  else
    echo -e "${RED}[ERR]${NC} $1 $3"
  fi
}

echo ""
echo -e "${CYAN}========================================"
echo -e "  Legal Redaction 环境检查"
echo -e "========================================${NC}"
echo ""

# ========== 基础命令 ==========
echo -e "${YELLOW}>> 基础环境${NC}"
command -v python3 &> /dev/null
check "python3" $? ""
command -v node &> /dev/null
check "node" $? ""
command -v npm &> /dev/null
check "npm" $? ""
echo ""

# ========== CUDA / NVIDIA ==========
echo -e "${YELLOW}>> GPU 环境${NC}"
if command -v nvidia-smi &> /dev/null; then
  check "nvidia-smi" 0 ""
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | while read line; do
    echo "   GPU: $line"
  done
else
  check "nvidia-smi" 1 "(未找到 NVIDIA 驱动)"
fi
echo ""

# ========== 模型文件 ==========
echo -e "${YELLOW}>> 模型文件（请根据实际路径调整）${NC}"
echo "   请确保以下文件存在："
echo "   - llama-server 可执行文件"
echo "   - GLM-4.6V-Flash-Q4_K_M.gguf"
echo "   - mmproj-F16.gguf"
echo ""

# ========== 端口占用 ==========
echo -e "${YELLOW}>> 服务端口${NC}"

check_port() {
  if ss -tlnp 2>/dev/null | grep -q ":$1 " || netstat -tlnp 2>/dev/null | grep -q ":$1 "; then
    check "$2" 0 "(port $1)"
  else
    check "$2" 1 "(port $1)"
  fi
}

check_port 8081 "GLM Vision 服务"
check_port 8080 "HaS NER 服务"
check_port 8000 "后端 API"
check_port 3000 "前端"

echo ""
echo -e "${CYAN}========================================"
echo -e "  检查完成"
echo -e "========================================${NC}"
echo ""
