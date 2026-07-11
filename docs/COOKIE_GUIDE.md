# 各平台 Cookie 配置详细教程

本文对应当前 ParseHub 代码实现。现阶段真正读取 Cookie 的平台为：Twitter/X、Instagram、YouTube、Bilibili、抖音、TikTok、快手、小红书、知乎。

> Cookie 等同于登录凭证。请使用专门的小号，避免使用主账号；不要发给他人、提交到 Git、写进快捷指令或粘贴到聊天记录。管理台会加密保存 Cookie，但服务端仍应只通过 HTTPS 访问。

## 一、管理台填写方法

1. 登录目标平台网页版，并确认能正常打开准备解析的作品。
2. 打开 ParseHub 管理台：`https://你的域名/admin`。
3. 输入 `PARSEHUB_ADMIN_TOKEN` 登录。
4. 在“平台 Cookie 与代理”找到对应平台，点击“设置”。
5. 将 Cookie Header 粘贴到 Cookie 输入框，例如：

   ```text
   key1=value1; key2=value2; key3=value3
   ```

6. 如该平台需要特定地区出口，再填写代理；代理会同时用于解析请求、媒体中转和打包下载，否则留空。
7. 保存后用一个正常公开链接调用 `/api/v1/resolve` 验证。

支持的 Cookie 输入格式：

```text
# 推荐：浏览器请求头格式
key1=value1; key2=value2

# 也支持 JSON
{"key1":"value1","key2":"value2"}

# 带 Cookie: 前缀也可以
Cookie: key1=value1; key2=value2
```

Cookie 留空并保存会保留原 Cookie，方便只修改代理；点击“清除配置”才会删除 Cookie 和代理。

## 二、从浏览器获取 Cookie

### 方法 A：从 Network 请求复制（最推荐）

适用于 Chrome、Edge、Brave 和其他 Chromium 浏览器：

1. 登录平台网页版。
2. 打开一个作品详情页。
3. 按 `F12`，或右键页面选择“检查”。
4. 切换到 **Network / 网络**。
5. 刷新页面。
6. 在请求列表中点击目标平台域名下的文档或 API 请求。
7. 打开 **Headers / 标头** → **Request Headers / 请求标头**。
8. 找到 `Cookie:`，复制冒号后面的完整内容。

如果看不到 `Cookie`：

- 确认选中的是目标平台自身域名，而不是图片 CDN、统计或广告请求。
- 在 Network 中打开“Preserve log”，刷新后重新选择主文档请求。
- Chrome 有时显示“Provisional headers”；换一个 Fetch/XHR 请求。

### 方法 B：从 Application 存储拼接

1. `F12` → **Application / 应用**。
2. 左侧进入 **Storage → Cookies**。
3. 选择目标平台主域名。
4. 将需要的每行按 `Name=Value` 拼接，用分号和空格隔开。

此方法适合只复制少数必要字段，但容易漏掉跨子域 Cookie。优先使用 Network 中的完整 `Cookie` 请求头。

### Safari（macOS）

1. Safari 设置 → 高级 → 开启“在菜单栏中显示开发菜单”。
2. 登录平台并打开作品页。
3. 开发 → 显示网页检查器 → 网络。
4. 刷新页面，选择目标平台请求。
5. 在请求标头中复制完整 `Cookie`。

Safari 的“存储”标签也可查看 Cookie，但同样需要手工拼接。

### Firefox

1. 按 `F12` → 网络。
2. 刷新作品页。
3. 选择目标平台请求 → 请求标头。
4. 复制完整的 `Cookie` 值。

## 三、各平台配置

## 1. Twitter / X

访问域名：`https://x.com`

当前代码明确要求以下两个字段才能启用登录态：

| 字段 | 必需 | 作用 |
|---|---|---|
| `auth_token` | 是 | 登录会话 |
| `ct0` | 是 | CSRF Token，同时写入 `x-csrf-token` 请求头 |

推荐直接复制 x.com 请求中的完整 Cookie。最小示例：

```text
auth_token=你的值; ct0=你的值
```

获取步骤：

1. 登录 x.com。
2. 打开任意推文详情。
3. Network 搜索 `TweetResultByRestId`；找不到时选择任意 `graphql` 请求。
4. 复制 Request Headers 中完整 Cookie。

验证：解析一个普通公开推文，再解析一个有年龄/可见性限制、但当前账号可查看的推文。缺少任一必需字段时，代码会放弃 Cookie 并按匿名用户请求。

常见问题：

- `error -2`：匿名态无法查看；检查 `auth_token` 和 `ct0`。
- 配置后仍失败：账号可能要求二次验证或已触发风控，重新在网页完成验证再复制。

## 2. Instagram

访问域名：`https://www.instagram.com`

推荐字段：

| 字段 | 建议级别 | 作用 |
|---|---|---|
| `sessionid` | 登录内容必需 | 登录会话 |
| `csrftoken` | 强烈建议 | GraphQL POST 的 CSRF Token |
| `ds_user_id` | 建议 | 当前账号标识 |
| `mid`、`ig_did` | 建议保留 | 设备和访客标识 |

示例：

```text
sessionid=...; csrftoken=...; ds_user_id=...; mid=...; ig_did=...
```

获取步骤：

1. 登录 Instagram 网页。
2. 打开一个帖子或 Reel。
3. Network 筛选 `graphql`，选择发送到 `www.instagram.com/graphql/query` 的 POST。
4. 复制完整 Cookie。

说明：解析器在没有配置 Cookie 时会尝试匿名获取 `csrftoken`；私人内容、年龄受限内容或匿名接口失败时才回退到已配置 Cookie。私人账号内容仍要求当前账号本身拥有查看权限。

## 3. YouTube

访问域名：`https://www.youtube.com`

YouTube 通过 `yt-dlp` 使用 Cookie。项目会把管理台里的键值对转换为 Netscape Cookie 文件，因此建议复制完整 Cookie，而不是只取一个字段。

常见重要字段包括：

```text
SAPISID; __Secure-1PAPISID; __Secure-3PAPISID; SID; HSID; SSID;
LOGIN_INFO; PREF; YSC; VISITOR_INFO1_LIVE; __Secure-3PSID
```

获取步骤：

1. 登录 YouTube，确保浏览器中能播放目标视频。
2. 打开目标视频页面。
3. Network 选择主文档 `watch?...` 或 `youtubei/v1/player`。
4. 复制完整 Cookie。

适用场景：年龄限制、登录确认、会员可见内容以及 YouTube 要求“确认不是机器人”的情况。Cookie 不能突破账号自身权限。

注意：YouTube Cookie 风控较敏感。服务端出口地区与浏览器登录地区差异过大时更容易失效，建议配合稳定的同地区代理，并使用独立账号。

## 4. Bilibili

访问域名：`https://www.bilibili.com`

推荐字段：

| 字段 | 建议级别 | 作用 |
|---|---|---|
| `SESSDATA` | 强烈建议 | 登录会话 |
| `bili_jct` | 强烈建议 | CSRF Token |
| `DedeUserID`、`DedeUserID__ckMd5` | 建议 | 用户标识 |
| `buvid3`、`buvid4` | 建议 | 设备标识 |
| `b_nut`、`CURRENT_FNVAL` | 可保留 | Web 播放环境 |

示例：

```text
SESSDATA=...; bili_jct=...; DedeUserID=...; buvid3=...; buvid4=...
```

获取步骤：

1. 登录 Bilibili。
2. 打开视频或动态详情。
3. Network 选择 `api.bilibili.com` 下的 `view/detail` 或动态 `polymer` 请求。
4. 复制 Cookie。

当前实现中 Cookie 对动态解析和 `yt-dlp` 回退更有价值；普通公开视频主接口可能不使用登录 Cookie。遇到 `-352`、`412` 等通常是风控，不一定是字段缺失，可以更换稳定出口或重新获取 Cookie。

## 5. 抖音

访问域名：`https://www.douyin.com`

抖音 Web 解析器没有硬编码单一必需字段，而是把完整 Cookie 交给作品详情接口。推荐完整复制，常见字段包括：

```text
sessionid; sessionid_ss; sid_guard; uid_tt; uid_tt_ss;
passport_csrf_token; passport_csrf_token_default; ttwid; msToken;
odin_tt; s_v_web_id
```

获取步骤：

1. 登录 douyin.com。
2. 打开作品详情，确保网页能正常播放。
3. Network 搜索 `aweme/v1/web/aweme/detail` 或选择 douyin.com 的 Fetch/XHR 请求。
4. 复制完整 Cookie。

解析顺序：配置 Cookie 后先尝试 Web 接口；失败时再尝试移动端设备接口。因此公开内容可能在 Cookie 失效时仍能解析，不能据此判断 Cookie 一定有效。

“日常/Story”还可能依赖服务端环境变量 `PARSEHUB_DOUYIN_DEVICE_ID` 和 `PARSEHUB_DOUYIN_IID`，这不是 Cookie，需在 `.env` 单独配置。

## 6. TikTok

访问域名：`https://www.tiktok.com`

推荐复制完整 Cookie。常见有用字段：

```text
sessionid; sessionid_ss; sid_guard; uid_tt; uid_tt_ss;
tt_chain_token; tt_csrf_token; msToken; odin_tt; passport_csrf_token
```

获取步骤：

1. 登录 TikTok 网页，并确保所用网络地区能够访问目标作品。
2. 打开视频或图文作品。
3. Network 选择 `www.tiktok.com` 的主文档、`api` 或 `feed` 请求。
4. 复制完整 Cookie。

TikTok 对地区、出口 IP 和作品区域限制非常敏感。出现 `notfound` 或网页回退也失败时，先确认同一代理出口下的浏览器是否能访问，而不是反复更换 Cookie。

## 7. 快手

访问域名：`https://www.kuaishou.com`

当前 GraphQL 解析最常见的关键字段是：

| 字段 | 建议级别 | 作用 |
|---|---|---|
| `did` | 关键 | Web 设备标识；缺失时接口常报“did 未填” |
| `didv` | 建议 | 设备版本标识 |
| `kpf`、`kpn` | 建议保留 | Web 客户端环境 |
| `userId`、`kuaishou.server.web_st` | 登录内容建议 | 登录会话 |
| `kuaishou.server.web_ph` | 建议 | Web 会话辅助字段 |

获取步骤：

1. 登录快手网页版。
2. 打开视频详情。
3. Network 搜索 `graphql`，选择发送到 `www.kuaishou.com/graphql` 的 POST。
4. 复制完整 Cookie。

常见错误：

- `did 未填`：Cookie 中缺少 `did`。
- `Need captcha`、`400002`：账号或出口触发验证；先在网页完成验证，再重新复制。

## 8. 小红书

访问域名：`https://www.xiaohongshu.com`

推荐字段：

```text
a1; web_session; webId; gid; xsecappid; webBuild; acw_tc
```

其中 `web_session` 表示登录会话，`a1` 常用于 Web 身份/签名环境。当前实现读取作品页面中的 `window.__INITIAL_STATE__`，所以完整浏览器 Cookie 比单独复制一个字段更可靠。

获取步骤：

1. 登录小红书网页版。
2. 从分享链接打开目标笔记，确认网页可见。
3. Network 选择笔记详情主文档，而不是图片 CDN 请求。
4. 复制完整 Cookie。

特别注意：分享链接中的 `xsec_token` 是 URL 查询参数，不是 Cookie。解析器会在解析前保留它，完成后才清理；不要手工删除分享链接上的 `xsec_token`。

出现“该帖子需要登录后查看”时，优先检查 `web_session` 是否存在、网页账号是否确实能看到该笔记，以及分享链接是否保留 `xsec_token`。

## 9. 知乎

访问域名：`https://www.zhihu.com`，专栏还会访问 `https://zhuanlan.zhihu.com`

当前代码硬性要求：

| 字段 | 必需 | 作用 |
|---|---|---|
| `d_c0` | 是 | 生成知乎 `x-zse-96` 签名 |
| `z_c0` | 强烈建议 | 登录会话 |

推荐同时保留：`_zap`、`q_c1`、`tst` 等浏览器已有字段。

示例：

```text
d_c0="你的值"; z_c0=你的值; _zap=...
```

不要删除 Cookie 值中原有的引号。`d_c0` 缺失时解析器会直接报 `d_c0 is not found in cookie`。

获取步骤：

1. 登录知乎。
2. 打开问题回答、专栏或圈子内容。
3. Network 选择 `www.zhihu.com/api` 或 `zhuanlan.zhihu.com` 请求。
4. 复制完整 Cookie，并确认其中能搜索到 `d_c0=`。

## 四、当前不读取 Cookie 的平台

以下平台虽然会显示在管理台的平台列表中，但当前对应解析器不会使用管理台 Cookie：

- Facebook
- Snapchat
- Threads
- 贴吧
- 微博
- 微信公众号
- 酷安
- 皮皮虾
- 最右
- 小黑盒

为它们填写 Cookie 不会改变当前解析结果。Facebook 和 Snapchat 虽然使用 `yt-dlp`，但现有基类没有向它们传递 Cookie；若将来增加平台专用实现，管理台无需改版即可继续存储配置。

## 五、验证 Cookie 是否生效

推荐用管理台保存后，通过 API 测试：

```bash
curl 'https://你的域名/api/v1/resolve' \
  -H 'Authorization: Bearer 你的APIKey' \
  -H 'Content-Type: application/json' \
  --data '{"input":"目标作品分享链接","delivery":"auto"}'
```

验证顺序：

1. 先测试一个无需登录的公开作品，确认平台解析器和网络正常。
2. 再测试当前账号能查看、匿名窗口不能查看的作品。
3. 保存新 Cookie 后使用不同作品链接，或等待旧缓存过期；当前服务也会根据 Cookie 指纹自动区分缓存。
4. 查看返回错误码：`UPSTREAM_PARSE_FAILED` 通常是 Cookie、风控或上游接口变化；`UPSTREAM_TIMEOUT` 更偏向网络/代理问题。

## 六、更新和失效排查

出现以下情况应重新复制 Cookie：

- 网页账号被退出登录。
- 修改密码、主动退出所有设备或完成安全验证。
- 服务端持续出现 401/403、账号风控或“需要登录”。
- 平台刷新了 `sessionid`、`auth_token`、`SESSDATA`、`web_session` 等核心字段。

排查清单：

1. 用同一账号在浏览器打开目标作品，确认确实有权限。
2. 确认 Cookie 来自正确域名和已登录请求。
3. 确认复制的是 `Cookie` 请求头值，不是响应里的 `Set-Cookie` 单行。
4. 检查是否漏掉必需字段：X 的 `auth_token/ct0`、快手的 `did`、知乎的 `d_c0`。
5. 检查服务端代理地区是否匹配平台和账号常用地区。
6. 删除旧配置、重新保存完整 Cookie，再用新链接测试。
7. 如果多个平台同时超时，优先检查服务端 DNS、代理和出口网络，而不是逐个平台换 Cookie。

## 七、备份与轮换

- SQLite 数据库默认位于 `PARSEHUB_ADMIN_DB_PATH`。
- Cookie 密文只有配合原 `PARSEHUB_TOKEN_SECRET` 才能解密。
- 备份数据库时同时安全备份该 Secret，但不要放在同一公开位置。
- 更换 `PARSEHUB_TOKEN_SECRET` 后需要重新录入所有 Cookie，并重新生成动态 API Key。
- 建议每个平台使用独立小号，定期轮换 Cookie；发现异常登录立即在平台侧撤销会话。
