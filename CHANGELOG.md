# Changelog

记录用户可感知的功能、修复与行为变化。日期使用北京时间；以下日期分组是主线合并记录，不代表已发布带版本号的安装包，也不代表所有运行实例已经升级。

初版回填经过 Git/PR 核对的近期变化，更早的完整历史保留在 Git。尚未完成的目标见 [路线图](docs/ROADMAP.md)，实际部署与验收范围见 [CURRENT](memory/CURRENT.md)。

## 2026-11-23

### 改进

- 聊天队列消息内联收发协议要点，携带绝对入口、配置路径、原请求 ID 与摘要，减少每轮读协议文件的固定开销；核验规则不变。[PR #152](https://github.com/TashanGKD/RSI-Agent/pull/152)
- 队列、送达通知与中断重排队统一使用 `codex queue --resume`，自动唤醒未加载的会话；唤醒失败仅告警，不重投原消息。[PR #152](https://github.com/TashanGKD/RSI-Agent/pull/152)
- 成功且清理完成的送达更新只入 V2 账本，不再产生可见通知轮次；失败、部分发送、结果不确定与清理未完成仍通知原会话。[PR #152](https://github.com/TashanGKD/RSI-Agent/pull/152)

### 文档

- 路线图补充定时任务框架与会话交互设计（含依赖顺序与风险约束）。[PR #152](https://github.com/TashanGKD/RSI-Agent/pull/152)

## Unreleased

### 已合并主线（2026-11-22，随 `009bbda`）

[PR #124：本地接入、回复恢复与送达反馈](https://github.com/TashanGKD/RSI-Agent/pull/124) 已合并；部署与验收范围见 [CURRENT](memory/CURRENT.md)：

- 新增私有配对、固定客户端的授权准备和分阶段就绪检查；保留已有令牌、账号资料和队列。
- 新增 WSLg/Xephyr 服务准备及 Windows 登录任务；完整服务包可显式绑定主号协调器和 Python，启动器检查主号服务是否运行。
- 修复 WSLg 剪贴板与独立 X11 桌面不一致、空编辑区悬停提示误触发草稿保护的问题。
- 主号私聊可收束已证明现场恢复的发送前失败，并只恢复指定已发送原单的清理状态，不重放旧回复。
- 送达反馈保留清理状态；晚到回执可持久化通知原会话，只查询原结果，不生成或发送另一条微信回复。
- 健康检查区分接收器就绪与新近的原生运行观察；处理内层 X 屏保，保持 Windows 电源策略不变。
- CI 对镜像下载设置超时和切换边界，保留全部 Linux、Windows 与隔离桌面检查。
- 新增 `docs/ROADMAP.md` 和根目录 `CHANGELOG.md`，在 README 提供入口，区分未完成目标、变更历史及部署验收状态。

## 2026-11-21

### 新增

- 支持接收微信中的 `.docx`，校验原始文件、Word 包结构和摘要，提取正文段落与表格。旧 `.doc`、表格和幻灯片不在该能力范围内；完整新消息回传验收仍单列。[PR #126](https://github.com/TashanGKD/RSI-Agent/pull/126)

### 修复

- 将已下载 PDF 的读取预算提高到 25,000,000 字节，保持原生来源、大小和 MD5 校验；超限与缓存不可用分别反馈。[PR #125](https://github.com/TashanGKD/RSI-Agent/pull/125)

### 文档

- 记录新原生 PDF 的完整收发验收与附件规则复用，区分 Word 的实现状态和待验收范围。[PR #127](https://github.com/TashanGKD/RSI-Agent/pull/127)
- 增加共享验证页的候选经验：分别读取构建状态、验证命题和独立审查证据；规则仍需后续独立请求证明复用。[PR #128](https://github.com/TashanGKD/RSI-Agent/pull/128)

## 2026-11-20

### 新增

- 支持将已核准的工程任务路由至维护会话，普通聊天沿原回复会话处理，减少长任务占用回复队列。[PR #123](https://github.com/TashanGKD/RSI-Agent/pull/123)

### 修复

- 图片读取失败时，执行器可收束其自有查看器和清理状态，避免失败图片长期阻塞后续回复；保留原失败结果，不重放旧消息。[PR #122](https://github.com/TashanGKD/RSI-Agent/pull/122)

## 2026-11-19

### 修复

- 收束过期群聊队列作业，保留原请求与完成结果，避免没有执行轮次的旧输入长期占用队列。[PR #120](https://github.com/TashanGKD/RSI-Agent/pull/120)
- 修复带文字图片的工具栏识别和延迟群图的历史定位；具体部署与新原图验收分别记录。[PR #121](https://github.com/TashanGKD/RSI-Agent/pull/121)

### 整理

- 统一晚间摘要实现及批量等待逻辑，清理不再被运行链路调用的归档入口与重复项目资料，历史保留在 Git。[PR #121](https://github.com/TashanGKD/RSI-Agent/pull/121)

## 维护约定

- 新变化先进入 `Unreleased`，待合并候选显式注明来源；合并后移入对应日期，正式建立版本发布流程后再按版本分组。
- 只记录有证据的用户可感知变化，不逐条复制提交信息或运行日志。
- 代码合并、发布、部署和真实验收分别记录；不把 CI 通过写成已送达，也不将单机验收推广到其他环境。
- 完成的路线图目标从路线图移除，在这里保留对应交付摘要与 PR；账号身份、凭据、聊天和私有回执不进入本文件。
