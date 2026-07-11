#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

case "$(uname -m)" in
  x86_64|amd64) ARCH="linux/amd64" ;;
  aarch64|arm64) ARCH="linux/arm64" ;;
  armv7l) echo "错误：当前发布暂不支持 32 位 ARM；请使用 64 位系统。" >&2; exit 1 ;;
  *) echo "错误：未支持的 CPU 架构 $(uname -m)。" >&2; exit 1 ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  echo "错误：没有找到 Docker。请先按 docs/VPS_DEPLOY.md 安装 Docker Engine。" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "错误：没有找到 docker compose 插件。" >&2
  exit 1
fi

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
  fi
}

if [ ! -f .env ]; then
  cp .env.example .env
  ADMIN_TOKEN="$(random_hex)"
  TOKEN_SECRET="$(random_hex)"
  INITIAL_KEY="ph_$(random_hex)"
  sed -i.bak "s|^PARSEHUB_ADMIN_TOKEN=.*|PARSEHUB_ADMIN_TOKEN=${ADMIN_TOKEN}|" .env
  sed -i.bak "s|^PARSEHUB_TOKEN_SECRET=.*|PARSEHUB_TOKEN_SECRET=${TOKEN_SECRET}|" .env
  sed -i.bak "s|^PARSEHUB_API_KEYS=.*|PARSEHUB_API_KEYS=${INITIAL_KEY}|" .env
  sed -i.bak "s|^PARSEHUB_ADMIN_DB_PATH=.*|PARSEHUB_ADMIN_DB_PATH=/data/parsehub-admin.db|" .env
  rm -f .env.bak
  chmod 600 .env
  echo "已生成 .env。请立即保存以下信息："
  echo "管理员密钥: ${ADMIN_TOKEN}"
  echo "初始 API Key: ${INITIAL_KEY}"
else
  echo "检测到已有 .env，不会覆盖现有密钥。"
fi

echo "CPU 架构: ${ARCH}"
echo "镜像: ${PARSEHUB_IMAGE:-ghcr.io/wuuduf/parsehub-api:latest}"
docker compose -f compose.prod.yaml pull
docker compose -f compose.prod.yaml up -d --remove-orphans
docker compose -f compose.prod.yaml ps

echo "等待健康检查……"
i=0
while [ "$i" -lt 30 ]; do
  if curl -fsS "http://127.0.0.1:${PARSEHUB_PORT:-8000}/health/live" >/dev/null 2>&1; then
    echo "部署成功：本机访问 http://127.0.0.1:${PARSEHUB_PORT:-8000}"
    echo "下一步请配置 Caddy/Nginx HTTPS，详见 docs/VPS_DEPLOY.md。"
    exit 0
  fi
  i=$((i + 1))
  sleep 2
done

echo "服务未在预期时间内健康，请运行：" >&2
echo "docker compose -f compose.prod.yaml logs --tail=200 parsehub-api" >&2
exit 1
