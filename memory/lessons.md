# Retained operational lessons

- Python `gi` existing does not prove `Gtk` can load. Import the actual namespace.
- Keep locks under the private runtime. An installed source tree can stay read-only.
- Openbox reparents windows: parse absolute screen coordinates, not frame-relative
  offsets. Calibrated geometry remains a supported-layout condition.
- Native `filehelper` has localized system titles. Match that exact native
  identity and a checked title; never relax arbitrary contact-title matching.
- WCDB may preallocate zero pages beyond its authenticated logical size. Check
  header validity, authenticate active pages and WAL, then check SQLite integrity.
- A durable pre-send checkpoint with `noSend` is distinct from an uncertain
  terminal attempt. Only explicit evidence permits ending the former request;
  the latter remains the original request and is never blindly replayed.
- A single successful live text is bounded acceptance. It does not establish
  media coverage, unattended cleanup, ordinary restart or 24–72 hour stability.
- A passing dependency doctor can coexist with a traced process, changed main
  layout and transient services. Keep structural runtime findings distinct from
  dependencies and historical send acceptance; retain nonzero audit status.
- Persistent service preparation must include private runtime-directory and
  Xauthority creation plus readiness. A generated unit file is not an activated
  service: transient definitions have higher load priority than `/etc` definitions.
- A target's stop job can return before its propagated child stop jobs finish.
  Before replacing runtime authorization, explicitly wait for every affected
  service/socket/connection unit and verify cleanup. This race occurred in the
  isolated systemd migration rehearsal, without restarting the production client.
- A bare GTK or Qt editor did not reproduce the partial clear. Adding Openbox
  exposed the click arriving after Ctrl+A and collapsing selection before
  Backspace. Wait after the click, not just after Delete; retain a real window
  manager in this regression and preserve exact-text/attempt guards.

## 微信会话复用经验

- **触发｜原请求入队后长时间等待。** 一条群回复有原入队回执，桌面队列快照中
  已无同一项，所查目标会话历史也未观测到原输入。接收器仍保留原请求，完成及
  V2 结果未证实。下次用同一回执的队列项 ID 交叉核队列、目标轮次和完成记录。
  等待时长用于提醒对账，原单缺乏结果证据时保持待核对。
- **接收｜群图缺附件。** 先查原图片的导出任务。一次有界恢复核对了官方卡片
  和保存控件，文件 MD5 与原消息一致，Codex 实际读取。原 V2 初次被草稿保护拦截，
  后经同请求对账证实微信只发一次。桌面保留首次未发送的记录。判断送达时以原 V2
  为准，这个案例的自动恢复仍待验收。
- **RSI｜本人任务回传。** 原请求、输入摘要和执行轮次一起绑定完成结果。
  一次真实工程文本回传经原 V2 和原生记录核实为单次发送。下次在报告微信已发送前
  查同一条原生回执。接口收到结果只是交接阶段。
- **发送｜结构化结果泄漏。** 链接阅读的原完成结果与实际待发正文分开。
  解包必须同时用于发送和回执核验；只改触发器会使正文摘要与接收器记录不一致。
  用同一原 ID 检查微信实际收到的文本，旧回执仍按原摘要展示。
- **发送｜空白弹窗的草稿检测。** 默认群聊弹窗的边框曾让空输入框被误判为草稿。
  同一窗口样本里，输入区计数从 605 降到 44，因为检测只排除已校准位置的一行均匀灰色边框。
  验证时用同一位置的非空样本检查草稿保护，并用原 V2 事件区分准备失败和实际发送。
- **接收｜大 PDF 附件（复用）。** 读取上限提到 25 MB 后，群回复会话自行按「文档附件」
  规则处理了一份新的 12.54 MB、25 页 PDF：先核原包 `documents` 与本地 SHA-256，再读正文、
  渲染关键页，最后查同一 ID、thread、turn 的 V2 回执为 `sent`。证据只覆盖 PDF；Word
  沿用同一规则，另需一份新 `.docx` 验收。
- **接收｜动态验证页（候选）。** 有人请星语点开分享的形式化证明或构建验证页面时，
  先看页面公开的运行状态和审计日志，分别说明构建是否通过、被验证的是哪个命题、
  哪些独立检查做了或跳过。页面链到独立复核方时，读对方原记录，按运行区分证据范围，
  不把另一处的检查算到本次运行上。来源链接与对应正文放在同一气泡。一次群聊实测中
  两条分段经同一请求的 V2 回执确认送达；待后续独立请求复用后再升为规则。

### 微信控件识别

Linux 微信 4.1.13.26 的现网会话可读取 AT-SPI 注册表，但两个无障碍开关均关闭，
注册表没有应用对象。用同版本、临时显示与私有 D-Bus 在离线未登录环境开启标准
无障碍后，GTK 对照控件可读，官方微信同 PID 的应用树也能读到窗口、工具栏、
按钮及 Close 标签。已登录界面的搜索、保存和发送控件仍待验证。

先用公开接口只读查询注册表和控件树。将 AT-SPI 的 D-Bus 进程 ID 对上 X11 官方
窗口，再在正确窗口内核对唯一的角色、名称、可见状态和边界。候选控件只能替代该步
OCR 定位。原会话身份、确认和 V2 回执按各自协议核验。控件缺失、未登录或身份
不匹配时，继续使用该安装现有的定位方式。上线依据是已登录窗口的目标控件证据。
[Qt 无障碍说明](https://doc.qt.io/qt-6/qaccessible.html) ·
[AT-SPI 控件接口](https://gnome.pages.gitlab.gnome.org/at-spi2-core/devel-docs/doc-org.a11y.atspi.Accessible.html)
