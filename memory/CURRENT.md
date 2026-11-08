# Current checkpoint

## User outcome

Make RSI Agent usable and maintainable through evidence-backed improvements,
with GitHub memory, a shared Harness and small PRs. The requested cadence is
every 45 minutes in the existing Codex chat.

## Verified baseline

- Latest checked main and installed code: `995c8c6c8ca3309b526130d8f4a50ed572400528`.
- PR #6 is merged and its code-only release is complete. Current points to
  `/opt/rsi-agent/releases/995c8c6c8ca3`; the prior immutable release is retained.
  Its merged PR body contains the delivery receipt and rollback evidence.
- One File Transfer text was accepted at 2026-11-08 00:06:05 +08:00. Native sender,
  peer and exact body matched; one terminal attempt and same-ID receipt replay
  were verified. See `docs/HORYZON-ACCEPTANCE.md`.
- Mac is still a source package with missing build dependencies.

## Active improvement

Restore actual replies to the user's confirmed private conversation. The user
selected restoring both the latest private text and ongoing incoming private
text replies using the already configured SCNET model. This is new scoped
activation/sending authorization, not a client restart or other-recipient permit.

The deployed baseline has a model port but no incoming-message/model/V2-sender
bridge. Hypothesis: the existing SourceInbox and original V2 executor can provide
durable handoff, cached model output and stable native-message-derived IDs, while
scoping all new effects to the confirmed owner. Queue attribution is not an ACL;
the adapter must enforce identity/scope and never claim a foreign queued request.
Unknown results and unproved cleanup block later replies. This is the only WIP.
Review/CI, code-only promotion, service activation and the actual native reply
receipt must be recorded separately in the same PR's live delivery receipt.

Permission diagnosis and isolated archive/install/upgrade/rollback are complete;
see [PR #6](https://github.com/Yu-Yang-Li/RSI-Agent/pull/6). Do not reopen them.

The SCNET interface is complete: `DeepSeek-V4.1-Flash-1017`, real text/tool-call
checks and UTF-8 CLI reply all passed from current. See [PR #5's delivery receipt](https://github.com/Yu-Yang-Li/RSI-Agent/pull/5).
No model WIP remains; it is the reply bridge, not provider setup, that is missing.

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
The user subsequently authorized restoring the latest owner private text reply
and ongoing replies in that same conversation. Until the new service is actually
activated, the old disabled state still applies. Do not revive the retired worker,
replay arbitrary history, send to other recipients, run model tools or restart
the official client under this authorization.

## Next checkpoint

Close the owner reply bridge through normal CI and code-only promotion,
preserving an immutable prior release, private metadata and pointer rollback.
Prepare fixed service/private configuration, enable only the authorized owner
scope, and verify the original V2 job plus native sender/peer/text acceptance.
Keep existing desktop processes and prior original requests unchanged; newly
authorized reply records are an explicit separate runtime increment.
Record completion in the same PR's delivery receipt. After delivery, choose only a demonstrated independent defect;
unchanged or externally gated state is no-op. Real-client cancellation needs its
own unsent-draft scope; service activation needs its X/WeChat/noVNC window.
