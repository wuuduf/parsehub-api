# iOS 快捷指令接入

仓库已经提供可直接导入的签名快捷指令：[`../shortcut/ParseHub.shortcut`](../shortcut/ParseHub.shortcut)。它会直接调用 API，分别询问是否复制文案、保存全部图片、保存最高画质视频，不会跳转网页。以下内容保留为手工搭建和二次定制参考。

## 服务准备

1. API 必须通过 HTTPS 暴露，不能在公开网络使用明文 HTTP。
2. 为每位用户生成独立 API Key，写入 `PARSEHUB_API_KEYS=key-a,key-b`。
3. 设置随机 `PARSEHUB_TOKEN_SECRET`，建议至少 32 字节。
4. 不要把生产主 Key 放进公开分享的快捷指令文件。

## 快捷指令动作

新建快捷指令“万能链接解析”，开启“在共享表单中显示”，接受 URL、文本和媒体：

1. `如果 快捷指令输入 没有任何值`，使用“获取剪贴板”。
2. 将输入通过“合并文本”转换成一个字符串，分隔符使用换行。
3. 使用“获取 URL 内容”：
   - URL：`https://你的域名/api/v1/resolve`
   - 方法：`POST`
   - Header：`Authorization` = `Bearer 你的个人APIKey`
   - Header：`Content-Type` = `application/json`
   - 请求正文选择 JSON：
     - `input` = 上一步文本
     - `delivery` = `auto`
     - `include_content` = `true`
4. 读取响应字典中的 `ok`。
5. 若为假，显示 `error.message` 并停止快捷指令。
6. 若为真，读取 `data.media`：
   - 数量为 0：复制 `data.post.content`，并显示通知。
   - 数量为 1：对 `media[0].url` 执行“获取 URL 内容”，再显示共享表单。
   - 数量大于 1：显示菜单“保存全部 / 打包下载 / 复制正文”。

## 打包下载分支

1. `POST /api/v1/jobs`，正文 `{ "input": "原始分享文本" }`。
2. 保存返回的 `data.id`。
3. 每 2 秒调用 `GET /api/v1/jobs/{id}`，最多等待 2 分钟。
4. `status=succeeded` 后调用 `GET /api/v1/jobs/{id}/download`。
5. 将 ZIP 保存到“文件”或打开共享表单。
6. `failed/cancelled/expired` 时显示 `error`。

## 响应示例

```json
{
  "ok": true,
  "request_id": "req_123",
  "data": {
    "platform": {"id": "xhs", "name": "小红书"},
    "post": {"type": "image", "title": "示例", "content": "正文", "canonical_url": "https://..."},
    "media": [
      {
        "id": "m_1",
        "kind": "image",
        "url": "https://api.example.com/api/v1/media/signed-token",
        "expires_at": 1780000000
      }
    ],
    "cache": {"hit": false, "ttl": 300}
  }
}
```

媒体签名有有效期。快捷指令应在解析后立即获取媒体，不要长期保存代理 URL；需要稍后使用时重新调用 `/resolve`。
