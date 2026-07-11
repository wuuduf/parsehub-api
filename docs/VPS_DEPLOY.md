# VPS 使用 Docker 部署：从零到 HTTPS

本文适用于 Ubuntu 22.04/24.04、Debian 12，以及常见的 `x86_64/amd64`、`aarch64/arm64` VPS。

发布镜像：

```text
ghcr.io/wuuduf/parsehub-api:latest
```

同一个标签包含 `linux/amd64` 和 `linux/arm64`。Docker 会根据 VPS 的 CPU 自动拉取正确架构，不需要修改 Compose 或镜像名。

## 0. 准备

需要：

- 一台至少 2 核、2 GB 内存、20 GB 磁盘的 64 位 Linux VPS；建议 4 GB 内存。
- 一个域名，例如 `parse.example.com`。
- DNS 中创建一条 A 记录指向 VPS IPv4；有 IPv6 时再创建 AAAA 记录。
- 开放安全组/防火墙端口：`22`、`80`、`443`。

检查架构：

```bash
uname -m
```

输出 `x86_64` 会使用 `linux/amd64`，输出 `aarch64` 会使用 `linux/arm64`。32 位 `armv7l` 暂不支持。

## 1. 登录 VPS

在本机执行：

```bash
ssh root@你的VPS_IP
```

建议创建普通用户；以下示例用 Ubuntu：

```bash
adduser deploy
usermod -aG sudo deploy
su - deploy
```

## 2. 安装 Docker Engine

不要使用发行版中很旧的 `docker.io`。Ubuntu/Debian 可执行 Docker 官方安装脚本：

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker "$USER"
rm get-docker.sh
```

退出 SSH 再重新登录，让 docker 用户组生效：

```bash
exit
ssh deploy@你的VPS_IP
```

确认：

```bash
docker version
docker compose version
```

两条命令都应正常输出，且 `docker compose` 中间没有连字符。

## 3. 下载项目

```bash
sudo mkdir -p /opt/parsehub-api
sudo chown "$USER":"$USER" /opt/parsehub-api
git clone https://github.com/wuuduf/parsehub-api.git /opt/parsehub-api
cd /opt/parsehub-api
```

如果系统没有 Git：

```bash
sudo apt update
sudo apt install -y git curl openssl
```

## 4. 一键初始化

```bash
cd /opt/parsehub-api
chmod +x scripts/bootstrap-vps.sh scripts/update-vps.sh
./scripts/bootstrap-vps.sh
```

脚本会：

1. 检测 `amd64` 或 `arm64`。
2. 检查 Docker Compose。
3. 首次运行时生成 `.env`。
4. 自动生成管理员密钥、媒体签名密钥和初始 API Key。
5. 拉取当前架构对应的 GHCR 镜像。
6. 启动 API 与 Redis。
7. 等待健康检查通过。

首次输出类似：

```text
管理员密钥: 8f...
初始 API Key: ph_4a...
```

立即保存这两个值。`.env` 权限会被设置为 `600`。

查看容器：

```bash
docker compose -f compose.prod.yaml ps
```

本机测试：

```bash
curl http://127.0.0.1:8000/health/live
```

应返回：

```json
{"ok":true,"data":{"status":"ok"}}
```

生产 Compose 只监听 `127.0.0.1:8000`，不会把未加密 API 直接暴露到公网。

## 5. 配置 HTTPS（推荐 Caddy）

Caddy 会自动申请和续期 Let's Encrypt 证书。

安装：

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

编辑配置：

```bash
sudo nano /etc/caddy/Caddyfile
```

写入，并把域名换成自己的：

```caddy
parse.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        Referrer-Policy same-origin
    }
}
```

格式化、检查和重载：

```bash
sudo caddy fmt --overwrite /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
```

访问：

- 用户解析页：`https://parse.example.com/`
- 管理后台：`https://parse.example.com/admin`
- OpenAPI：`https://parse.example.com/docs`

若证书申请失败，检查 DNS 是否已生效，以及云厂商安全组是否开放 80/443。

## 6. 登录管理后台

查看管理员密钥：

```bash
grep '^PARSEHUB_ADMIN_TOKEN=' /opt/parsehub-api/.env
```

打开：

```text
https://你的域名/admin
```

输入管理员密钥，然后：

1. 为需要登录态的平台设置 Cookie。
2. 为 iPhone、家人或不同设备分别生成 API Key。
3. 为每个 Key 设置独立日额度。
4. 不再使用的 Key 可立即停用或删除。

## 7. 用户解析页

访问：

```text
https://你的域名/
```

输入管理员生成的用户 API Key，即可粘贴链接、预览媒体、切换视频清晰度和下载。

## 8. 防火墙

使用 UFW：

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

不要开放：

- `8000`：仅供本机 Caddy 反代。
- `6379`：Redis 只在 Docker 内部网络使用。

## 9. 更新

```bash
cd /opt/parsehub-api
git pull --ff-only
./scripts/update-vps.sh
```

脚本会拉取当前 CPU 架构的新镜像、滚动重建容器并清理旧镜像。

指定版本，避免始终跟随 `latest`：

```bash
echo 'PARSEHUB_IMAGE=ghcr.io/wuuduf/parsehub-api:v1.0.0' >> .env
./scripts/update-vps.sh
```

回滚：

```bash
sed -i 's|^PARSEHUB_IMAGE=.*|PARSEHUB_IMAGE=ghcr.io/wuuduf/parsehub-api:v0.9.0|' .env
./scripts/update-vps.sh
```

## 10. 备份和恢复

管理数据位于 Docker 卷 `admin-data`。备份 SQLite：

```bash
cd /opt/parsehub-api
mkdir -p backups
docker compose -f compose.prod.yaml exec -T parsehub-api \
  sh -c 'cat /data/parsehub-admin.db' > "backups/parsehub-admin-$(date +%F-%H%M).db"
cp .env "backups/env-$(date +%F-%H%M)"
chmod 600 backups/*
```

必须同时安全备份 `.env` 中的 `PARSEHUB_TOKEN_SECRET`。没有原 Secret，就无法解密 Cookie，也无法继续校验已有动态 API Key。

恢复前停止服务：

```bash
docker compose -f compose.prod.yaml stop parsehub-api
docker compose -f compose.prod.yaml run --rm -T parsehub-api \
  sh -c 'cat > /data/parsehub-admin.db' < backups/你的数据库.db
docker compose -f compose.prod.yaml up -d
```

## 11. 常用运维命令

查看日志：

```bash
docker compose -f compose.prod.yaml logs -f --tail=200 parsehub-api
```

重启：

```bash
docker compose -f compose.prod.yaml restart parsehub-api
```

查看健康状态：

```bash
curl -fsS http://127.0.0.1:8000/health/ready
```

查看实际镜像架构：

```bash
docker image inspect ghcr.io/wuuduf/parsehub-api:latest \
  --format '{{.Os}}/{{.Architecture}}'
```

查看多架构清单：

```bash
docker buildx imagetools inspect ghcr.io/wuuduf/parsehub-api:latest
```

查看资源：

```bash
docker stats
df -h
docker system df
```

## 12. 常见错误

### `manifest unknown`

GitHub Action 还没有成功发布 `latest`，到仓库 Actions 页面查看 “Build and publish multi-arch image”。首次推送后需要等待构建完成。

### `exec format error`

通常是拉到了错误架构的单架构镜像。当前官方 GHCR 标签应同时包含 amd64/arm64：

```bash
docker buildx imagetools inspect ghcr.io/wuuduf/parsehub-api:latest
docker compose -f compose.prod.yaml pull --policy always
```

### 容器一直 `unhealthy`

```bash
docker compose -f compose.prod.yaml logs --tail=300 parsehub-api
docker inspect --format '{{json .State.Health}}' "$(docker compose -f compose.prod.yaml ps -q parsehub-api)"
```

重点检查 `.env`、Redis 是否健康、SQLite 卷权限及内存是否不足。

### 页面能打开但解析超时

检查 VPS 出口、DNS、平台 Cookie 和平台所在地区。部分国际平台需要配置平台代理。不要把 8000 暴露公网来“解决”超时。

### GHCR 私有包拉取失败

公开仓库通常会生成公开包。如果包仍为私有，在 VPS 登录：

```bash
echo '你的GitHub PAT' | docker login ghcr.io -u wuuduf --password-stdin
```

PAT 只需要 `read:packages` 权限。

## 13. GitHub Actions 发布规则

- 推送到默认分支：发布 `latest`、分支名和 `sha-xxxxxxx`。
- 推送 `v1.2.3` 标签：发布 `v1.2.3`、`1.2.3`、`1.2`。
- 手动运行：GitHub → Actions → “Build and publish multi-arch image” → Run workflow。
- 架构：`linux/amd64`、`linux/arm64`。
- GHCR 登录使用仓库自带的 `GITHUB_TOKEN`，不需要额外保存 Docker 密码。
