#!/bin/bash
# ============================================================
# 离线部署包 - 一键构建脚本
#
# 在有外网的构建机上运行，生成完整的离线部署包。
# 新架构: YOLO + GLM (移除 LocateAnything)
# 模型端与前后端分离
#
# 用法:
#   bash build-offline.sh [--skip-images] [--skip-models]
#
# 产物: offline-bundle/ 目录
#   ├── images/          Docker 镜像 tar
#   ├── models/          模型权重文件
#   ├── code/            前后端代码 (由 release.py 生成)
#   ├── docker-compose.model.yml
#   ├── docker-compose.app.yml
#   ├── load.sh
#   ├── nginx-app.conf
#   ├── .env.model-server
#   └── .env.app-server
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUNDLE_DIR="$SCRIPT_DIR/offline-bundle"

SKIP_IMAGES=false
SKIP_MODELS=false
for arg in "$@"; do
    case "$arg" in
        --skip-images) SKIP_IMAGES=true ;;
        --skip-models) SKIP_MODELS=true ;;
    esac
done

echo "============================================"
echo "  离线部署包构建"
echo "  项目根目录: $ROOT_DIR"
echo "  输出目录:   $BUNDLE_DIR"
echo "  跳过镜像:   $SKIP_IMAGES"
echo "  跳过模型:   $SKIP_MODELS"
echo "============================================"
echo ""

# ---- 清理旧的 bundle ----
echo "[1/5] 清理旧 bundle..."
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR/images" "$BUNDLE_DIR/models"

# ---- 构建并导出 Docker 镜像 ----
if [ "$SKIP_IMAGES" = false ]; then
    echo ""
    echo "[2/5] 构建并导出 Docker 镜像..."

    # Backend
    echo "  构建 redaction-backend..."
    docker build -t redaction-backend:latest -f "$ROOT_DIR/backend/Dockerfile" "$ROOT_DIR/backend"
    docker save redaction-backend:latest -o "$BUNDLE_DIR/images/redaction-backend.tar"
    echo "  -> redaction-backend.tar"

    # Frontend
    echo "  构建 redaction-frontend..."
    docker build -t redaction-frontend:latest -f "$ROOT_DIR/frontend/Dockerfile" "$ROOT_DIR/frontend"
    docker save redaction-frontend:latest -o "$BUNDLE_DIR/images/redaction-frontend.tar"
    echo "  -> redaction-frontend.tar"

    # OCR
    echo "  构建 redaction-ocr..."
    docker build -t redaction-ocr:latest -f "$ROOT_DIR/backend/Dockerfile.ocr" "$ROOT_DIR/backend"
    docker save redaction-ocr:latest -o "$BUNDLE_DIR/images/redaction-ocr.tar"
    echo "  -> redaction-ocr.tar"

    # Visual-Features (GLM adapter)
    echo "  构建 redaction-visual-features..."
    docker build -t redaction-visual-features:latest -f "$ROOT_DIR/backend/Dockerfile.glm" "$ROOT_DIR/backend"
    docker save redaction-visual-features:latest -o "$BUNDLE_DIR/images/redaction-visual-features.tar"
    echo "  -> redaction-visual-features.tar"

    # HaS-Image (YOLO)
    echo "  构建 redaction-has-image..."
    docker build -t redaction-has-image:latest -f "$ROOT_DIR/backend/Dockerfile.hasimage" "$ROOT_DIR/backend"
    docker save redaction-has-image:latest -o "$BUNDLE_DIR/images/redaction-has-image.tar"
    echo "  -> redaction-has-image.tar"

    # 注意: vLLM 镜像已移除，需使用外部已部署的 vLLM 服务

    echo "  镜像导出完成"
else
    echo ""
    echo "[2/5] 跳过镜像构建 (--skip-images)"
fi

# ---- 拷贝模型文件 ----
if [ "$SKIP_MODELS" = false ]; then
    echo ""
    echo "[3/5] 拷贝模型文件..."

    # HaS Text NER 模型
    HAS_SRC="$ROOT_DIR/backend/models/has"
    if [ -d "$HAS_SRC" ]; then
        echo "  拷贝 HaS Text NER 模型..."
        mkdir -p "$BUNDLE_DIR/models/has"
        cp -a "$HAS_SRC/." "$BUNDLE_DIR/models/has/"
        echo "  -> models/has/"
    else
        echo "  [警告] HaS Text 模型不存在: $HAS_SRC"
    fi

    # HaS Image YOLO 权重
    YOLO_SRC="$ROOT_DIR/backend/models/has_image"
    if [ -d "$YOLO_SRC" ]; then
        echo "  拷贝 YOLO (HaS-Image) 权重..."
        mkdir -p "$BUNDLE_DIR/models/has_image"
        cp -a "$YOLO_SRC/." "$BUNDLE_DIR/models/has_image/"
        echo "  -> models/has_image/"
    else
        echo "  [警告] YOLO 权重不存在: $YOLO_SRC"
    fi

    # GLM-4.6V-Flash 模型 - 已移除，由外部 vLLM 服务自行加载

    echo "  模型拷贝完成"
else
    echo ""
    echo "[3/5] 跳过模型拷贝 (--skip-models)"
fi

# ---- 生成代码包 (通过 release.py) ----
echo ""
echo "[4/5] 生成代码包..."
CODE_DIR="$BUNDLE_DIR/code"
mkdir -p "$CODE_DIR"

# 直接拷贝必要文件 (不走 release.py 的 tar 流程，保持目录结构)
echo "  拷贝后端代码..."
mkdir -p "$CODE_DIR/backend"
cp -a "$ROOT_DIR/backend/app" "$CODE_DIR/backend/" 2>/dev/null || true
cp -a "$ROOT_DIR/backend/config" "$CODE_DIR/backend/" 2>/dev/null || true
cp -a "$ROOT_DIR/backend/scripts" "$CODE_DIR/backend/" 2>/dev/null || true
cp -a "$ROOT_DIR/backend/requirements.txt" "$CODE_DIR/backend/" 2>/dev/null || true
cp -a "$ROOT_DIR/backend/requirements.lock" "$CODE_DIR/backend/" 2>/dev/null || true
cp -a "$ROOT_DIR/backend/Dockerfile" "$CODE_DIR/backend/" 2>/dev/null || true
cp -a "$ROOT_DIR/backend/Dockerfile.glm" "$CODE_DIR/backend/" 2>/dev/null || true
cp -a "$ROOT_DIR/backend/Dockerfile.hasimage" "$CODE_DIR/backend/" 2>/dev/null || true
cp -a "$ROOT_DIR/backend/Dockerfile.ocr" "$CODE_DIR/backend/" 2>/dev/null || true

echo "  拷贝前端代码..."
if [ -d "$ROOT_DIR/frontend/dist" ]; then
    mkdir -p "$CODE_DIR/frontend"
    cp -a "$ROOT_DIR/frontend/dist" "$CODE_DIR/frontend/"
    cp -a "$ROOT_DIR/frontend/Dockerfile" "$CODE_DIR/frontend/" 2>/dev/null || true
    cp -a "$ROOT_DIR/frontend/nginx.conf" "$CODE_DIR/frontend/" 2>/dev/null || true
else
    echo "  [提示] frontend/dist 不存在，请先运行 npm run build"
fi

# 清理 __pycache__ 和 .pyc
find "$CODE_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$CODE_DIR" -name "*.pyc" -delete 2>/dev/null || true

echo "  代码包生成完成"

# ---- 复制部署配置文件 ----
echo ""
echo "[5/5] 复制部署配置文件..."
cp "$SCRIPT_DIR/docker-compose.model.yml" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/docker-compose.app.yml" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/load.sh" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/nginx-app.conf" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/.env.model-server" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/.env.app-server" "$BUNDLE_DIR/"
echo "  配置文件复制完成"

# ---- 汇总 ----
echo ""
echo "============================================"
echo "  离线部署包构建完成！"
echo "============================================"
echo ""
echo "产物目录: $BUNDLE_DIR"
echo ""
echo "镜像列表:"
ls -lh "$BUNDLE_DIR/images/" 2>/dev/null || echo "  (无)"
echo ""
echo "模型列表:"
ls -d "$BUNDLE_DIR/models"/*/ 2>/dev/null || echo "  (无)"
echo ""
echo "打包为 tar.gz (可选):"
echo "  cd $SCRIPT_DIR && tar czf offline-bundle.tar.gz offline-bundle/"
echo ""
echo "部署方式:"
echo "  模型服务器: bash load.sh model"
echo "  前后端服务器: bash load.sh app"
