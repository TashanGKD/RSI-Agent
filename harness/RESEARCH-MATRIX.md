# RSI Agent 微信触发与回复调研矩阵

2026-11-10，北京时间。当前主线是小号登录普通微信客户端，Linux 触发器按原生身份和会话接单，本机 Codex 在固定专用会话处理，原 V2 请求负责回传。工程任务由本人原生身份和请求类型决定。普通好友私聊、群聊各用当次会话资料。

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

## 本轮实际采样

群回复器版本 `064ba7f497ee` 启动后的约 32 分钟窗口，核到两条新群聊文字。两条均有原生 ACK、匹配的输入摘要、固定 Codex 会话完成轮次及原回复。V2 均单次点击发送，`nativeStatus=2`，清理完成。

| 样本 | 首次记录到创建 V2（Linux） | V2 创建到终态（Linux） | 首次记录到送达（Linux） | 入队回执到完成（Windows） |
| --- | ---: | ---: | ---: | ---: |
| 群聊文字 A | 70.7 秒 | 7.9 秒 | 78.7 秒 | 59.0 秒 |
| 群聊文字 B | 38.0 秒 | 7.9 秒 | 45.9 秒 | 29.8 秒 |

Linux 起点用源批次首次落盘的时间，Windows 用队列回执文件和原任务完成记录。两机采样时钟相差约 78 秒，各段使用同一主机的差值。样本量为 2，较慢的部分在创建 V2 之前，其中桌面入队后等待完成占了主要时间。下一步区分等待会话与模型执行。这个窗口中的图片样本为 0，仍以新原生图片完成全链路为优先。读取 GitHub 原始源码、项目文档和现网原回执。豆包补充检索未返回结果。用户提供的两份扫描 PDF 使用 OCR 抽查项目名称。
