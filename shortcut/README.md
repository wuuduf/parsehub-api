# ParseHub 万能解析快捷指令

可直接导入文件：[`ParseHub.shortcut`](ParseHub.shortcut)

## 导入

1. 将 `ParseHub.shortcut` 发送到 iPhone（AirDrop、iCloud Drive 或聊天文件均可）。
2. 在 iPhone 上点击该文件，选择用“快捷指令”打开。
3. 导入过程中填写 ParseHub 解析接口完整地址，例如：

   ```text
   https://parse.example.com/api/v1/shortcut/resolve
   ```

4. 填写管理员面板生成的 API Key，只填写 `ph_` 开头的密钥：

   ```text
   ph_你的APIKey
   ```

## 使用

- 在小红书、抖音、YouTube 等应用中点击“分享” → “ParseHub 万能解析”。
- 复制分享文案后直接运行快捷指令，会自动读取剪贴板。
- 快捷指令直接调用 ParseHub API，不再跳转网页。
- 解析完成后依次询问：
  - 是否复制文案；正文为空时自动使用标题。
  - 是否将全部图片、动图和 Live Photo 封面保存到图库。
  - 是否将所有视频的最高可播放画质保存到图库。
- 多图作品会逐张下载并全部写入系统“最近项目”。
- 视频使用 API 已按分辨率和码率排在首位的最高可播放画质。

## 重新配置服务器

快捷指令会自动生成 `Authorization: Bearer ph_...` 请求头。长按快捷指令 → 编辑，可以修改解析接口和 API Key；也可以删除后重新导入。

## 源码

`ParseHub.cherri` 是可维护源码，使用 [Cherri](https://github.com/electrikmilk/cherri) 编译。仓库中交付的 `.shortcut` 已使用 Apple Shortcut 签名格式签名。
