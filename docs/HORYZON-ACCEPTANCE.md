# 合睿 Linux 微信接入记录

实测时间：2026-11-07 至 2026-11-08，北京时间。官方 Linux 微信版本 4.1.13.26，专用用户 `wechat-gui`，显示 `:92`。

## 已完成的实机验证

- 用户在手机确认登录后，统一 CLI 精确解析原生会话 `filehelper`。消息、会话、语音库快照通过逐页认证和 SQLite 完整性检查；本次只查询文件传输助手及自发测试消息。
- 2026-11-08 00:06:05，原 V2 队列发送一条明确标注的 `[RSI Agent 接入测试]` 文本。请求 ID 为 `rsi-horyzon-20261107-d080a8-database`，原生消息 ID 为 `1223700658069115783`。
- 原生状态为 2，唯一候选数为 1；会话、配置账号发送者和 77 字全文逐字匹配。正文 SHA-256 为 `a7b30aa5520c9e6e77fb53eabdb84c1475f98f2c1c6ae981091c27c12b378ae8`。
- 发送点击数为 1，整个测试运行目录只有一个终端发送尝试文件。统一 CLI 按原生消息 ID 回读到同一条文本；重新提交相同请求 ID 与原内容返回同一成功回执。
- 成功请求的草稿恢复、导航恢复均为真，没有待恢复标记。网页桌面可见实际消息气泡；未声称手机已读。
- 测试前因缺少 Gtk、输入框边框误判、消息库零预分配分别产生的三个请求，均已以明确的 `noSend` 结果终结。最后一例的本次测试草稿由操作员清理，自动取消恢复尚未验收。

## 安装状态

- 验收代码：`fcd16a78014c225d6d9833afd5c0a5dba41636c2`，部署于 `/opt/rsi-agent/releases/fcd16a7`，`/opt/rsi-agent/current` 指向此版。源码由 root 拥有，运行用户只有读取权限。
- 独立 Python 依赖目录：`/opt/rsi-agent/python`；主机使用 GTK 3 introspection、Pillow、X11 工具和 Tesseract 的英文、简体中文数据。
- 私有安装配置：`/var/lib/rsi-agent/installation.json`；私有运行目录：`/var/lib/rsi-agent/wechat`。账号资料、授权材料、界面绑定、队列与原始回执仅留在服务器私有目录，不进入仓库。
- 此次按次启动有时限的执行器，没有新增自动回复、定时发送或持续执行任务。`operations_enabled` 只表示本安装启用原操作入口，不能代替每次实际业务授权。
- 普通微信启动脚本已恢复。当前微信进程仍是本次授权材料准备时启动的 GDB 子进程；转为普通启动需要再正常重启一次，可能需要手机确认。已向用户询问这一收尾步骤，尚未据此宣称普通启动验收通过。

只读复核示例，在服务器以 root 执行：

```sh
cd /opt/rsi-agent/current
printf '%s' '{"action":"messages","peer":"filehelper","server_ids":["1223700658069115783"],"limit":10}' |
  runuser -u wechat-gui -- env PYTHONPATH=/opt/rsi-agent/python \
  python3 -B -m rsi_agent --config /var/lib/rsi-agent/installation.json wechat read
```

## 修复及适用范围

本次修复只针对实测暴露的问题：控制锁移入私有运行目录、Openbox 绝对坐标、仅针对原生 `filehelper` 的中英文系统标题、真实 Gtk 依赖检测、输入框上边框校准、WCDB 全零预分配。

WCDB 处理先认证数据库头。只有非零页数且 change-counter 与 version-valid-for 一致时，才按逻辑页数排除其后的全零预分配；有效范围内的零页与非零异常尾部仍拒绝。WAL 提交解析、页认证与完整性检查保留。依据为 [SQLite 文件格式 1.3.7](https://www.sqlite.org/fileformat.html#in_header_database_size)。

发送验收时主窗口为 905×667、独立会话窗口为 623×667，使用私有校准绑定。改变尺寸、窗口集合或账号会触发保护，不能据此推广到任意布局。长时间运行、跨重启持久化、普通启动后的绑定恢复、自动取消恢复、其他会话、图片、文件和语音均未完成本机验收。

合成测试共 437 项通过，另有真实记事本 HTTP 检查与 Mac 静态清单验证；[对应代码的 CI 已通过](https://github.com/Yu-Yang-Li/RSI-Agent/actions/runs/42389024933)。这些结果不等于 24–72 小时稳定性、所有功能覆盖或 Mac 应用可构建。
