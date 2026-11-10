# Windows WSL 微信安装和配对

适用环境是 Windows 11 x64、WSL 2、WSLg 和已登录的 Windows Codex。安装器准备单独的 Ubuntu 24.04 发行版，首次运行时从 Ubuntu 和腾讯下载经 SHA-256 固定的底包和官方 Linux 微信 4.1.13.26。分开检查扫码、账号绑定、Codex 接收和微信回执。

当前是由 Codex 协助安装和适配的流程。安装器已经覆盖客户端下载及登录检查；扫码后自动生成所有绑定和运行配置尚未实现。后面的配对步骤需要 Codex 按实际机器完成，尤其是本机账号授权、独立显示和 SSH 通道。

新手可将下面这段和[安装技能](../../.agents/skills/rsi-wechat-setup/SKILL.md)链接一起发给自己的 Codex：

> 请按 TashanGKD/RSI-Agent 的 rsi-wechat-setup 技能，从完整仓库为我安装微信小号接入。先检查电脑环境，下载并校验客户端，到扫码时告诉我；建立一个专用 Codex 回复会话，完成本机配对，最后用我发的一条新私聊确认只回一次。遇到尚未适配的步骤请指出具体缺口。

## 从 GitHub 安装

公开下载无需 GitHub 账号。已有工作副本时先核对来源、版本与未提交改动。新安装可用 Git 克隆：

```powershell
git clone https://github.com/TashanGKD/RSI-Agent.git
Set-Location RSI-Agent
```

没有 Git 时，在仓库页面点 **Code → Download ZIP**，完整解压后用 Codex 打开解压目录。按 [Actions](https://github.com/TashanGKD/RSI-Agent/actions) 核对所选提交的 Linux 检查已成功；ZIP 下载可在该固定提交页面进行。以下命令均在包含 `README.md` 和 `deploy/` 的仓库根目录执行：

```powershell
.\deploy\wechat-wsl\Install-WeChat.ps1 -Action Check
.\deploy\wechat-wsl\Install-WeChat.ps1 -Action Install
```

WSL 未启用时，先按用户授权运行 `wsl --install --no-distribution` 并完成 Windows 所需重启。安装后在官方窗口扫码；看到已有头像则点击 **Log In**，然后在手机确认。

```powershell
.\deploy\wechat-wsl\Install-WeChat.ps1 -Action WaitForLogin
```

`login=desktop_open` 才进入配对。若返回 `required`，保留窗口等手机确认。若返回 `window_unrecognized`，检查实际窗口和进程。扫码完成后，下面的账号绑定和回传步骤仍需在本机执行。

## 准备接收器

读[接收器运行说明](../../harness/LOCAL-CODEX.md)和[专用会话协议](../../harness/DESKTOP-WECHAT.md)。在 Codex 桌面为小号新建一个可见的专用回复会话。保存返回的真实会话 ID，在本机私有配置里设为 `desktop_thread_id`，同时设置 `desktop_all_requests: true`。该安装以后复用这个专用会话。目标缺失或入队结果不明时，保留原请求等待核对。

先核对 Windows 的 Python、OpenSSH 和当前 Codex 可执行文件，确认该 Codex 支持 `queue --help`。在仓库外的本用户私有目录创建 UTF-8 JSON 配置，按 [接收器源码](../../receiver/codex_worker.py) 的实际字段填写：

| 字段 | 本实例的值 |
| --- | --- |
| `codex` | 已登录 Codex 的可执行文件绝对路径；须支持 `queue` |
| `token` | 由 Codex 用 Python `secrets.token_hex(32)` 生成的 64 位十六进制令牌，直接写入私有配置，不输出到对话或日志 |
| `state` | 本实例专用的状态目录绝对路径，保留队列、原输入和完成结果 |
| `port` | Windows 上未占用的回环 TCP 端口，JSON 整数 |
| `desktop_thread_id` | 新建专用会话返回的真实 ID |
| `desktop_all_requests` | JSON 布尔值 `true` |
| `ssh` | 下述 WSL SSH 通道对应的本机 SSH 配置别名 |
| `identity_file` | 为本实例生成的 SSH 私钥绝对路径 |
| `remote_port` | WSL 内未占用的回环转发端口，JSON 整数 |

在 Windows 仓库根目录运行 `python -B -m receiver.codex_worker --config <本机私有配置绝对路径>`。把这个绝对路径和 `harness/DESKTOP-WECHAT.md` 交给专用会话，避免会话沙箱改写 `LOCALAPPDATA` 后读到另一目录。新安装不需要维护者的 `var/maintenance/operator.json`。专用会话收到带原请求链接的队列项后，通过本机认证接口核对请求和原始摘要，用当前实际轮次提交回执。回传器再将这份回复送到原微信会话。用新请求分别核对桌面实际收件、固定会话回执和微信原生发信记录。

WSL 默认 NAT 下两侧的 `127.0.0.1` 是不同端点。已经验证的连接方式是用 Windows OpenSSH 的 `ProxyCommand` 调用 `wsl.exe -d <专用发行版> -u wechat-gui -- /usr/bin/nc -N 127.0.0.1 <SSH端口>`，再用 `ssh -R 127.0.0.1:<WSL接收端口>:127.0.0.1:<Windows接收端口>` 转发。WSL sshd 和转发端口都只听回环。为该实例生成新 SSH 身份并固定主机公钥。只允许该回环转发，禁用密码、交互式会话和任意监听。先验收带令牌的 `GET /health`、错令牌拒绝和重复请求去重。[WSL 网络说明](https://learn.microsoft.com/en-us/windows/wsl/networking)

## 绑定微信

1. 根据 [Linux 微信运行说明](../wechat-gui/README.md)补齐触发器和发送器的依赖。在 Ubuntu 上验证 Python 能导入 `Crypto.Cipher.AES`，发行版包的 `Cryptodome` 命名空间不能通过这一关。使用隔离的 Python 依赖目录。
2. 发送器需要单独的 X11 显示及 0600 的 Xauthority。用 `deploy/wechat-gui/prepare_runtime.py prepare` 生成授权，Xephyr 跑在 WSLg 内。试验客户端登录后的主窗口是 880×640，已在同一个进程里调到发送器支持的 905×667。另一个已支持布局是 623×667 会话窗口。每次都要确认窗口、进程归属和实际目标。
3. 只绑定用户本次登录的账号。在启动账号绑定前请用户明确同意用其专用客户端进行本地授权。优先把绑定环境准备在第一次扫码前。用仓库 `components/wechat-linux/capture.py` 的自有子进程方式，不附着现有进程。该脚本的固定路径针对服务端部署，Windows WSL 版必须检查实际安装文件 `/opt/wechat/wechat`，使用与经过校验的版本匹配的程序地址。授权材料只写入 WSL 内账号拥有的私有目录。对联系人库、会话库和消息库做页认证、提交一致性和只读完整性检查。把微信留在正常运行状态并核对 `TracerPid=0`。
4. 开启回传前，先确认同一个微信原生账号是否已有自动回复器。可从已有安装的确认账号和运行状态核对，不以昵称或客户端窗口区分。若另有运行中的回复器，当前实例保持只读。要验收新回传，用独立账号，或在明确的交接范围内把发送职责移到这一实例。
5. 限定一对原生私聊身份和绑定后的新消息。将 Windows 端的测试接收器和 WSL 的触发器绑定，再校验原生会话、已配置的窗口和 V2 预检。只有用户发来一条新私聊后，才观察其原生 ID、Codex 同一请求的完成结果和原 V2 单次发送回执。已有消息、缺失回执和仅 HTTP 入队的请求不能记作成功。

如果签名 APT 索引无法获取，先记录是 WSL DNS、代理还是镜像连接失败，再检查用户网络。Windows 能下载的、通过 Ubuntu 已签名索引校验的包可以离线供给试验实例。不要通过关闭软件源签名或跳过客户端哈希继续安装。

## 后续功能与升级

把功能要求发给同一个安装 Codex，例如“按完整仓库检查图片读取怎样启用，缺什么就定位并实现”。[安装技能的扩展流程](../../.agents/skills/rsi-wechat-setup/SKILL.md#查找或添加功能)会先区分现有配置、所需依赖和缺失实现，再从源码、测试及 PR 找依据。归档中的实验或安装好的插件不能替代实际微信收发验证。

升级时先记录当前源码提交、运行进程、配置位置和原队列状态。保留旧源码和私有配置，在独立工作副本选择 Linux 检查成功的固定提交，按 [接收器运行说明](../../harness/LOCAL-CODEX.md)处理在途请求后再更新对应进程。已接收的桌面任务仍需原完成 API；不要回滚或清空状态数据库。微信客户端、登录状态及用户草稿无需随代码升级重置。最后核对实际运行版本，并用新的授权入站验证受影响路径。
