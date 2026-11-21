# Windows WSL 微信安装和配对

适用环境是 Windows 11 x64、WSL 2、WSLg 和已登录的 Windows Codex。安装器准备单独的 Ubuntu 24.04 发行版，首次运行时从 Ubuntu 和腾讯下载经 SHA-256 固定的底包和官方 Linux 微信 4.1.13.26。分开检查扫码、账号绑定、Codex 接收和微信回执。

当前是由 Codex 协助安装和适配的流程。安装器已经覆盖客户端下载及登录检查；扫码后自动生成所有绑定和运行配置尚未实现。后面的配对步骤需要 Codex 按实际机器完成，尤其是本机账号授权、独立显示和 SSH 通道。

首次安装先使用 `-PrepareOnly`，准备好依赖、私有配置和账号授权脚本后再扫码，避免登录后
才发现缺少授权准备、不得不重新启动客户端。本仓库的 `setup pair` 可以生成相互一致的
接收器/后端配置，`setup prepare-capture` 可以生成经过固定版本校验的自有子进程授权脚本，
`setup check` 可以逐阶段定位缺口；这三个命令不重启微信、不采集授权材料、不发送消息。
实际账号授权、原生身份及界面绑定仍须在本实例完成。

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
.\deploy\wechat-wsl\Install-WeChat.ps1 -Action Install -PrepareOnly
```

WSL 未启用时，先按用户授权运行 `wsl --install --no-distribution` 并完成 Windows 所需重启。
`-PrepareOnly` 安装客户端但不启动窗口。先完成下文依赖、显示和账号授权准备，再在授权的
自有子进程中启动官方客户端扫码；看到已有头像则点击 **Log In**，然后在手机确认。

```powershell
.\deploy\wechat-wsl\Install-WeChat.ps1 -Action WaitForLogin
```

`login=desktop_open` 才进入配对。若返回 `required`，保留窗口等手机确认。若返回 `window_unrecognized`，检查实际窗口和进程。扫码完成后，下面的账号绑定和回传步骤仍需在本机执行。

## 准备接收器

读[接收器运行说明](../../harness/LOCAL-CODEX.md)和[专用会话协议](../../harness/DESKTOP-WECHAT.md)。在 Codex 桌面为小号新建一个可见的专用回复会话。保存返回的真实会话 ID，在本机私有配置里设为 `desktop_thread_id`，同时设置 `desktop_all_requests: true`。该安装以后复用这个专用会话。目标缺失或入队结果不明时，保留原请求等待核对。

先核对 Windows 的 Python、OpenSSH 和当前 Codex 可执行文件，确认该 Codex 支持 `queue --help`。在仓库外的本用户私有目录创建 UTF-8 JSON 配置，按 [接收器源码](../../receiver/codex_worker.py) 的实际字段填写：

新实例可以先生成一套配对文件，减少手写字段和两端令牌不一致。以下命令用 Windows Python
在一个**不存在的新目录**中生成文件，参数均替换为本机已核对的值；`--thread` 使用已经建立的
专用会话真实 UUID，`--ssh` 使用本机已配置的 SSH 别名：

```powershell
python -B -m rsi_agent setup pair --output C:\RSI\private\new-instance `
  --codex C:\RSI\codex.exe --thread ACTUAL-CONVERSATION-UUID `
  --ssh rsi-wechat-tunnel --identity-file C:\RSI\private\tunnel-key `
  --port 8765 --remote-port 8766
```

生成目录就是 Windows 接收器配置的保留位置，`local-codex.json` 中的 state 指向其下
`receiver-state`，不要生成后直接搬动目录。Windows 目录 ACL 限制为当前用户，Linux 文件
部署时使用 0700 目录和 0600 文件；标准输出只有无令牌的计划，不打印配置内容。
已有配置或队列时不要运行 pair 迁移，改用 check 检查原配置；pair 遇到已有目录直接拒绝。

`plan.json` 声明 Linux 部署位置与文件属主：默认将 `linux/codex/` 放到
`/var/lib/rsi-agent/codex/`，由 root 持有，供触发器协调进程使用；将 `linux/installation.json`
和 `linux/receiver-check.json` 放到 `/var/lib/rsi-agent/wechat/`，由 `wechat-gui` 持有。
父目录需要允许该用户遍历，私有子目录不开放列目录权限。根据实际部署方式填写 Xauthority
路径，保留原账号资料的位置；首次生成的账号/profile 为 null，写操作及工程权限关闭。
这些文件没有联系人或 owner 身份，也不启用回复触发器。`paired: false` 表示仍需部署和验证。
已有服务模板中的 installation/model 引用应改为这套文件的实际绝对路径。

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

在首次扫码前，用账号用户准备授权脚本。先建立该用户拥有的 0700 私有 runtime 和 0600
installation 配置；安装器的客户端依赖并不包含全部触发器依赖，需提前核对 Python、GTK3、
PyCryptodome、Pillow、X11、OCR、Xephyr/Openbox 和 SSH 工具。首次授权还需要 GDB，
在取得必要的依赖安装授权后准备；运行期不依赖 GDB。

```sh
runuser -u wechat-gui -- env PYTHONPATH=/opt/rsi-agent/python \
  python3 -B -m rsi_agent --config /var/lib/rsi-agent/wechat/installation.json \
  setup prepare-capture --binary /opt/wechat/wechat
```

此命令复用 `components/wechat-linux/capture.py`，从 `client_release.json` 读取经过审核的
客户端摘要和程序地址，拒绝未知二进制和不匹配的地址。只生成本用户的 `capture-child.gdb`，
不启动 GDB 或客户端；相同准备可以重跑，不覆盖不同脚本或已有授权材料。捕获脚本只启动
自有子进程，第一次取得材料后停止、detach、退出；不附着现有微信进程。
新账号的实际授权启动需沿已审查的自有子进程流程执行；已经登录的客户端需要单独的重启窗口。
随后仍需对联系人、会话和消息库做认证/一致性验证，确认普通进程的 `TracerPid=0`，再绑定原生身份。

### 分阶段检查

Windows 侧先检查接收器配置，加 `--probe` 才会发送带令牌的回环 `GET /health`：

```powershell
python -B -m rsi_agent setup check --receiver-config C:\RSI\private\new-instance\local-codex.json --probe
```

Linux 侧以账号资料用户运行，用私有 `receiver-check.json` 核对固定目标和隧道另一端：

```sh
runuser -u wechat-gui -- env PYTHONPATH=/opt/rsi-agent/python \
  python3 -B -m rsi_agent --config /var/lib/rsi-agent/wechat/installation.json \
  setup check --receiver-config /var/lib/rsi-agent/wechat/receiver-check.json --probe --remote
```

未加 `--probe` 时只做本地文件/依赖检查，不连接接收器。探测禁止代理和重定向，不向输出写入
令牌、账号 ID、会话 ID 或健康接口原始正文。输出分别列出客户端、依赖、runtime 属主、授权准备、
账号配置、显示配置、发送器配置和接收器状态，以及一个下一步；不完整时退出码为 1。
`configured` 只表示配置前置条件，`ready_for_acceptance` 只表示可以开始实机验收；
原生读取、实际登录/布局和微信送达仍须分别核实，`live_delivery` 始终保留 `not_verified`。
接收器在线不会掩盖未授权账号、错误文件属主或尚未绑定的发送器。

如果签名 APT 索引无法获取，先记录是 WSL DNS、代理还是镜像连接失败，再检查用户网络。Windows 能下载的、通过 Ubuntu 已签名索引校验的包可以离线供给试验实例。不要通过关闭软件源签名或跳过客户端哈希继续安装。

## 后续功能与升级

把功能要求发给同一个安装 Codex，例如“按完整仓库检查图片读取怎样启用，缺什么就定位并实现”。[安装技能的扩展流程](../../.agents/skills/rsi-wechat-setup/SKILL.md#查找或添加功能)会先区分现有配置、所需依赖和缺失实现，再从源码、测试及 PR 找依据。归档中的实验或安装好的插件不能替代实际微信收发验证。

升级时先记录当前源码提交、运行进程、配置位置和原队列状态。保留旧源码和私有配置，在独立工作副本选择 Linux 检查成功的固定提交，按 [接收器运行说明](../../harness/LOCAL-CODEX.md)处理在途请求后再更新对应进程。已接收的桌面任务仍需原完成 API；不要回滚或清空状态数据库。微信客户端、登录状态及用户草稿无需随代码升级重置。最后核对实际运行版本，并用新的授权入站验证受影响路径。

## 本地常驻与登录启动

账号资料、令牌和队列已经存储在磁盘上；这里增加的是进程启动和故障恢复。
服务器默认使用 X/VNC/noVNC 服务包，本地 WSL 使用 `--profile wsl`，以 WSLg
为父显示运行 Xephyr，并复用同一个 `wechat-gui-desktop.service` 和官方微信启动脚本。
WSL 包只有 X、桌面和 target 三个定义，不创建网页桌面或公网入口。
首次安装、配对和单条新私聊验收仍按前文执行；这些服务不生成账号授权或触发器绑定。

先生成候选包。以下命令在 Linux 中运行，`REVIEWED_SHA` 对应已经保留的完整 release，
`bundle` 必须是新目录。此步骤不读取账号配置、不安装或启动服务，也不改变登录态。

```sh
python3 -B -m rsi_agent services stage --profile wsl \
  --release /opt/rsi-agent/releases/REVIEWED_SHA \
  --output /var/tmp/rsi-wsl-services-REVIEWED_SHA
SYSTEMD_UNIT_PATH=/var/tmp/rsi-wsl-services-REVIEWED_SHA: \
  systemd-analyze verify --man=no /var/tmp/rsi-wsl-services-REVIEWED_SHA/*.service \
  /var/tmp/rsi-wsl-services-REVIEWED_SHA/*.target
```

`plan.json` 记录 profile、release、各 unit 的摘要及 `activated: false`。
包中的 target 依赖系统 `ssh.service`；sshd 的回环监听、固定身份和转发限制仍按前文配置，
服务包不会替换现有 SSH 策略。反向监听应使用 `PermitListen 127.0.0.1:<WSL接收端口>`
限制；`PermitOpen` 约束的是本地转发目的地，不能用它代替反向监听限制。
纯隧道连接可用 `MaxSessions 0` 禁止 shell、命令和子系统会话，同时保留转发。
Ubuntu 的 `ssh.socket` 可能接管监听；激活前应核对并停用本实例不需要的 socket 激活，
确认实际 `ssh.service` 只监听配置的回环端口，不能只看 `sshd_config` 推断监听范围。

激活安排在另行授权的维护窗口内。先备份原服务定义、启动方式、私有配置与实际队列状态，
确认没有未核对的发送。需要 `systemd`、`systemd-sysv`、`dbus`、`xserver-xephyr`、`openssh-server`、
`xauth`、`x11-utils`、`openbox`、`dbus-x11`、Python 及前文的触发器依赖。
在该发行版 `/etc/wsl.conf` 中保留其他配置，并加入：

```ini
[boot]
systemd=true
```

按微软的 [WSL systemd 说明](https://learn.microsoft.com/windows/wsl/systemd)使配置生效。
可以在维护窗口内用 `wsl --terminate RSI-WeChat` 只停止这个发行版，然后重新启动它；
不要用全局 shutdown 影响其他发行版。重启会中断微信，缓存登录仍可能需要手机确认。

确认 PID 1 是 systemd 后，停止本实例旧的客户端和内层显示，等待其实际退出。
服务初始化发现 `:92` 已有 X socket 时会拒绝覆盖授权；不要删除活动 socket 来强行启动。
配对和主号授权完成后，用 `services stage --profile wsl --owner-config /private/owner/coordinator.json
--python /opt/rsi-agent/venv/bin/python` 连同原来的 `--release`、`--output` 参数生成完整包。
这会加入绑定原配置与 Python 的主号服务，以及 target 对它的依赖；不加入群聊，不读取或更改授权。
审查后将四个定义安装至 `/etc/systemd/system/`，执行 daemon-reload，再 enable/start
`wechat-gui.target`。不带 `--owner-config` 生成的三个定义仍只供桌面准备。
内层显示固定为 `:92`，私有授权位于 `/run/wechat-gui/Xauthority`；安装配置应使用这两个值，
持久的账号资料与 `runtime_root` 仍留在原私有目录，不迁移到 `/run`。
登录后核对窗口布局和原生绑定，再分别验证接收器 `/health` 与：

```sh
python3 -B -m rsi_agent --config /private/installation.json audit --profile wsl
```

该 audit 检查 X 和桌面的持久服务，不要求本地部署运行 noVNC；仍不代替微信送达验收。
触发器只在配对、配置和新消息验收完成后启用。已有 owner/group 模板需替换 `@RELEASE@`；
完整 WSL 包已把已授权的私聊触发器接入启动链。群聊服务应在群准入配置完成后单独加入，不默认打开。

### Windows 接收器登录任务

使用一个保留的 Windows 源码 release、绝对 Python 路径，以及原来的私有接收器配置。
不要为常驻生成新令牌、替换 state 或清空队列。以下 PowerShell 命令中的路径均为本实例值：

```powershell
.\deploy\wechat-wsl\Register-Startup.ps1 -Action Check `
  -Release C:\RSI\releases\REVIEWED_SHA -Config C:\RSI\private\local-codex.json `
  -Python C:\Python\python.exe
.\deploy\wechat-wsl\Register-Startup.ps1 -Action Register `
  -Release C:\RSI\releases\REVIEWED_SHA -Config C:\RSI\private\local-codex.json `
  -Python C:\Python\python.exe
```

`Check` 只检查本地路径和任务注册；不读取令牌、不连接 WSL、不启动接收器。
`Register` 为当前 Windows 用户创建 `RSI-WeChat-Receiver` 登录任务，但不立即运行。
任务使用交互式登录身份和普通权限，不保存 Windows 密码；下次登录执行保留 release 中的
`Start-Local.ps1`，先启动 WSL 桌面 target，再以前台子进程运行原接收器。
接收器退出码交给任务计划程序，最多每分钟重试一次、共三次；已有任务不覆盖，重复实例忽略。
接收器自己维护 SSH 隧道，继续使用原私有请求与完成记录。
Linux 桌面或主号服务启动失败时不会继续拉起接收器，以免把不完整启动报告成成功。

`/health` 的 `ready` 保留接收器就绪语义，并显式标注 `readiness_scope=receiver_only`。
`pipeline_ready` 还要求最近 90 秒内有 Linux 触发器经隧道传来的原生账号、普通官方进程、
支持布局观察，且触发器没有停在 attention。它不代替真实送达验收。
晚于原会话 18 秒等待窗口到达的发送回执会持久化通知原会话；通知只查询原回执，不生成或重发微信。

WSL 桌面模板以 `-s 0` 关闭内层 X 屏保，每次已获桌面锁的操作也先唤醒旧显示的屏保。
这不更改 Windows 电源策略，不能阻止宿主睡眠、合盖或注销。插电熄屏与锁屏仍应分别用新请求验收。

这依赖 Windows 用户登录、电脑唤醒和 Codex 可用。WSL 服务 enable 只负责发行版启动后
拉起服务；Windows 登录任务负责启动发行版与接收器，不能把仅有 enable 当作 Windows 开机验收。
需要手机确认或客户端正常退出时，由用户核对后恢复；不使用无限重启循环绕过登录。

升级先 drain 和核原队列，再停止旧接收器。确认原登录任务已停止后，用相同参数执行
`Register-Startup.ps1 -Action Remove`，随后在新 release 中重新 Check/Register。
Remove 不停止进程、不删除配置或 state，且拒绝移除运行中的任务或其他来源的任务。
回滚保留原配置和队列，恢复上一个 release 的任务注册；Linux 端在维护窗口内恢复原服务
定义和启动方式。任务注册、服务运行、系统重启后恢复及原生微信送达应分别记录实测状态。
