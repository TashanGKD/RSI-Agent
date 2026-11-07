# Integration and acceptance

The first release brings both source packages into one repository and adds one CLI and installation configuration.
The complete upstream snapshots were imported first; the next commit adapts seven Linux helper files through `rsi_runtime_env.py`. The inherited queues, message identity, snapshot consistency and native receipts are not replaced.

## Runtime boundaries

- Notebook: use the existing local server and schema, with a new explicit demo workspace or an existing user-owned workspace.
- Linux WeChat: one existing official client, one operator display, one original operations queue. Read requests cannot reach send actions through the read entry.
- Mac collector: source integrity verification is available from the root CLI. Compilation and actual use still require the separately authorized missing dependencies and macOS.
- ClawBot, host coordination and monitor remain available under the original workbench component. Their binding, credentials, timers and scopes are not synthesized by the new CLI.

Linux display and Xauthority are passed as `WECHAT_DISPLAY` and `WECHAT_XAUTHORITY`. Other inherited paths are set through `WECHAT_TOOL_ROOT`, `WECHAT_NATIVE_CODE`, `WECHAT_HOST_SUPPORT_CODE`, `WECHAT_PROFILE`, `WECHAT_ACCOUNT_ID` and the existing OCR variables. The installed GTK/X11/OCR and Python decoder dependencies must be supplied by the operator. The adapter does not extract keys, log into WeChat, send setup messages or silently fall back to a different account.

`operations_enabled` is an installation switch, not a replacement for real business authorization. Upstream client labels are attribution fields, not isolated permission tenants. Real source credentials and UI bindings stay outside this repository.

## Horyzon acceptance still to do

1. Persist and validate the existing X/WeChat/noVNC service definitions; check boot directories, Xauthority, ordering, crash recovery and operator handover. Schedule the actual disruptive recovery checks in a maintenance window.
2. Supply current-account authorization and calibrate the current `:92` desktop. Validate source identity, encrypted snapshot consistency, incremental/late message coverage and unsupported media gaps.
3. Use an explicitly selected test conversation for native text/image/file receipts, stable-ID replay, dropped responses and interrupted-client recovery.
4. Observe a 24–72 hour trial before describing the installation as stable. Record missed reads, duplicate sends, outages and recovery rather than only process uptime.

The first release does not restart or replace Horyzon's live client. No claim of live send, phone receipt or long-run acceptance follows from passing fixture tests.
