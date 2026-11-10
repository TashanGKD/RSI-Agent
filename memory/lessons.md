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

- **接收｜群图缺附件。** 先查原图片的导出任务。一次有界恢复核对了官方卡片
  和保存控件，文件 MD5 与原消息一致，Codex 实际读取。原 V2 初次被草稿保护拦截，
  后经同请求对账证实微信只发一次。桌面保留首次未发送的记录。判断送达时以原 V2
  为准，这个案例的自动恢复仍待验收。
- **RSI｜本人任务回传。** 原请求、输入摘要和执行轮次一起绑定完成结果。
  一次真实工程文本回传经原 V2 和原生记录核实为单次发送。下次在报告微信已发送前
  查同一条原生回执。接口收到结果只是交接阶段。
