# Current checkpoint

## User outcome

Make RSI Agent usable and maintainable through evidence-backed improvements,
with GitHub memory, a shared Harness and small PRs. The requested cadence is
every 45 minutes in the existing Codex chat.

## Verified baseline

- Latest checked main and installed code: `e3ddea74b49627d4584618abcb826adf5ee9ecf3`.
- PR #3 is merged and its code-only release is complete. Current points to
  `/opt/rsi-agent/releases/e3ddea74b496`; the prior immutable release is retained.
  Its merged PR body contains the delivery receipt and rollback evidence.
- One File Transfer text was accepted at 2026-11-08 00:06:05 +08:00. Native sender,
  peer and exact body matched; one terminal attempt and same-ID receipt replay
  were verified. See `docs/HORYZON-ACCEPTANCE.md`.
- Mac is still a source package with missing build dependencies.

## Active improvement

Restore original-receipt lookup when the desktop, decryption keys or write enable
are unavailable. The original SDK can get stored succeeded/unknown receipts under
those conditions, but the unified CLI blocks on full operations prerequisites.
Hypothesis: single get needs the existing private queue and policy, not live-send
dependencies. Keep SDK validation and original IDs; never create a missing queue
or start an executor. The frozen synthetic fixture reproduced the baseline block
and verified candidate recovery, unchanged queue files and protected mutations.
See [comparison](../harness/evidence/2026-11-08-receipt-recovery.json).

This is the only change under consideration. If its PR is merged and delivered,
there is no remaining receipt-recovery WIP. Check its head, CI and delivery receipt;
the installed revision is authoritative in `/var/lib/rsi-agent/release.json` and
`/opt/rsi-agent/current`, rather than the checked baseline above.

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
A bounded read confirmed an incoming private text at the native layer; matching
the sender to the user is still awaiting clarification. No automatic incoming-
message/AI-reply service is deployed, and no new standing-send scope was granted.

## Next checkpoint

Until delivered, close receipt recovery through normal CI and code-only promotion,
preserving an immutable prior release, private metadata and pointer rollback.
Run the frozen synthetic receipt fixture from the actual current source, along
with unchanged processes, private configuration and real original request records. Keep completion in that PR's
delivery receipt. After delivery, choose only a demonstrated independent defect;
unchanged or externally gated state is no-op. Real-client cancellation needs its
own unsent-draft scope; service activation needs its X/WeChat/noVNC window.
