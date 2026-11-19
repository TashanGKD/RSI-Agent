# Integration and acceptance

The [README](../README.md) describes the current trigger and receiver. This
page records the first release and the companion operator tools.

The first release brought the Linux WeChat module into this repository and added one CLI and installation configuration.
The complete upstream snapshots were imported first; the next commit adapts seven Linux helper files through `rsi_runtime_env.py`. The inherited queues, message identity, snapshot consistency and native receipts are not replaced.

## Runtime boundaries

- Linux WeChat: one existing official client, one operator display, one original operations queue. Read requests cannot reach send actions through the read entry.
- The notebook, Mac collector, ClawBot and host coordination tools were retired with `archive/`; they remain in Git history and their source repositories.

Linux display and Xauthority are passed as `WECHAT_DISPLAY` and `WECHAT_XAUTHORITY`. Other inherited paths are set through `WECHAT_TOOL_ROOT`, `WECHAT_NATIVE_CODE`, `WECHAT_HOST_SUPPORT_CODE`, `WECHAT_PROFILE`, `WECHAT_ACCOUNT_ID` and the existing OCR variables. The installed GTK/X11/OCR and Python decoder dependencies must be supplied by the operator. The adapter does not extract keys, log into WeChat, send setup messages or silently fall back to a different account.

`operations_enabled` is an installation switch, not a replacement for real business authorization. Upstream client labels are attribution fields, not isolated permission tenants. Real source credentials and UI bindings stay outside this repository.

## Horyzon live acceptance

On 2026-11-08, the configured account was read through the unified CLI and one owner-authorized text was sent to File Transfer Assistant through the original V2 queue. The native record matched the exact sender, peer and text, with status 2 and one Send click. Same-ID submission returned the existing receipt. See [the installation record](HORYZON-ACCEPTANCE.md) for scope, bootstrap state and remaining work.

Native control locks now live in the private runtime directory so installed source can remain read-only. Openbox-reparented windows use absolute screen coordinates. File Transfer localization is recognized only for the exact native `filehelper` identity. GTK diagnostics load the actual Gtk namespace. A private `editor_content_top` may exclude up to 12 pixels of the calibrated top frame from empty-composer inspection; visible content remains protected. WCDB snapshots may trim only all-zero preallocation after an authenticated, valid SQLite header size; active pages, committed WAL frames and SQLite integrity are still checked.

## First-release acceptance and open checks

1. Persist and validate the existing X/WeChat/noVNC service definitions; check boot directories, Xauthority, ordering, crash recovery and operator handover. Schedule the actual disruptive recovery checks in a maintenance window.
2. Ordinary non-debugger startup, cached login and original-message readback are now verified after explicit user authorization. The layout/binding was restored manually; automatic layout recovery, incremental/late coverage and unsupported media gaps remain unverified.
3. Text-to-File-Transfer and stable-ID replay are verified for one controlled sample. Image/file receipts, other conversations, dropped responses, manual takeover and interrupted-client recovery remain unverified on this installation.
4. Observe a 24–72 hour trial before describing the installation as stable. Record missed reads, duplicate sends, outages and recovery rather than only process uptime.

The source-import release did not restart the client. The subsequent live test used the owner's explicit restart and test-message authorization. Its native acceptance does not establish a phone-seen receipt or long-run reliability.

## Linux 微信操作

先在私有配置中填写自己的准确账号、profile 和运行目录。[examples/linux.json](../examples/linux.json) 适配合睿当前 `:92` 显示与 Xauthority 路径，但没有填账号或密钥，写操作默认关闭。

```sh
python -m rsi_agent --config /private/installation.json doctor
python -m rsi_agent --config /private/installation.json wechat read < request.json
python -m rsi_agent --config /private/installation.json wechat operations < operation.json
```

配置中的相对路径以配置文件所在目录为基准。工具应以拥有微信账号资料及授权文件的同一专用用户运行，不能通过改变文件所有者绕过原身份检查。

只读入口仅接受 `resolve/messages/voice/attachments/attachment`，不能夹带发送动作。
写操作继续走同一 V2 队列、稳定请求 ID、目标/草稿检查和原生回执，不新增第二个发送器；未知结果核原请求，不自动换 ID 重发。

桌面、解密密钥暂不可用或写开关关闭时，仍可查询已有的单条回执：

```json
{"op":"get","client":"original-client","request_id":"original-request-id"}
```

把这份 JSON 通过上面的 `wechat operations` 入口传入。Linux 下须由原专用用户持有已有的私有 `operations-state/config.json` 和 `queue.sqlite`；查询不会新建缺失队列或启动执行器。`unknown` 保持原状态，不自动重发；其他 operations 仍受原就绪门禁约束。

Linux 原生辅助函数已经统一使用 `WECHAT_DISPLAY` 和 `WECHAT_XAUTHORITY`，不再分别写死显示号。通过 RSI Agent 入口会从配置传入；直接使用原入口时仍保留原 `:97` 默认值，以兼容既有调用方。账号绑定、窗口布局和版本仍需在实际机器上验收。

持久化桌面服务可通过 `python -m rsi_agent services stage` 生成可审查的候选包，详见
[合睿服务部署说明](../deploy/wechat-gui/README.md)。该命令只生成可审查的文件。当前部署以实际服务和验收回执为准。

## SCNET 独立诊断

单独的 `model` 诊断命令可通过 OpenAI 兼容的 Chat Completions 接口调用 SCNET DeepSeek。
以 [配置示例](../examples/scnet.json) 创建私有 `config.json`，把 API Key 单独写入同目录的
`api-key.txt`；目录权限为 0700，两份文件为 0600，均由实际调用用户拥有。不要把密钥写入 Git 或命令参数。

在持有私有配置的用户下运行：

```sh
python3 -B -m rsi_agent --config /private/scnet/config.json model check
printf '你好，请介绍你能协助的工作。' | python3 -B -m rsi_agent --config /private/scnet/config.json model reply
```

`check` 实际验证文字回复与一个不会执行的工具调用，`reply` 从标准输入读取问题并返回 JSON。
其他模块可复用 `rsi_agent.model.ModelClient.complete(messages, tools=..., tool_choice=...)`；
配置中的 Base URL 已含 `/v1`，入口只追加 `/chat/completions`。请求使用直接 HTTPS 连接，不跟随重定向。
此入口不启动微信自动回复或执行模型返回的工具；现有微信与记事本的执行授权各自保留。
