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

## Horyzon live acceptance

On 2026-11-08, the configured account was read through the unified CLI and one owner-authorized text was sent to File Transfer Assistant through the original V2 queue. The native record matched the exact sender, peer and text, with status 2 and one Send click. Same-ID submission returned the existing receipt. See [the installation record](HORYZON-ACCEPTANCE.md) for scope, bootstrap state and remaining work.

Native control locks now live in the private runtime directory so installed source can remain read-only. Openbox-reparented windows use absolute screen coordinates. File Transfer localization is recognized only for the exact native `filehelper` identity. GTK diagnostics load the actual Gtk namespace. A private `editor_content_top` may exclude up to 12 pixels of the calibrated top frame from empty-composer inspection; visible content remains protected. WCDB snapshots may trim only all-zero preallocation after an authenticated, valid SQLite header size; active pages, committed WAL frames and SQLite integrity are still checked.

## Horyzon acceptance still to do

1. Persist and validate the existing X/WeChat/noVNC service definitions; check boot directories, Xauthority, ordering, crash recovery and operator handover. Schedule the actual disruptive recovery checks in a maintenance window.
2. Finish ordinary, non-debugger startup after the authorized login bootstrap. Recalibrate changed layouts and validate incremental/late message coverage and unsupported media gaps.
3. Text-to-File-Transfer and stable-ID replay are verified for one controlled sample. Image/file receipts, other conversations, dropped responses, manual takeover and interrupted-client recovery remain unverified on this installation.
4. Observe a 24–72 hour trial before describing the installation as stable. Record missed reads, duplicate sends, outages and recovery rather than only process uptime.

The source-import release did not restart the client. The subsequent live test used the owner's explicit restart and test-message authorization. Its native acceptance does not establish a phone-seen receipt or long-run reliability.
