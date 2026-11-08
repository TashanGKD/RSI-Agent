# Current checkpoint

## User outcome

Make RSI Agent usable and maintainable through evidence-backed improvements,
with GitHub memory, a shared Harness and small PRs. The requested cadence is
every 45 minutes in the existing Codex chat.

## Verified baseline

- Latest checked main and installed code: `907b8061de84ad580cc4d07ce6b60732ac936bdb`.
- PR #5 is merged and its code-only release is complete. Current points to
  `/opt/rsi-agent/releases/907b8061de84`; the prior immutable release is retained.
  Its merged PR body contains the delivery receipt and rollback evidence.
- One File Transfer text was accepted at 2026-11-08 00:06:05 +08:00. Native sender,
  peer and exact body matched; one terminal attempt and same-ID receipt replay
  were verified. See `docs/HORYZON-ACCEPTANCE.md`.
- Mac is still a source package with missing build dependencies.

## Active improvement

Keep `doctor` useful when the dedicated user cannot traverse a configured runtime
or profile directory. A synthetic installation reproduces a complete CLI block
(exit 2) rather than the usual per-layer report. The same frozen fixture fails
on both cases at the deployed baseline; no production permissions were changed.

Hypothesis: treat permission-denied file/directory probes as unmet prerequisites,
while retaining the other diagnostic layers and blocking read/write operations.
Keep file ownership, mode and symlink rules intact. This is the only WIP; normal
review/CI, code-only promotion and the frozen unprivileged fixture from actual
current source must close it. Read its live PR receipt and actual host metadata
for later deployment state rather than predeclaring release here.

The SCNET interface is complete: `DeepSeek-V4.1-Flash-1017`, real text/tool-call
checks and UTF-8 CLI reply all passed from current. See [PR #5's delivery receipt](https://github.com/Yu-Yang-Li/RSI-Agent/pull/5).
The user was told that this is a model interface, with automatic replies still
disabled. No model WIP remains and no repeat provider probe is needed absent a
new relevant source change or demonstrated failure.

Original-receipt recovery is complete, including interrupted-query recovery;
do not retain it as WIP. See [PR #4's live delivery receipt](https://github.com/Yu-Yang-Li/RSI-Agent/pull/4)
and [comparison](../harness/evidence/2026-11-08-receipt-recovery.json).

PR #3 has delivered X11 dependency diagnosis and contains the eighth-round
benefit audit: two bounded CLI paths were repaired and published in the last four
rounds; general delivery, recovery and auto-reply are separate. Its
[receipt](https://github.com/Yu-Yang-Li/RSI-Agent/pull/3) supersedes the candidate
status in [X11 evidence](../harness/evidence/2026-11-08-doctor-x11.json).
PR #2's duplicate-request rejection is also released; do not keep either as WIP.
The fourth-round audit retuned candidate accumulation to actual delivery. PR #1
then published the current-path audit and cancellation repair. Its deployed
source passed the isolated Qt/Openbox cancellation fixture; official WeChat UI
acceptance remains separate. Do not tune the delay again. See the
[review](../harness/evidence/2026-11-08-four-round-review.json),
[cancellation comparison](../harness/evidence/2026-11-08-horyzon-cancellation.json)
and [completed release receipt](https://github.com/Yu-Yang-Li/RSI-Agent/pull/1).

## Known operational limits

After explicit user authorization, an ordinary client restart and cached login
succeeded on 2026-11-08 without another phone prompt. The old debugger exited;
the new official client has TracerPid 0. The 905×667 main / 623×667 conversation
layout and private binding were restored manually. The original test message
was read back with exact text and configured sender, and total send attempts
remained one. See
[`normal-startup evidence`](../harness/evidence/2026-11-08-horyzon-normal-startup.json).

The latest structural audit now reports only `SERVICES_NOT_PERSISTENT`.
Desktop units are still transient. Layout restoration was manual rather than
automatic across restart, and one cancelled test draft earlier needed manual
cleanup. Server-boot persistence, general recovery and long stability remain
unverified. The single restart authorization has been used; no additional send
or repeated restart is implied by the 45-minute maintenance cadence.

The user clarified that their message was sent directly to the logged-in account.
A bounded read confirmed an incoming private text at the native layer; the user
confirmed that sender, and the exact binding remains in a private host file.
Automatic replies remain disabled. Configuring a model interface does not grant
a new standing-send scope or enable the retired worker.

## Next checkpoint

Close permission-tolerant diagnosis through normal CI and code-only promotion,
preserving an immutable prior release, private metadata and pointer rollback.
Run the frozen real-filesystem fixture as an unprivileged Linux user from actual
current source; keep WeChat processes, configuration and original requests unchanged.
Record completion in the same PR's delivery receipt. After delivery, choose only a demonstrated independent defect;
unchanged or externally gated state is no-op. Real-client cancellation needs its
own unsent-draft scope; service activation needs its X/WeChat/noVNC window.
