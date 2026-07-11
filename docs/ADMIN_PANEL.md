# 管理员面板

## 启用

在 `.env` 中设置三个独立值：

```dotenv
PARSEHUB_ADMIN_TOKEN=管理员登录密钥
PARSEHUB_TOKEN_SECRET=Cookie加密和媒体签名密钥
PARSEHUB_ADMIN_DB_PATH=./data/parsehub-admin.db
```

启动后访问 `https://你的域名/admin`。管理接口使用 `X-Admin-Token`，不要把管理面板暴露在没有 HTTPS 的公网入口。

各平台所需字段和浏览器获取步骤见 [`COOKIE_GUIDE.md`](COOKIE_GUIDE.md)。

## 平台凭据

- 支持为每个平台保存 Cookie 和解析代理。
- Cookie 使用由 `PARSEHUB_TOKEN_SECRET` 派生的 Fernet 密钥加密后存入 SQLite。
- 列表只显示“是否已配置”，不会回显 Cookie 明文。
- Cookie 留空并保存会保留原 Cookie，可单独修改代理；“清除配置”会同时删除 Cookie 和代理。
- 解析请求会在运行时读取对应平台配置，不需要重启 API。
- 更换 `PARSEHUB_TOKEN_SECRET` 后旧 Cookie 无法解密，已生成的动态 API Key 摘要也无法再匹配；应重新录入 Cookie 并重新生成 Key。

## API Key

- 创建时可以设置名称和独立每日额度。
- API Key 明文只在创建响应中返回一次，数据库只保存 HMAC 摘要和前缀。
- 可随时启用、停用或永久删除 Key。
- 列表显示创建时间、最后使用时间和日额度。
- `PARSEHUB_API_KEYS` 中的静态 Key 仍然有效，便于故障恢复，但不会出现在面板列表中。

## 数据持久化

Compose 使用 `admin-data` 卷挂载 `/data`。备份时保存 SQLite 文件和对应的 `PARSEHUB_TOKEN_SECRET`；缺少后者无法恢复 Cookie 明文。
