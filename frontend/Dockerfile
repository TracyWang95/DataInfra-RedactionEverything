ARG NODE_IMAGE=docker.m.daocloud.io/library/node:24-alpine
ARG NGINX_IMAGE=docker.m.daocloud.io/library/nginx:alpine

FROM ${NODE_IMAGE} AS builder

WORKDIR /app

# 国内 npm 镜像，加速依赖安装
RUN npm config set registry https://registry.npmmirror.com

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM ${NGINX_IMAGE}

# Use auto-detected worker count instead of the default 1.
RUN sed -i 's/worker_processes\s*1/worker_processes auto/' /etc/nginx/nginx.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

# Create a non-root user and fix permissions for nginx runtime directories.
RUN adduser -D -u 1001 appuser && \
    chown -R appuser:appuser /usr/share/nginx/html /var/cache/nginx /var/log/nginx && \
    touch /var/run/nginx.pid && chown appuser:appuser /var/run/nginx.pid

# Non-privileged port for the non-root nginx worker.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget -qO /dev/null http://127.0.0.1:8080/ || exit 1

USER appuser

CMD ["nginx", "-g", "daemon off;"]
