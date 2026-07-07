#!/bin/bash
# ============================================================
# 离线部署 - 打包脚本
# 在有外网的机器上运行，生成离线部署包
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/offline-bundle"

echo "============================================"
echo "  离线部署包打包工具"
echo "============================================"
echo ""
echo "项目根目录: $PROJECT_ROOT"
echo "输出目录:   $OUTPUT_DIR"
echo ""

# 创建输出目录结构
mkdir -p "$OUTPUT_DIR"/{images,code,models}

# ---- 0. 构建项目镜像（OCR 模型在此步骤预下载并打包进镜像）----
echo "[0/4] 构建项目 Docker 镜像（OCR 模型预下载中，首次较慢）..."

cd "$PROJECT_ROOT"

echo "  构建 backend..."
docker build -t redaction-backend -f backend/Dockerfile backend/

echo "  构建 ocr（含 PaddleOCR 模型预下载，约 2-3GB）..."
docker build -t redaction-ocr -f backend/Dockerfile.ocr backend/

echo "  构建 locateanything..."
docker build -t redaction-locateanything -f backend/Dockerfile.locateanything backend/

echo "  构建 frontend..."
docker build -t redaction-frontend -f frontend/Dockerfile frontend/

echo "  所有镜像构建完成"
echo ""

# ---- 1. 导出 Docker 镜像 ----
echo "[1/4] 导出 Docker 镜像..."

# 基础镜像（项目镜像已包含依赖，只需导出 vllm 基础镜像）
BASE_IMAGES=(
    "vllm/vllm-openai:v0.19.1"
)

PROJECT_IMAGES=(
    "redaction-backend"
    "redaction-ocr"
    "redaction-locateanything"
    "redaction-frontend"
)

for img in "${BASE_IMAGES[@]}"; do
    safe_name=$(echo "$img" | tr '/:' '_-')
    echo "  导出基础镜像: $img -> images/${safe_name}.tar"
    docker save "$img" -o "$OUTPUT_DIR/images/${safe_name}.tar" 2>/dev/null || echo "  [跳过] $img 不存在，请先 docker pull"
done

for img in "${PROJECT_IMAGES[@]}"; do
    echo "  导出项目镜像: $img -> images/${img}.tar"
    docker save "$img" -o "$OUTPUT_DIR/images/${img}.tar"
done

# ---- 2. 拷贝模型文件 ----
echo ""
echo "[2/4] 拷贝模型文件..."

MODEL_SRC="$PROJECT_ROOT/backend/models"
MODEL_DST="$OUTPUT_DIR/models"

if [ -d "$MODEL_SRC" ]; then
    # 使用 rsync 如果可用，否则 cp
    if command -v rsync &>/dev/null; then
        rsync -a --info=progress2 "$MODEL_SRC/" "$MODEL_DST/"
    else
        cp -a "$MODEL_SRC/" "$MODEL_DST/"
    fi
    echo "  模型文件拷贝完成"
    du -sh "$MODEL_DST"
else
    echo "  [错误] 模型目录不存在: $MODEL_SRC"
    exit 1
fi

# ---- 3. 拷贝项目代码 ----
echo ""
echo "[3/4] 拷贝项目代码..."

CODE_DST="$OUTPUT_DIR/code"
# 拷贝必要目录
for dir in backend frontend deploy; do
    if [ -d "$PROJECT_ROOT/$dir" ]; then
        mkdir -p "$CODE_DST/$dir"
        if command -v rsync &>/dev/null; then
            rsync -a --exclude='node_modules' --exclude='.venv' --exclude='__pycache__' \
                  --exclude='dist' --exclude='outputs' --exclude='uploads' \
                  "$PROJECT_ROOT/$dir/" "$CODE_DST/$dir/"
        else
            cp -a "$PROJECT_ROOT/$dir" "$CODE_DST/"
        fi
    fi
done

# 拷贝根目录配置文件
for f in docker-compose.yml .env.example .env.production.example package.json; do
    [ -f "$PROJECT_ROOT/$f" ] && cp "$PROJECT_ROOT/$f" "$CODE_DST/"
done

# ---- 4. 拷贝离线部署配置 ----
echo ""
echo "[4/4] 拷贝离线部署配置..."

cp "$SCRIPT_DIR/docker-compose.model.yml" "$OUTPUT_DIR/"
cp "$SCRIPT_DIR/docker-compose.app.yml" "$OUTPUT_DIR/"
cp "$SCRIPT_DIR/.env.model-server" "$OUTPUT_DIR/"
cp "$SCRIPT_DIR/.env.app-server" "$OUTPUT_DIR/"
cp "$SCRIPT_DIR/nginx-app.conf" "$OUTPUT_DIR/"
cp "$SCRIPT_DIR/load.sh" "$OUTPUT_DIR/"
chmod +x "$OUTPUT_DIR/load.sh"

# ---- 汇总 ----
echo ""
echo "============================================"
echo "  打包完成！"
echo "============================================"
echo ""
echo "离线部署包位置: $OUTPUT_DIR"
echo ""
echo "目录结构:"
echo "  offline-bundle/"
echo "  ├── images/              # Docker 镜像 tar 文件"
echo "  ├── models/              # 模型文件"
echo "  ├── code/                # 项目代码"
echo "  ├── docker-compose.model.yml  # A100 服务器用"
echo "  ├── docker-compose.app.yml    # 前后端服务器用"
echo "  ├── .env.model-server         # A100 环境变量"
echo "  ├── .env.app-server           # 前后端环境变量"
echo "  ├── nginx-app.conf            # 前后端 nginx 配置"
echo "  └── load.sh                   # 一键导入脚本"
echo ""

# 计算总大小
TOTAL_SIZE=$(du -sh "$OUTPUT_DIR" | cut -f1)
echo "总大小: $TOTAL_SIZE"
echo ""
echo "下一步: 将 offline-bundle/ 目录拷贝到 U 盘，"
echo "然后在两台目标服务器上分别运行 load.sh"
