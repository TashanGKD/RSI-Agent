# 小红书图文发布

星语通过 WSL 里一个已登录的 Chrome 发布小红书图文笔记。Chrome 由专用用户 `xhs-browser` 在私有显示 `:93` 上运行，与微信的显示和账号目录分开，只在本机 `127.0.0.1:9333` 开放调试端口。[发布工具](xhs_publish.py)

## 安装与登录

在 WSL 里以 root 运行 [install.sh](deploy/install.sh)。它安装 Chrome、中文字体和 Xvfb，创建 `xhs-browser` 用户，并注册开机自启的 `rsi-xhs-display` 和 `rsi-xhs-browser` 服务。浏览器经本机代理 `127.0.0.1:7890` 访问小红书，WSL 直连会超时。

在 Windows 上运行 [Show-Login.ps1](deploy/Show-Login.ps1)，用小红书 App 扫描打开的二维码页面。页面每 2 秒刷新，过期的二维码会自动重载，登录成功后停止。登录凭据保存在 `/home/xhs-browser/chrome-profile`，重启后保持。Windows 端需要 Python 和 `websocket-client`。

## 发布流程

草稿是一个 JSON 文件，图片路径相对于草稿文件：

```json
{"title": "不超过 20 字", "body": "正文，可以换行", "images": ["1.png", "2.jpg"],
 "topics": ["天文"], "visibility": "仅自己可见"}
```

`visibility` 取 `公开可见`、`仅自己可见` 或 `仅互关好友可见`。`declaration` 可选，省略时不添加内容类型声明。正文里不要写 `#` 和 `@`，话题放进 `topics`。

```powershell
python components/xiaohongshu/xhs_publish.py status
python components/xiaohongshu/xhs_publish.py prepare draft.json
python components/xiaohongshu/xhs_publish.py publish <job> --confirm <确认码>
```

`status` 报告登录状态和账号阻断，例如未绑定手机号时不能发布。`prepare` 在新标签页里上传图片、逐字输入标题和正文、从联想列表点选话题、设置可见范围，再回读表单逐项核对，生成两张预览截图和确认码。看过预览后，用同一个确认码运行 `publish`。它先核对表单没有被改动，再点击发布，页面离开发布表单才记为 `published`。

`save-draft` 点击「暂存离开」，以草稿箱数量增加为准。草稿只保存在这个浏览器本地。`discard` 关闭标签页并放弃任务。

## 稳定与安全

- 同一份内容（标题、正文、话题、设置和图片字节）只能有一个进行中的任务，已发布的内容不能再次准备。
- 一个任务点过发布或暂存后就不会再点第二次。结果不明时记为 `unknown`，先在「笔记管理」或草稿箱核实，再用 `resolve <job> published|draft_saved|not_published --evidence ...` 记录。
- 同一时刻只有一个浏览器操作，靠状态目录里的 `browser.lock` 保证。
- 操作按真人节奏进行：鼠标沿曲线移动，点击落在元素内的随机位置，逐字输入并有长短不一的停顿，步骤之间留出间隔。点击前确认目标没有被遮挡。
- 任务记录、预览和失败截图保存在 `%LOCALAPPDATA%\RSI-Xiaohongshu`，不进 Git。

页面选择器集中在 `SELECTORS`，按 2026-11-26 的创作服务平台记录。页面改版后，`prepare` 会因回读不一致或找不到控件而失败，并留下 `failure.png`。

