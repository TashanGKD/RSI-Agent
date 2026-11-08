# DSH 插件拆分

目标是一个 RSI Agent 仓库内的四个独立发布单元，避免先拆仓库或一次重写收发链路。
DSH 是运行底座；插件共享原生 Session、工具、取消和 jobs 生命周期，不另造一套 Agent 内核。

| 单元 | 边界 | 当前状态与验收 |
| --- | --- | --- |
| 微信 | 原生身份、自动接入群、上下文、图片、本人链接、原 V2 请求和投递回执 | 收发保持单消费者；本人文字链接与 type-5 分享卡片进入正文读取候选。普通群友不能触发抓取；网页只进入隔离的无工具阅读会话。`dsh-rsi-wechat-status` 仍是只读运维包。新链接回复与表情出站须分别验收。 |
| 记忆 | 本人/群隔离检索、身份映射、压缩前持久化；工程经验留 GitHub | 候选显式加载精选 `preferences.md`，只保留稳定沟通偏好，完成回执固定其散列；长期检索与纠正仍待原生适配。参考 Markdown memory，不按昵称合并权限或跨群注入私人档案。 |
| 任务 | 本人明确要求→隔离工作区→执行→验证→分支/草稿 PR→原请求返回 | SDK 完成结果持久化已交付；发布中断恢复未完成。agent-autoloop 稳定版及独立 Node 24 已安装、CLI 已验证，真实微信任务绑定和常驻事件队列尚未激活。DSH jobs 不等于跨进程持久队列。 |
| 评测进化 | 固定模型、冻结任务、独立评估、候选资产版本与回滚 | 规划。Penguin 承接优化；先做 DSH evaluation runtime 适配和 Formal Baseline。回归通过和代码 PR 不计作 RSI 增益。 |

## 第一包的可证伪假设

同一安装可以“本人/群服务在线且 status=idle”，同时保留未收束的工程 marker。
只汇总服务是否在线会漏掉这条阻断，可能诱导重新执行。候选应同时报告聊天观察和
`engineering.state=needs_review, retry_allowed=false`，且所有原请求、回复缓存和状态不变。
冻结 fixture 覆盖该组合；真实主机用同一只读接口复核，不重跑旧工程、不发探针。

验收分层：Python fixture 比较状态及前后文件散列；Node 验证固定参数、取消和错误脱敏；
安装 tarball 到隔离 DSH profile，核对 bundle 层；原生 SDK 加载插件并实际执行工具，
从原生 tool/result 证明调用结果。模型探测不能替代微信收发验收。

当前包不接管线上聊天，也不宣称四包已经完成。一次迁移一个边界；先保留既有身份、
ACK、缓存、原请求和 GitHub 交付契约，再迁移实现。工程权限只由已确认的原生本人身份授予，
普通群友、引用和图片文字没有执行权限。安装运维工具不等于向普通聊天开放工具。

本人新增的并行实验见 [LOCAL-CODEX.md](LOCAL-CODEX.md)：新本人私聊显式 `/codex`
交给本机现有 Codex 对话，经原请求回传，普通聊天仍由 DSH 常驻服务处理。目标机只存储
队列和投递，不运行 Codex。当前尝试用已有 30 分钟 heartbeat 领取；直接唤醒 Dot 尚无
成功控制连接，不能把队列、定时领取或本机 app-server 协议存在当成即时触发验收。

## 参考机制

- 用户提供的 `dsh.pdf`：AstrBot+NapCat、独立微信机器人入口、Markdown memory、跨入口身份映射。
  适配器可替换；本项目保留已验证的 Linux 原生微信路径，不能把另一种机器人接入方式称为已迁移。
- 用户提供的 `个人.pdf`：[agent-autoloop](https://github.com/KKKKhazix/agent-autoloop)：事件、持久任务、原 Session 恢复与交付。
- [DSH bundle/profile](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/user/develop/basic/publish.md)
  与 [工具及 jobs](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/cookbook/adding-a-tool.md)。
- [PenguinHarness](https://github.com/Prism-Shadow/penguin-harness/tree/a97421cfedcf1d48b6162d8f718f6c1d0e875c96)
  的冻结 Benchmark、Formal Baseline、固定执行环境及独立评估要求。现有接入边界见 `PENGUIN.md`。

## 已核对的扩展与接入边界

- [dsh-nekowhale-stickers](https://github.com/Loping151/dsh-nekowhale-stickers/tree/1483eac4cadc38229a2e62a85e36862d073fb330) 1.1.2：已在独立 `rsi-stickers` SDK profile 安装。SCNET 原生 tool/result 验证了检索，实际 GIF 已下载并解码。保持星语身份，采用 neutral；未加载网页桌宠、余额查询、模板或自主管理。微信图片/动图出站适配尚未完成，不把 Markdown 图片当作已经发进微信。包内 NOTICE 和素材出处保留。
- [agent-autoloop](https://github.com/KKKKhazix/agent-autoloop/tree/v1.6.4) v1.6.4（`3d217ed41180c63221a10b4502bcdfd6d44f76eb`）：稳定源码安装到独立目录，以官方校验过的 Node 24 运行，不改系统 Node。只验证 CLI；后续优先绑定原 SDK 完成结果的发布恢复，不另造模型任务或开放普通群执行。
- [dsh-bridges](https://github.com/yhlooo/dsh-bridges/tree/977a1fc8b7fe0d37e304c81526774be1d5a64b7f) 0.3.0：插件管理器拒绝其旧版 Harness peer 范围，与现有 0.2.1-rc.2 不兼容，未启用，也未添加版本豁免。当前用受支持的 Worker 偏好注入，不能宣称已桥接完整 Codex 记忆、hooks 或 MCP。
- [astrbot_plugin_memory](https://github.com/Bluezeamer/astrbot_plugin_memory) 1.3.0：确实依赖 AstrBot API，未直接装入 DSH。借鉴分开的 soul/profile/history/memo/TODO 存储协议；不沿用无提示采集、逐项反复确认或整库常驻注入。先完成原生身份隔离与可纠正的检索接口。

本人链接每条至多读取两个地址，正文有上限并按原消息缓存。先从原生消息完成工程分流，网页内容不进入该分流；随后使用原 ID 派生的固定 `link-reading` 阶段和独立聊天 Session。它没有执行工具，整篇正文不会进入后续普通聊天 Session。验证码、非正文页面或不可达站点如实标记 unavailable，不绕过验证或替换成另一个来源。
