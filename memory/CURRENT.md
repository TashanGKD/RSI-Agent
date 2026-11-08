# Current checkpoint

## User outcome

Make RSI Agent usable and maintainable through evidence-backed improvements,
with GitHub memory, a shared Harness and small PRs. The requested cadence is
every 45 minutes in the existing Codex chat.

## Verified baseline

- Latest checked main and installed code: `85f54bc464ee118071ec2e82d8aa582de5bce6e0`.
- PR #4 is merged and its code-only release is complete. Current points to
  `/opt/rsi-agent/releases/85f54bc464ee`; the prior immutable release is retained.
  Its merged PR body contains the delivery receipt and rollback evidence.
- One File Transfer text was accepted at 2026-11-08 00:06:05 +08:00. Native sender,
  peer and exact body matched; one terminal attempt and same-ID receipt replay
  were verified. See `docs/HORYZON-ACCEPTANCE.md`.
- Mac is still a source package with missing build dependencies.

## Active improvement

Configure only RSI Agent's model interface, as explicitly clarified by the user.
Use SCNET `https://api.scnet.cn/api/llm/v1` with the live catalog's pinned
`DeepSeek-V4.1-Flash-1017`. Horyzon's root-owned private provider configuration
and separate key are installed; both text and nonexecuting tool-call probes
returned HTTP 200. No credentials or provider reasoning are copied into Git.

Hypothesis: a small shared Chat Completions client and explicit `model check/reply`
CLI can make this provider callable without the retired WeChat worker, Codex
authentication or automatic sending. Verify the actual installed path after
normal review/CI and code-only promotion. This is the only WIP. Its PR delivery
receipt and `/opt/rsi-agent/current` plus `/var/lib/rsi-agent/release.json` resolve
the later deployment state; this checkpoint does not predeclare release.

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

Close the SCNET model interface through normal CI and code-only promotion,
preserving an immutable prior release, private metadata and pointer rollback.
Run `model check` from the actual current source using the private provider
configuration; keep WeChat processes, configuration and original requests unchanged.
Record completion in the same PR's delivery receipt. After delivery, choose only a demonstrated independent defect;
unchanged or externally gated state is no-op. Real-client cancellation needs its
own unsent-draft scope; service activation needs its X/WeChat/noVNC window.
