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
- Baseline has 437 synthetic checks plus notebook HTTP and Mac manifest checks.
  Mac is still a source package with missing build dependencies.

## Active improvement

Branch `codex/rsi-harness-foundation`: add a read-only runtime audit that exposes
conditions a successful dependency doctor misses; establish project memory and
the shared maintenance Skill. It is a candidate until its PR is merged.

[PR #1](https://github.com/Yu-Yang-Li/RSI-Agent/pull/1) is open for this work.
Its initial head passed [remote CI](https://github.com/Yu-Yang-Li/RSI-Agent/actions/runs/42391600476);
recheck CI after any later push. The requested 45-minute heartbeat was created
and verified ACTIVE in this chat as `rsi-agent-harness`. Its first future
scheduled invocation has not yet been observed; the work below was manual.

Candidate `8208c84c355c18bf9167b257efc296515a75fcaf` passed 443 Linux checks,
the notebook HTTP probe and the Mac manifest. Its real-host audit observed
`degraded` at 2026-11-07 16:26:51 UTC (2026-11-08 00:26:51 +08:00): dependency
prerequisites passed, but the 623×667 main layout, attached debugger and transient
desktop services failed the structural checks. See
[`harness/evidence/2026-11-08-horyzon-audit.json`](../harness/evidence/2026-11-08-horyzon-audit.json).
An unauthenticated public-terminal request also redirected to the password form.
Production remained on `fcd16a7`; no UI input, message read or additional send
was part of this engineering audit.

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

## Next checkpoint

Check PR #1 and its latest remote head/CI, then select the highest-value independent
item in `todo.md`. The host findings remain open until separately repaired and
rechecked; the audit surfacing them is not a repair.
