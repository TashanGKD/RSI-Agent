# Verification Harness

The regular Harness has two entrypoints:

| Entry | Runs | What it establishes |
| --- | --- | --- |
| `python -B scripts/check.py --linux` | Synthetic adapter/native-reader/queue/snapshot regressions, isolated X/VNC bootstrap and service-definition verification, temporary notebook HTTP and Mac manifest | Code regression and isolated Linux startup evidence |
| `python -B -m rsi_agent --config /private/installation.json audit` | Existing X11 window metadata, owning process's TracerPid, service FragmentPath and dependency prerequisites | Current structural runtime findings without reading messages or sending input |

`audit` prints bounded JSON. Exit 0 means the inspected conditions pass; 1 means
degraded/blocked; 2 means unsupported platform. Its result is intentionally
separate from `doctor`, which reports prerequisites, and from native delivery
proof. It recognizes the installation's existing `wechat-gui-*` service names
and calibrated 905×667 main layout. Other installations need their own verified
adapter rather than a false pass.

Run a candidate from an isolated checkout against the private host configuration;
do not switch the production release merely to inspect it. Keep full artifacts
private and retain only sanitized findings supporting a decision. Record exact
base/head revisions, observed time, validation commands and limitations in the PR.
Freeze regression cases before evaluating a candidate; a changed test definition
requires a new baseline and is not comparable to the old result.

The new bootstrap fixture owns a temporary directory and child X server on an
unused display. It validates X authorization and a VNC handshake without WeChat,
production data or service installation. See the
[service bundle](../deploy/wechat-gui/README.md) for the staging entrypoint and
the still-pending production migration/rollback boundary.

`python3 -B scripts/rehearse_service_migration.py --execute` is a separate root
integration fixture for a real systemd host, outside ordinary CI. It creates only
disposable names and verifies the complete private HTTP/WebSocket/VNC path before,
during and after rollback. Its desktop is `sleep`; production login, boot and
layout recovery remain separate acceptance. Without `--execute` it only prints help.

The local operator's SSH and installation bindings can be kept in ignored
`var/maintenance/operator.json`. They are execution context, not project memory.
Inspect the current remote release each time rather than carrying an old SHA
into the next run. The first sanitized host audit is in
[`evidence/2026-11-08-horyzon-audit.json`](evidence/2026-11-08-horyzon-audit.json).

For the agent self-improvement layer, see [Penguin integration](PENGUIN.md).
The regressions and audit are usable engineering gates, not a Penguin Formal
Baseline or evidence that an optimizer improves itself.
