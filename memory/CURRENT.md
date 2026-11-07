# Current checkpoint

## User outcome

Make RSI Agent usable and maintainable through evidence-backed improvements,
with GitHub memory, a shared Harness and small PRs. The requested cadence is
every 45 minutes in the existing Codex chat.

## Verified baseline

- Latest checked main and installed code: `e8dfd084d2053de60b091b9f027e74a4a36311ca`.
- PR #1 is merged and its code-only release is complete. Current points to
  `/opt/rsi-agent/releases/e8dfd084d205`; the prior immutable release is retained.
  Its merged PR body contains the delivery receipt and rollback evidence.
- One File Transfer text was accepted at 2026-11-08 00:06:05 +08:00. Native sender,
  peer and exact body matched; one terminal attempt and same-ID receipt replay
  were verified. See `docs/HORYZON-ACCEPTANCE.md`.
- Mac is still a source package with missing build dependencies.

## Active improvement

Reject ambiguous request JSON before delegating to the native SDK. The unified
baseline CLI drops earlier duplicate keys, so the original SDK's duplicate-key
check cannot see an overwritten peer, request ID or nested payload. Hypothesis:
checking pairs during the first parse prevents delegation, while valid Unicode
and message text containing JSON-like strings remain unchanged. The four
duplicate-key cases failed before the fix and pass with the narrow parser change.
See [request comparison](../harness/evidence/2026-11-08-request-json.json).

This is the only change under consideration. If its PR is merged and delivered,
there is no remaining request-validation WIP. Check its head, CI and delivery receipt;
the installed revision is authoritative in `/var/lib/rsi-agent/release.json` and
`/opt/rsi-agent/current`, rather than the checked baseline above.

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

Until delivered, close the request-validation WIP through normal CI and code-only promotion,
preserving an immutable prior release, private metadata and pointer rollback.
Verify duplicate-input rejection at the actual current CLI and unchanged process,
configuration and send-attempt count. Keep observed completion in that PR's
delivery receipt. After delivery, choose only a demonstrated independent defect;
unchanged or externally gated state is no-op. Real-client cancellation needs its
own unsent-draft scope; service activation needs its X/WeChat/noVNC window.
