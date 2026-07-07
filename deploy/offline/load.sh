#!/bin/bash
# ============================================================
# 离线部署 - 一键导入脚本
# 在目标服务器（无外网）上运行
#
# 用法:
#   A100 模型服务器:    bash load.sh model
#   前后端服务器:        bash load.sh app
# ============================================================
set -euo pipefail

BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"
ROLE="${1:-}"

if [ -z "$ROLE" ]; then
    echo "用法: bash load.sh [model|app]"
    echo ""
    echo "  model  - A100 模型服务器（导入模型服务镜像 + 模型文件）"
    echo "  app    - 前后端服务器（导入前后端镜像 + 配置）"
    exit 1
fi

echo "============================================"
echo "  离线部署导入 - 角色: $ROLE"
echo "============================================"
echo "部署包目录: $BUNDLE_DIR"
echo ""

# ---- 导入 Docker 镜像 ----
import_images() {
    local images_dir="$BUNDLE_DIR/images"
    if [ ! -d "$images_dir" ]; then
        echo "[错误] 镜像目录不存在: $images_dir"
        exit 1
    fi

    echo "[1/3] 导入 Docker 镜像..."
    for tar_file in "$images_dir"/*.tar; do
        [ -f "$tar_file" ] || continue
        filename=$(basename "$tar_file")
        echo "  导入: $filename"
        docker load -i "$tar_file"
    done
    echo "  镜像导入完成"
}

# ---- 拷贝模型文件（A100 服务器）----
setup_model_server() {
    import_images

    echo ""
    echo "[2/3] 部署模型文件..."

    # 模型文件已在 bundle/models/ 中
    # 创建软链接或拷贝到项目目录
    DEPLOY_DIR="$BUNDLE_DIR/code"
    if [ ! -d "$DEPLOY_DIR" ]; then
        echo "[错误] 代码目录不存在: $DEPLOY_DIR"
        exit 1
    fi

    # 确保模型文件在正确位置
    if [ -d "$BUNDLE_DIR/models" ]; then
        mkdir -p "$DEPLOY_DIR/backend/models"
        if command -v rsync &>/dev/null; then
            rsync -a "$BUNDLE_DIR/models/" "$DEPLOY_DIR/backend/models/"
        else
            cp -a "$BUNDLE_DIR/models/." "$DEPLOY_DIR/backend/models/"
        fi
        echo "  模型文件就位"
    else
        echo "[警告] 模型目录不存在: $BUNDLE_DIR/models"
        echo "  请手动将模型文件放到 $DEPLOY_DIR/backend/models/"
    fi

    echo ""
    echo "[3/3] 配置环境变量..."

    cd "$DEPLOY_DIR"
    cp "$BUNDLE_DIR/.env.model-server" .env
    echo "  .env 已配置"

    echo ""
    echo "============================================"
    echo "  A100 模型服务器部署完成！"
    echo "============================================"
    echo ""
    echo "启动命令:"
    echo "  cd $DEPLOY_DIR"
    echo "  docker compose -f $BUNDLE_DIR/docker-compose.model.yml up -d"
    echo ""
    echo "检查状态:"
    echo "  docker compose -f $BUNDLE_DIR/docker-compose.model.yml ps"
    echo "  curl http://localhost:8082/health   # OCR"
    echo "  curl http://localhost:8080/health   # NER (vLLM)"
    echo "  curl http://localhost:8090/health   # Visual Features"
    echo ""
    echo "★★★ 请记录本机内网 IP，在前后端服务器的 .env 中配置 ★★★"
    echo "  查看 IP: ip addr show"
}

# ---- 配置前后端服务器 ----
setup_app_server() {
    import_images

    echo ""
    echo "[2/3] 配置前后端..."

    DEPLOY_DIR="$BUNDLE_DIR/code"
    if [ ! -d "$DEPLOY_DIR" ]; then
        echo "[错误] 代码目录不存在: $DEPLOY_DIR"
        exit 1
    fi

    cd "$DEPLOY_DIR"

    # 复制环境配置
    cp "$BUNDLE_DIR/.env.app-server" .env

    # 替换 nginx 配置
    cp "$BUNDLE_DIR/nginx-app.conf" frontend/nginx.conf

    echo "  .env 和 nginx.conf 已配置"

    echo ""
    echo "[3/3] 配置模型服务地址..."

    echo ""
    echo "★★★ 请输入 A100 服务器的内网 IP ★★★"
    read -rp "A100 IP [192.168.1.100]: " A100_IP
    A100_IP="${A100_IP:-192.168.1.100}"

    # 替换 .env 中的占位符
    sed -i "s|<A100_IP>|$A100_IP|g" .env
    echo "  模型服务地址已指向 http://$A100_IP"

    echo ""
    echo "============================================"
    echo "  前后端服务器部署完成！"
    echo "============================================"
    echo ""
    echo "启动命令:"
    echo "  cd $DEPLOY_DIR"
    echo "  docker compose -f $BUNDLE_DIR/docker-compose.app.yml up -d"
    echo ""
    echo "检查状态:"
    echo "  docker compose -f $BUNDLE_DIR/docker-compose.app.yml ps"
    echo "  curl http://localhost:8000/health          # Backend"
    echo "  curl http://localhost:3000                  # Frontend"
    echo "  curl http://localhost:8000/health/services  # 模型服务连通性"
    echo ""
    echo "验证模型服务连通性:"
    echo "  curl http://$A100_IP:8082/health   # OCR"
    echo "  curl http://$A100_IP:8080/health   # NER"
    echo "  curl http://$A100_IP:8090/health   # Visual Features"
}

# ---- 执行 ----
case "$ROLE" in
    model)
        setup_model_server
        ;;
    app)
        setup_app_server
        ;;
    *)
        echo "[错误] 未知角色: $ROLE"
        echo "用法: bash load.sh [model|app]"
        exit 1
        ;;
esac
