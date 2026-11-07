# Verification Harness

The current Harness has two runnable entrypoints:

| Entry | Runs | What it establishes |
| --- | --- | --- |
| `python -B scripts/check.py --linux` | Synthetic adapter/native-reader/queue/snapshot regressions, temporary notebook HTTP and Mac manifest | Code regression evidence on Linux |
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

For the agent self-improvement layer, see [Penguin integration](PENGUIN.md).
The regressions and audit are usable engineering gates, not a Penguin Formal
Baseline or evidence that an optimizer improves itself.
