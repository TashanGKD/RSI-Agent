# RSI Agent

RSI Agent 把微信消息交给本机 Codex 处理，再由原微信发送队列回传结果。[触发器](trigger/)核对并接入微信原消息，[发送器](components/wechat-linux/operations/sending.py)核对收件人并记录原生回执。[本机接收器](receiver/)把这两端接到一个专用 Codex 会话。

```text
微信消息 → Linux 触发器 → SSH 回环通道 → 本机接收器 → 专用 Codex 会话
微信回执 ← 原 V2 发送队列 ← Linux 触发器 ← 本机接收器保存的完成结果
```

本人私聊、已确认好友私聊和已核实加入的群聊走同一个专用 Codex 会话，普通文字无需加前缀。好友私聊各用自己的上下文，工程任务必须经本人原生身份和消息类型检查。独立的 DeepSeek 群聊筛选已在当前部署关闭。

## Windows 小号接入

把[安装技能](.agents/skills/rsi-wechat-setup/SKILL.md)或本仓库链接交给你电脑上的 Codex，按 [WSL 安装和配对](deploy/wechat-wsl/README.md)操作。安装器在首次运行时下载并校验 Ubuntu Base 和官方 Linux 微信。扫码后为小号建立一个可见的专用回复会话，再验证触发器接入和发送器回执。

仓库公开下载无需 GitHub 账号。当前安装器完成客户端下载及登录检查，扫码后的账号授权、通道和接收器绑定仍由 Codex 按本机环境适配。安装指南列出了实际配置字段、验证步骤和升级方式；后续功能也按安装技能从完整仓库定位。

## 触发器

触发器运行在微信客户端所在的 Linux 主机。它核对账号、会话、发送者和授权范围，把原生消息持久化后再 ACK。图片和链接按原生来源核验。原请求 ID、正文和附件绑定后，通过经过认证的 SSH 回环通道交给本机接收器。

| 想找什么 | 入口 |
| --- | --- |
| 本人私聊接入与回传 | [owner_reply.py](trigger/owner_reply.py)、[reply_io.py](trigger/reply_io.py) |
| 群聊接入与回传 | [group_reply.py](trigger/group_reply.py)、[group_io.py](trigger/group_io.py)、[群聊准入](harness/GROUP-ADMISSION.md) |
| 固定原始请求并投递 | [codex_backend.py](trigger/codex_backend.py) |
| 图片与 PDF 原件校验 | [media_io.py](trigger/media_io.py)、[微信图像适配](components/wechat-linux/operations/images.py) |

用已配置的私有文件检查触发器。两个 `check` 都不发送微信消息。

```sh
python -B -m rsi_agent --config /private/owner-replies/config.json replies check
python -B -m rsi_agent --config /private/invited-groups/config.json groups check
```

已安装的常驻服务通过相同入口的 `run` 模式工作。服务模板见 [私聊](deploy/owner-replies/rsi-owner-replies.service)和[群聊](deploy/group-replies/rsi-group-replies.service)。

## 接收器

[本机接收器](receiver/codex_worker.py)在已登录 Codex 的电脑上运行。它认证请求，按原 ID 和输入摘要持久化去重，然后通过 `codex queue` 把请求交给配置中固定的专用会话。该会话核对原始请求，读取已校验的附件，再把完成结果交回接收器。接收器保存结果，触发器据此交给原 V2 发送队列核对收件人并投递。

```sh
python -B -m receiver.codex_worker --config /private/local-codex.json
```

原有的 `python -m rsi_agent.codex_worker` 仍可启动同一个接收器。运行中的实例可通过认证的 `GET /health` 核对就绪状态和会话路由。配置、启动和恢复见[接收器运行说明](harness/LOCAL-CODEX.md)，会话如何读取原始请求和提交结果见[微信专用会话协议](harness/DESKTOP-WECHAT.md)。

| 遇到的问题 | 从哪里查 |
| --- | --- |
| 微信已有原消息，接收器无记录 | 核对触发器范围、原生入站记录、冻结请求和 SSH 回环连通性 |
| 请求已入队，专用会话未显示 | 核对固定目标和原入队回执。结果不确定时按原 ID 对账 |
| Codex 已完成，微信未收到 | 核对触发器保存的结果和原 V2 回执。实际投递以微信回执为准 |
| 图片未出现在 Codex | 查原图导出阶段、来源校验和接收器的附件摘要 |

## 诊断与验证

```sh
python -m rsi_agent --help
python -m rsi_agent --config /private/installation.json doctor
python -m rsi_agent --config /private/installation.json audit
python -B scripts/check.py --linux
```

`doctor` 检查依赖、权限和读写条件。 `audit` 检查实际 Linux 窗口和服务，发现退化会返回非零状态。回归运行环境及依赖见[验证说明](harness/README.md)。两侧就绪、Codex 完成、微信回执是不同的证据，收发验收需要核对原消息。

Linux 安装配置示例见 [examples/linux.json](examples/linux.json)，默认关闭写操作。相对路径以配置文件所在目录为准，账号资料和授权文件归实际调用用户持有。手动读取、原 V2 回执查询和桌面服务准备见 [Linux 微信操作说明](docs/INTEGRATION.md#linux-微信操作)。

## 配套目录

- [components/wechat-linux/](components/wechat-linux/) 是触发器依赖的 Linux 微信模块，提供原生消息读取、附件校验和 V2 回传。
- [archive/](archive/) 保存 Mac 微信采集器、秘书工作台的记事本与配套源码、本机 Codex 和 Dot MCP 实验。
- [rsi_agent/](rsi_agent/) 提供统一命令、配置、诊断和旧启动入口。[deploy/](deploy/) 放服务模板，[scripts/](scripts/) 和 [tests/](tests/) 放验证脚本和回归测试。
- [harness/](harness/) 放协议与接入说明。[memory/](memory/) 放项目决策与待办。[docs/](docs/) 放集成和验收记录。
