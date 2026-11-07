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
shared maintenance Skill support service preparation. The candidate has completed
isolated transport migration/rollback; production is awaiting a maintenance window.

[PR #1](https://github.com/Yu-Yang-Li/RSI-Agent/pull/1) is open for this work.
Recheck its current remote head and CI after each push. Heartbeat
`rsi-agent-harness` has now produced two actual scheduled preparation rounds.

Latest code candidate `59b018e45aa2d369b23f15ab658fab0f2ae579dd` includes
`services stage`, six unit templates, private Xauthority/readiness bootstrap and
the root/systemd rehearsal. Its exact Git archive passed 450 Linux checks,
notebook HTTP and Mac manifest checks on Horyzon. The
[bootstrap fixture](../harness/evidence/2026-11-08-horyzon-service-bundle.json)
verified authorization, permissions and readiness; the staged graph passed
systemd verification. This bundle is not activated on production.

The separate root rehearsal verified actual transient → persistent → rollback unit
selection, with HTTP 200, WebSocket 101 and RFB handshake in every phase. The
desktop was an isolated sleep process. The initial assumption that stopping only
a target waits for all children was rejected; explicit stop requests for every
owned unit fixed the cleanup barrier. No fixture definitions, units or runtime
directories remained, and production service PIDs were unchanged. See
[`migration evidence`](../harness/evidence/2026-11-08-horyzon-service-migration.json).

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

The user's report of a message getting no reply exposed a separate product gap:
this installation has no automatic incoming-message/AI-reply service. The exact
conversation is awaiting clarification. Existing read/send access is not an
automatic chat loop or new standing-send authorization.

## Next checkpoint

Two service-preparation rounds have now closed staging and isolated transport
migration/rollback. Actual production persistence is blocked on a suitable new
maintenance window for X/WeChat/noVNC interruption and possible phone confirmation;
it is not blocked on repeating syntax checks. Preserve the candidate and move to
the independent cancellation-recovery fixture in todo item 3 while that window
is unresolved. Check PR #1's actual head/CI first; do not repeat live sends.
