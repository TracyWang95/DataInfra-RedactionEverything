#!/bin/bash
# ============================================================
# 前后端离线 Docker 包 - 仅构建 Backend + Frontend（国内镜像）
#
# 用法:
#   bash pack.sh
#
# 镜像源:
#   - 基础镜像: docker.m.daocloud.io
#   - pip:      pypi.tuna.tsinghua.edu.cn
#   - apt:      mirrors.tuna.tsinghua.edu.cn
#   - npm:      registry.npmmirror.com
#
# 产物: offline-bundle/
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUNDLE_DIR="$SCRIPT_DIR/offline-bundle"

# 保留已有 .env（含 GPU 6/7 模型地址）
SAVED_ENV=""
if [ -f "$BUNDLE_DIR/.env" ]; then
    SAVED_ENV=$(mktemp)
    cp "$BUNDLE_DIR/.env" "$SAVED_ENV"
    echo "[info] 已备份现有 .env -> $SAVED_ENV"
fi

echo "============================================"
echo "  前后端离线 Docker 包构建（国内镜像）"
echo "  项目根目录: $ROOT_DIR"
echo "  输出目录:   $BUNDLE_DIR"
echo "============================================"
echo ""

rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR/images"

echo "[1/3] 构建 Backend 镜像 (DaoCloud python + 清华 pip/apt)..."
docker build -t redaction-backend:latest -f "$ROOT_DIR/backend/Dockerfile" "$ROOT_DIR/backend"
docker save redaction-backend:latest -o "$BUNDLE_DIR/images/redaction-backend.tar"
echo "  -> images/redaction-backend.tar ($(du -h "$BUNDLE_DIR/images/redaction-backend.tar" | cut -f1))"

echo ""
echo "[2/3] 构建 Frontend 镜像 (DaoCloud node/nginx + npmmirror)..."
docker build -t redaction-frontend:latest -f "$ROOT_DIR/frontend/Dockerfile" "$ROOT_DIR/frontend"
docker save redaction-frontend:latest -o "$BUNDLE_DIR/images/redaction-frontend.tar"
echo "  -> images/redaction-frontend.tar ($(du -h "$BUNDLE_DIR/images/redaction-frontend.tar" | cut -f1))"

echo ""
echo "[3/3] 复制部署配置..."
cp "$SCRIPT_DIR/docker-compose.app.yml" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/nginx-app.conf" "$BUNDLE_DIR/"
cp "$SCRIPT_DIR/.env.app-server" "$BUNDLE_DIR/"

if [ -n "$SAVED_ENV" ] && [ -f "$SAVED_ENV" ]; then
    cp "$SAVED_ENV" "$BUNDLE_DIR/.env"
    rm -f "$SAVED_ENV"
    echo "  已恢复原 .env"
fi

cat > "$BUNDLE_DIR/load-app.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[1/2] 导入 Docker 镜像..."
for tar_file in "$BUNDLE_DIR/images"/*.tar; do
    [ -f "$tar_file" ] || continue
    echo "  导入: $(basename "$tar_file")"
    docker load -i "$tar_file"
done

echo "[2/2] 准备 .env..."
if [ ! -f "$BUNDLE_DIR/.env" ]; then
    cp "$BUNDLE_DIR/.env.app-server" "$BUNDLE_DIR/.env"
    sed -i 's|<MODEL_SERVER_IP>|127.0.0.1|g' "$BUNDLE_DIR/.env"
    if grep -q 'CHANGE_ME' "$BUNDLE_DIR/.env"; then
        SECRET=$(openssl rand -hex 32)
        sed -i "s|CHANGE_ME_GENERATE_WITH_openssl_rand_hex_32|$SECRET|g" "$BUNDLE_DIR/.env"
    fi
fi

echo ""
echo "导入完成。启动:"
echo "  cd $BUNDLE_DIR"
echo "  docker compose -f docker-compose.app.yml --env-file .env up -d"
echo ""
echo "默认端口: Frontend 43000 / Backend 48000"
EOF
chmod +x "$BUNDLE_DIR/load-app.sh"

echo ""
echo "============================================"
echo "  前后端离线包构建完成"
echo "============================================"
echo ""
ls -lh "$BUNDLE_DIR/images/"
echo ""
echo "本机试部署:"
echo "  cd $BUNDLE_DIR && bash load-app.sh"
echo "  cd $BUNDLE_DIR && docker compose -f docker-compose.app.yml --env-file .env up -d --force-recreate"
