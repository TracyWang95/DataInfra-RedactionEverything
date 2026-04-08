# 构建阶段
FROM node:20-alpine as builder

WORKDIR /app

# 复制依赖文件
COPY package*.json ./

# 安装依赖
RUN npm ci

# 复制源代码
COPY . .

# 构建生产版本
RUN npm run build

# 运行阶段 - 使用 nginx 提供静态文件服务
FROM nginx:alpine

# Use auto-detected worker count instead of the default 1
RUN sed -i 's/worker_processes\s*1/worker_processes auto/' /etc/nginx/nginx.conf

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 从构建阶段复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# Create non-root user and fix permissions for nginx runtime dirs
RUN adduser -D -u 1001 appuser && \
    chown -R appuser:appuser /usr/share/nginx/html /var/cache/nginx /var/log/nginx && \
    # nginx needs to write to /var/run/nginx.pid — make it writable for appuser
    touch /var/run/nginx.pid && chown appuser:appuser /var/run/nginx.pid

# 暴露端口 (non-privileged port for non-root)
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget -qO /dev/null http://localhost:8080/ || exit 1

USER appuser

# 启动 nginx
CMD ["nginx", "-g", "daemon off;"]
