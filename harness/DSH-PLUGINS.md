# DSH 插件拆分

目标是一个 RSI Agent 仓库内的四个独立发布单元，避免先拆仓库或一次重写收发链路。
DSH 是运行底座；插件共享原生 Session、工具、取消和 jobs 生命周期，不另造一套 Agent 内核。

| 单元 | 边界 | 当前状态与验收 |
| --- | --- | --- |
| 微信 | 原生身份、登记群、上下文、真实图片、原 V2 请求和投递回执 | 已有收发实现保持原位；首包 `dsh-rsi-wechat-status` 只读诊断。迁移收发须另验真实入站→原图→模型→同会话回执，且只有一个消费者。 |
| 记忆 | 本人/群隔离检索、身份映射、压缩前持久化；工程经验留 GitHub | 规划。先复用已有上下文；借鉴文章的 Markdown memory/owner alias，不能按昵称合并权限或跨群泄漏。 |
| 任务 | 本人明确要求→隔离工作区→执行→验证→分支/草稿 PR→原请求返回 | 规划。复用 DSH jobs 和 agent-autoloop 的事件/交付机制。当前 SDK 是逐轮短进程，必须先解决常驻宿主与未收束任务，不能把原生后台 job 当跨进程持久队列。 |
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

## 参考机制

- 用户提供的 `dsh.pdf`：AstrBot+NapCat、独立微信机器人入口、Markdown memory、跨入口身份映射。
  适配器可替换；本项目保留已验证的 Linux 原生微信路径，不能把另一种机器人接入方式称为已迁移。
- 用户提供的 `个人.pdf`：[agent-autoloop](https://github.com/KKKKhazix/agent-autoloop)：事件、持久任务、原 Session 恢复与交付。
- [DSH bundle/profile](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/user/develop/basic/publish.md)
  与 [工具及 jobs](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/cookbook/adding-a-tool.md)。
- [PenguinHarness](https://github.com/Prism-Shadow/penguin-harness/tree/a97421cfedcf1d48b6162d8f718f6c1d0e875c96)
  的冻结 Benchmark、Formal Baseline、固定执行环境及独立评估要求。现有接入边界见 `PENGUIN.md`。
