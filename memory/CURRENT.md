# Current checkpoint

## User outcome

Make RSI Agent usable and maintainable through evidence-backed improvements,
with GitHub memory, a shared Harness and small PRs. The requested cadence is
every 45 minutes in the existing Codex chat.

## Verified baseline

- Main at the start of this change: `4e53016799d690ffa270a762238a4d6e234331a7`.
- Horyzon application code was deployed as `fcd16a78014c225d6d9833afd5c0a5dba41636c2`.
- One File Transfer text was accepted at 2026-11-08 00:06:05 +08:00. Native sender,
  peer and exact body matched; one terminal attempt and same-ID receipt replay
  were verified. See `docs/HORYZON-ACCEPTANCE.md`.
- Mac is still a source package with missing build dependencies.

## Active improvement

Branch `codex/rsi-harness-foundation`: the read-only audit, project memory and
shared maintenance Skill support the current cancellation-recovery repair.
Production service migration is prepared and awaiting a maintenance window.

[PR #1](https://github.com/Yu-Yang-Li/RSI-Agent/pull/1) is open for this work.
Recheck its current remote head and CI after each push. This is the third actual
scheduled engineering round; audit user outcomes at round four.

Latest code candidate `8ae366e4cc087505cc7a3d819d7c2fff72744ffe` waits 100 ms after
the editor click and before Ctrl+A in composer.clear. A frozen Qt/Openbox fixture
reproduced the baseline's partial deletion: 37 selected characters, then a late
click clearing selection, then Backspace leaving 36. The candidate restores both
empty and prior-text composers; foreign text and original attempt checkpoints
remain protected, with no Return keys. The same evaluator compares baseline and
candidate checkouts. Its exact Git archive passed the full 450 Linux checks,
notebook HTTP and Mac manifest, and the separate native cancellation fixture.
See [comparison evidence](../harness/evidence/2026-11-08-horyzon-cancellation.json).

This repairs the reproduced isolated failure; official WeChat cancellation still
needs separately scoped UI acceptance. Production service PIDs and release were
unchanged. Service staging/bootstrap and the separate transport migration/rollback
rehearsal remain prepared, not activated on production; their exact evidence is in
[`service migration`](../harness/evidence/2026-11-08-horyzon-service-migration.json).

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

Check PR #1's actual head/CI and hand off this bounded repair for review and
release. The remaining cancellation checkpoint is an explicitly scoped unsent
draft on the real client; neither the isolated fixture nor prior restart/send
authorization grants it. Do not keep tuning delays after the gates pass.
Production service activation separately needs its X/WeChat/noVNC maintenance
window. Round four must audit actual user gains before choosing more WIP scope.
