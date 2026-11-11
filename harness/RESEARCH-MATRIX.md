# RSI Agent 微信触发与回复调研矩阵

2026-11-10，北京时间。当前主线是小号登录普通微信客户端，Linux 触发器按原生身份和会话接单，本机 Codex 在固定专用会话处理，原 V2 请求负责回传。工程任务由本人原生身份和请求类型决定。普通好友私聊、群聊各用当次会话资料。

## 2026-11-11 反馈复盘

复查两个回复会话及 11 月 10 日 00:00–24:00（北京时间）首次投递的原请求。
78 个桌面请求中 74 个完成、4 个待复核。按原账号、会话和源消息 ID 得到
58 次 V2 匹配；分类与后续处理可能共享原请求。按原 V2 ID 去重后是
45 个发送任务：33 个成功、12 个失败，其中 9 个为 `DRAFT_PROTECTED`。
另外 20 个桌面请求没有对应发送任务，不能统一计为失败或已送达。
此次实时核查中 V2 没有非终态任务，各消费者均无 attention；这不消除历史失败。

| 部分 | 当前证据和缺口 | 下一次的闭环条件 |
| --- | --- | --- |
| 触发：文本、引用和身份 | 原身份、同会话上下文、去重与 ACK 已接入；群内提问有实际回复。仍有历史入队待复核，不能把 CLI 入队当可见接收。 | 新原请求对应实际用户项、执行轮次和原 V2。 |
| 触发：原图、PDF | 这 78 个原请求的附件清单没有成功绑定的图像或 PDF。图片导出修复 #70/#71 已合并但服务还在旧源；本次已补齐固定源码发布和实际服务激活。PDF 仅接已下载且来源可核验的文件。人工恢复案例不代表自动链路稳定。 | 新图/PDF 的来源、字节摘要、实际读取轮次和同会话回传。相册和整段视频仍不在已验收范围。 |
| 触发：链接、语音 | 该集合有 6 个读取结果：2 个 ready、4 个 unavailable。最近群文章已取得正文并成功回传。B 站走现有公开读取器；好友/群普通网页、语音与本人私聊的接入范围不同。 | 按源 URL/消息核实际正文、字幕或转写；不可用时保留原因，不能声称读过。 |
| 发送：草稿、回执和载体 | 历史失败集中在草稿保护。已证实未输入的终态失败可释放后续 intake，原失败仍保留。另有人工恢复后原 V2 成功、桌面仍留首次 not_sent 的案例。表情搜索、收藏和一次原生发送已有独立案例，尚未绑定通用原 V2 表情回复。 | 自动原请求恢复须同时证明原草稿和单次发送；桌面回执与原 V2 不一致须对账。文字、静态图片、原生动画分别验收。 |
| 收发入口 | 群会话的实际 cwd 是旧工作区，实测因接口缺失临时重建查询。新 handoff 绑定配置仓库的绝对协议及 helper；helper 从自己的源码导入，可在旧 cwd 执行。 | 隔离旧工作区核认证、完成和查询；新原入站再核实际采用此入口。 |
| RSI Skills | 代码问题进入定向回归，可复用判断进入现有 learn skill，单次案例进脱敏经验。自动报备、分层经验被后续案例实际复用仍不完备。 | 新案例命中既有 skill，留下实际调用和原结果；回归通过不计为已证明的 RSI 增益。 |

发布保留了 532 条旧原生/消费者记录、配置和客户端/显示进程。结构审计仍报告
既有 Crypto 依赖探测和桌面服务非持久化告警，未把在线轮询等同于跨启动恢复。
当前先验收新原图的自动链路，再处理草稿失败与桌面回执不一致的独立缺口。

## 触发、生成和送达

| 研究对象 | 已核机制 | RSI Agent 的取舍 | 下一项能改变判断的证据 |
| --- | --- | --- | --- |
| AstrBot 的事件和回复阶段 | 事件包含平台、消息类型与会话标识，回复阶段按文本、图片、引用、文件等类型校验组件。 [事件接口](https://github.com/AstrBotDevs/astrbot-sdk/blob/main/docs/plugin-api-v1.md) · [回复阶段源码](https://github.com/AstrBotDevs/AstrBot/blob/6b10af75e118714335aff3aab047bf7689fa1388/astrbot/core/pipeline/respond/stage.py) | 继续使用原生账号、会话、消息 ID 做隔离。桌面标题描述会话类型。普通私聊与工程任务共用专用窗口，各由自己的认证原包决定权限。 | 让两位不同好友和本人分别发送真实消息，核每条原包的会话、标题、回传目标和工程权限。 |
| Hermes Gateway | 接纳回执、模型轮次、最终投递分别记录。异步完成可保留独立送达记录，原会话决定回传位置。 [网关设计](https://github.com/NousResearch/hermes-agent/blob/546f3b3032d6e21e72dc5240091da1275005d847/website/docs/developer-guide/gateway-internals.md) | 沿用 SourceInbox ACK、原包摘要、Codex 队列和完成轮次、V2 结果。PR #49 已让好友私聊在原回执证实未开始发送、导航恢复后继续收新消息。 [PR #49](https://github.com/Yu-Yang-Li/RSI-Agent/pull/49) | 等一次新的预发送失败。核原 ID、回复摘要、草稿和回执，再跟同一会话的下一条实际入站。 |
| 卡兹克的 agent-autoloop | 事件和索引同事务提交，等待状态持久化，恢复时可续接原会话。事件来源、Agent、通知和交付各有接口。来自用户的《个人》PDF 第 3、5、7、9 页及项目原文。 [项目源码和机制](https://github.com/KKKKhazix/agent-autoloop/tree/84e55787bf195dc89d58910ee349b0a021f93459) | 已有原请求与完成接口。优先把接单、排队、完成和微信送达分段计时，用原请求查明停在哪一步。 | 对一个真实慢请求同时核源 ACK、Codex 队列与完成、V2 开始与结束，找到最耗时的那段。 |
| 图片和表情 | AstrBot 将图片与文本作为不同组件。大肥鱼项目提供表情检索与素材。Linux 微信的图片读取以原消息、发送者和可解码字节为证据。 [AstrBot 消息组件](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/message/message_event_result.py) · [表情素材项目](https://github.com/Loping151/dsh-nekowhale-stickers) | PR #50 在真实客户端导出两张源绑定照片并匹配 MD5，两份 JPEG 在隔离接收器通过 SHA-256。已部署；图片完整验收等待一张新原生入站。 [PR #50](https://github.com/Yu-Yang-Li/RSI-Agent/pull/50) | 新普通图片从原生 ID 走到同一 Codex 轮次，凭实际字节理解图片，再核原 V2 回传或同一轮静默。动图发送另验原载体。 |

## 小号接入与部署

| 路线 | 实际支持范围或证据 | 决策 |
| --- | --- | --- |
| 普通 Linux 微信客户端 | 好友关系、本人身份和已加入群由微信原生记录确认。当前群聊文字有真实完整回执，原图和 PDF 各按实际证据单列。 [好友与群接入](https://github.com/Yu-Yang-Li/RSI-Agent/pull/48) · [运行协议](https://github.com/Yu-Yang-Li/RSI-Agent/blob/main/harness/DESKTOP-WECHAT.md) | 好友和普通微信群使用此路线。部署以实际进程版本与请求回执核验。 |
| AstrBot / Hermes 的微信 iLink | AstrBot 的 `weixin_oc` 从 `ilink/bot/getupdates` 收取，入站被映射为 `FRIEND_MESSAGE`，会话键为发送者 ID。Hermes 指出扫码绑定独立机器人身份，普通微信群事件通常无法送达。 [AstrBot 微信适配器](https://github.com/AstrBotDevs/AstrBot/blob/6b10af75e118714335aff3aab047bf7689fa1388/astrbot/core/platform/sources/weixin_oc/weixin_oc_adapter.py) · [Hermes 微信接入](https://github.com/NousResearch/hermes-agent/blob/546f3b3032d6e21e72dc5240091da1275005d847/website/docs/user-guide/messaging/weixin.md) | 独立机器人私聊可作为安装简化的对照。普通小号好友关系、拉入普通群和群内图片回传是切换路线前的实测门槛。 |
| AstrBot + NapCat | 用户的《DSH》PDF 第 21 页可见 AstrBot，历史调研将其与 NapCat 的 QQ 接入组合核对。NapCat 官方仓库定位 NTQQ。 [NapCat 源码](https://github.com/NapNeko/NapCatQQ) | 参考协议适配和消息组件，QQ 的运行证据独立记录。 |
| Windows 11 x64 + WSL 2 + Ubuntu 24.04 | 首版候选，和现网及 CI 同代。Ubuntu Base 加齐图形与读图依赖约 686 MiB，装微信后约 1.41 GiB。Debian 13 实验包已在 Windows 家庭版实测从本地 `.wsl` 导入并启动；同配置少约 8 MiB。客户端由启动命令下载并校验。 [安装实测与启动入口](https://github.com/Yu-Yang-Li/RSI-Agent/pull/47) · [微软分发说明](https://learn.microsoft.com/en-us/windows/wsl/build-custom-distro) | Windows 首版走 Ubuntu 24.04。待用全新 Windows 验收安装、扫码、群文、原图、PDF 和重启后恢复。 |

## 续研：扫码后配对

目标用户在自己的 Windows Codex 中打开仓库，使用普通微信小号扫码。比较时固定三条验收线：原生好友和普通群能否进来，任务是否进入可见的专用 Codex 会话，回复能否按原请求查到发送结果。安装包下载体积、账号权限和恢复成本分别比较。

| 路线 | 核到的机制和适用边界 | 对本项目的价值 |
| --- | --- | --- |
| WSL 2 + Ubuntu Base + 腾讯客户端 | 已发布的安装器可下载并校验固定版本、准备专用发行版和检查登录窗口。Windows 端接收器与 Linux 原生收发已分别运行。扫码后的账号绑定和回环通道仍由 Codex 手工配置。 [安装器](../deploy/wechat-wsl/Install-WeChat.ps1) · [配对指南](../deploy/wechat-wsl/README.md) | 继续作为首版。客户端首次启动下载，图形依赖留在专用发行版。先减少配对中的人工步骤。 |
| Agent WeChat | 上游提供 Windows 安装包及自有客户端，文档支持普通私聊、群聊和媒体。API 支持按事件游标续读、按消费者确认和按幂等键查同一发送。存储源码将重启前已进入提交的发送标为 `needs_review`。上游仍列明无法发送原生表情。RSI 未实测其登录兼容、群媒体或发送。 [发布包](https://github.com/thisnick/agent-wechat/releases/tag/v2.2.1) · [API 契约](https://github.com/thisnick/agent-wechat/blob/08b3bfa2b49ccb51b64b38d37bbb545a26b2e7fa/docs/src/content/docs/use/api.mdx) · [送达存储](https://github.com/thisnick/agent-wechat/blob/08b3bfa2b49ccb51b64b38d37bbb545a26b2e7fa/packages/native-client-rust/crates/wechat-store/src/operations.rs) | 有价值的免 WSL 对照。先借鉴按原 ID 展示进度、断线续读和未知结果待复核的契约。保留现有普通客户端和 V2。 |
| Windows 普通客户端 + UI 自动化 | wxauto 的上游列出两个已测试的 4.1 版本。其说明指出 4.x 界面消息无法取得发送者信息。它能演示普通群发送，RSI 未验证其原生身份、原图来源或单次送达证据。 [项目说明](https://github.com/evanhuang365/wxauto) | 可对照图形发送方式。只有同时证明原生发送者、会话及原请求回执后，才能承接本人任务。 |
| iLink + SteerWX / WeClaw | SteerWX 在 Windows 用 ClawBot QR 绑定，显式 `/codex` 走本机只读 CLI。WeClaw 可用长驻 ACP 或逐轮 CLI。Hermes 文档说明 QR 机器人是独立身份，普通群事件常无法送到。 [SteerWX](https://github.com/samzhou1972/steerwx/blob/dec13a103fb73f7bef85f868d6666f5b0da3527f/README.md) · [WeClaw](https://github.com/fastclaw-ai/weclaw/tree/f9560754a67a7ed5e83be1eb793d972471b06cf7) · [Hermes 的身份限制](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/messaging/weixin.md) | 对照扫码向导和分段诊断。ACP 的进程与会话复用不能当作 Codex 桌面可见用户项的证据。普通小号群聊仍走原生链路。 |
| 容器或微型虚拟机 | Podman Machine 在 Windows 仍需 Linux VM。Firecracker 需要 Linux KVM，官方微信图形会话、权限和回传需要另外接通。WSLg 已提供本项目使用的 X11 应用窗口。 [Podman Machine](https://docs.podman.io/en/latest/markdown/podman-machine-init.1.html) · [Firecracker 前置条件](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md) · [WSLg](https://learn.microsoft.com/windows/wsl/tutorials/gui-apps) | 能改变封装方式。首版维持当前底包，等首装闭环后再用同一收发场景比较磁盘、内存、安装时间和恢复成本。 |

### 回环通道的隔离实测

基线为 `e38444d`。在同一台 Windows 机器上，试验 WSL 2 发行版的 `wslinfo --networking-mode` 返回 `mirrored`。用原 [接收器](../receiver/codex_worker.py) 的 `server()` 和临时 `Jobs` 库监听 Windows `127.0.0.1` 的随机端口。从 WSL 直连该端口，未启动 SSH、微信客户端或 Codex 轮次。

| 跨边界请求 | 实际结果 |
| --- | --- |
| 正确令牌查询 `GET /health` | HTTP 200 |
| 错误令牌查询同一地址 | HTTP 403 |
| 首次提交和重交同一个隔离原包 | 两次 HTTP 202，SQLite 中共 1 条 queued 记录 |
| 原 ID 不变，替换包内原消息 ID | HTTP 409，原记录保留 |

实测支持把直连作为已开启镜像网络、且通过认证探测的本机候选。保留现有 SSH 回环方案供默认 NAT、远程 Linux 或探测失败时使用。现有常驻接收器入口仍会启动 SSH，独立试验只复用了实际 HTTP 和 SQLite 模块。镜像模式不能作为全局安装前提。该试验未测默认 NAT、新机重启或真实微信送达。 [微软 WSL 网络说明](https://learn.microsoft.com/windows/wsl/networking)

### 首个要收束的工程项

下一项是扫码后的可恢复配对。安装器现有的 `desktop_open` 由客户端窗口、进程和资料目录判定，不能单独确认原生账号或决定是否启用发送。先让安装技能和配对入口给出同一份可检查的阶段结果，复用现有模块和状态：

1. 扫码前核发行版、官方客户端版本、独立显示、接收器依赖和 Codex 入队能力。需要账号授权准备时在首次扫码前说明。
2. 扫码后核唯一原生账号、当前运行实例和发送职责。无法证实账号或已有同账号回复器时保持只读。由用户在本机明确授权本人绑定，再固化原生身份及新消息起点。
3. 绑定一个可见的专用 Codex 会话。用已认证的回环探测校验接收器和固定目标。续跑复用当前实例及目标，避免生成第二个回复器或会话。
4. 用用户新发的一条私聊贯通原生入站、可见用户项、同一完成轮次和原 V2 单次发送。再分别记录好友、普通群、图片及 PDF 的新增验收。记录人工步骤数、扫码后耗时及中断续跑结果。扫码完成、HTTP 接纳和实际发送各留一项结果。

现有基线没有通用配对命令。若一台全新 Windows 仍需用户手改私有配置、手输账号 ID 或手工维护 SSH 转发，首版配对尚未达到目标。升级和恢复沿用同一个账号、目标、原队列和回执。相关来源通过内置搜索、豆包发现及上游固定源码核对。`wx-cli` 的 GitHub 原始仓库访问返回 451，本轮不据转载判断其能力。

## 本轮实际采样

群回复器版本 `064ba7f497ee` 启动后的约 32 分钟窗口，核到两条新群聊文字。两条均有原生 ACK、匹配的输入摘要、固定 Codex 会话完成轮次及原回复。V2 均单次点击发送，`nativeStatus=2`，清理完成。

| 样本 | 首次记录到创建 V2（Linux） | V2 创建到终态（Linux） | 首次记录到送达（Linux） | 入队回执到完成（Windows） |
| --- | ---: | ---: | ---: | ---: |
| 群聊文字 A | 70.7 秒 | 7.9 秒 | 78.7 秒 | 59.0 秒 |
| 群聊文字 B | 38.0 秒 | 7.9 秒 | 45.9 秒 | 29.8 秒 |

Linux 起点用源批次首次落盘的时间，Windows 用队列回执文件和原任务完成记录。两机采样时钟相差约 78 秒，各段使用同一主机的差值。这两条用于比较微信端和桌面端耗时。这个窗口中的原图样本为 0，仍以新原生图片完成全链路为优先。读取 GitHub 原始源码、项目文档和现网原回执。豆包补充检索未返回结果。用户提供的两份扫描 PDF 使用 OCR 抽查项目名称。

## 桌面排队和轮次占用

在同一 Windows 主机上对齐队列回执时间、Codex 实际用户项和轮次的开始与结束时间，以及接收器提交原完成结果的时间。使用相同原请求、输入摘要、目标会话和完成轮次关联，共核对 28 个轮次。下表列出前一窗口的两条文字和三个对照。单位为秒。

| 样本 | 入队到完成接口接收 | 排队到轮次开始 | 轮次开始到完成接口接收 | 接收后仍占用会话 |
| --- | ---: | ---: | ---: | ---: |
| 群聊文字 A | 59.0 | 7.4 | 51.6 | 26.1 |
| 群聊文字 B | 29.8 | 0.7 | 29.1 | 26.9 |
| 无明显排队的群聊批次 | 37.3 | 0.1 | 37.1 | 22.5 |
| 前轮占用中的群聊文字 | 155.4 | 128.2 | 27.2 | 21.1 |
| 前轮长时占用中的群聊文字 | 471.3 | 439.6 | 31.7 | 6.2 |

两条长排队样本在前一轮结束时开始。A 和 B 主要耗在轮次开始到完成接口接收，这一段包括推理、原包核验和工具调用，无法单独计量模型生成。时间按各原记录精度分别舍入。完成接口接收后，下一条仍须等整轮结束才可开始。

普通聊天的入队消息要求完成接口确认接收后用一句话结束本轮，微信送达交给原桥接器。新样本沿用上述关联方式，优先比较完成后占用时间；继续分开记录排队和原 V2 送达。共用会话的长任务仍可能占用队列。新原图须按原生入站、实际资产、Codex 看图及原 V2 回执独立验收。
