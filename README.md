# RSI Agent

RSI Agent 把微信消息交给本机 Codex 处理，再由原微信发送队列回传结果。项目在同一个仓库维护两个核心模块：[触发器](#触发器)负责从微信接入，[接收器](#接收器)负责接单并交给专用 Codex 会话。

```text
微信消息 → Linux 触发器 → SSH 回环通道 → 本机接收器 → 专用 Codex 会话
微信回执 ← 原 V2 发送队列 ← Linux 触发器 ← 本机接收器保存的完成结果
```

目前启用的本人私聊和群聊都走同一个专用 Codex 会话，普通文字无需加前缀。工程任务必须经原生身份和消息类型检查。独立的 DeepSeek 群聊筛选已在当前部署关闭。

## 触发器

触发器运行在微信客户端所在的 Linux 主机。它核对账号、会话、发送者和授权范围，把原生消息持久化后再 ACK。图片和链接按原生来源核验。原请求 ID、正文和附件绑定后，通过经过认证的 SSH 回环通道交给本机接收器。

| 想找什么 | 入口 |
| --- | --- |
| 本人私聊接入与回传 | [owner_reply.py](rsi_agent/owner_reply.py)、[reply_io.py](rsi_agent/reply_io.py) |
| 群聊接入与回传 | [group_reply.py](rsi_agent/group_reply.py)、[group_io.py](rsi_agent/group_io.py)、[群聊准入](harness/GROUP-ADMISSION.md) |
| 固定原始请求并投递 | [codex_backend.py](rsi_agent/codex_backend.py) |
| 图片读取及验真 | [media_io.py](rsi_agent/media_io.py)、[微信图像适配](components/secretary-workbench/wechat/operations/images.py) |

用已配置的私有文件检查触发器。两个 `check` 都不发送微信消息。

```sh
python -B -m rsi_agent --config /private/owner-replies/config.json replies check
python -B -m rsi_agent --config /private/invited-groups/config.json groups check
```

已安装的常驻服务通过相同入口的 `run` 模式工作。服务模板见 [私聊](deploy/owner-replies/rsi-owner-replies.service)和[群聊](deploy/group-replies/rsi-group-replies.service)。

## 接收器

[本机接收器](rsi_agent/codex_worker.py)在已登录 Codex 的电脑上运行。它认证请求，按原 ID 和输入摘要持久化去重，然后通过 `codex queue` 把请求交给配置中固定的专用会话。该会话核对原始请求，读取已校验的附件，再把完成结果交回接收器。接收器保存结果，触发器据此交给原 V2 发送队列核对收件人并投递。

```sh
python -B -m rsi_agent.codex_worker --config /private/local-codex.json
```

该命令用于接收器的启动配置。运行中的实例可通过认证的 `GET /health` 核对就绪状态和会话路由。配置、启动和恢复见[接收器运行说明](harness/LOCAL-CODEX.md)，会话如何读取原始请求和提交结果见[微信专用会话协议](harness/DESKTOP-WECHAT.md)。

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

## 配套组件

- [秘书工作台](components/secretary-workbench/) 提供原生微信、发送队列和记事本。 `python -m rsi_agent notebook --workspace ./var/demo --demo` 可用新目录启动合成记事本。
- [Mac 微信采集器](components/wechat-collector-mac/) 保留源码。 `python -m rsi_agent mac verify` 检查静态源码；实际构建仍有[依赖缺口](components/wechat-collector-mac/docs/BUILD_GAPS.md)。
- [触发器实验](experiments/triggers/README.md) 保存 Dot 和本机事件实验的复现方法。[SCNET 独立诊断](docs/INTEGRATION.md#scnet-独立诊断)和[项目验收记录](docs/HORYZON-ACCEPTANCE.md)也在本仓库。
- [来源锁定](SOURCES.lock.json)、[来源与许可](NOTICE.md)、[项目记忆](memory/README.md)和[Penguin 接入](harness/PENGUIN.md)集中维护在这里。
