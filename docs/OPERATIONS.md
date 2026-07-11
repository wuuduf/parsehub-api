# 部署与运维

## 单机

复制 `.env.example` 为 `.env`，至少修改：

```dotenv
PARSEHUB_API_KEYS=user-a-long-random-key,user-b-long-random-key
PARSEHUB_TOKEN_SECRET=another-independent-long-random-secret
```

执行 `docker compose up -d --build`。Compose 默认启动 Redis，用于共享解析缓存、限流、每日额度和媒体 Token。

## 多副本

- 所有副本必须使用相同 `PARSEHUB_TOKEN_SECRET` 和 Redis。
- `/api/v1/jobs` 的临时 ZIP 当前位于创建任务的 API 节点；多副本部署需使用会话粘滞，或将 Job API 单独部署为一个 worker 实例并挂载持久卷。
- 媒体代理无本地文件状态，使用 Redis Token 后可由任意副本服务。
- 在反向代理上保留 `Range`、`If-Range`、`X-Request-ID`，并关闭响应缓冲。

## 指标

使用 Bearer Key 抓取 `/metrics`。当前指标包括运行时间、按平台和结果分类的解析次数、媒体请求次数。`/health/ready` 同时返回平台数量和熔断状态。

## 凭据与用户

- `PARSEHUB_API_KEYS` 中每个 Key 都是独立用户身份，服务端仅使用 Key 的 SHA-256 摘要关联限流、额度和任务所有权。
- 删除 Key 即可撤销用户访问。
- `PARSEHUB_DAILY_QUOTA` 是每个 Key 的 UTC 日额度。
- 日志和响应不输出 Key、Cookie、代理或媒体原始查询参数。

## 产物存储

默认 Job 产物使用节点临时目录并在 `PARSEHUB_JOB_TTL` 后清理。这种模式适合个人服务和单 worker。设置 `PARSEHUB_S3_BUCKET`、`PARSEHUB_S3_ENDPOINT` 和 `PARSEHUB_S3_REGION` 后，任务完成时会上传到 S3 兼容对象存储，下载接口返回短期预签名 URL，过期清理会删除对象。源码安装时需要 `uv sync --extra api --extra object-storage`；Docker 镜像已包含该扩展。
