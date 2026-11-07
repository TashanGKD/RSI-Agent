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

Branch `codex/rsi-harness-foundation`: the read-only audit, project memory and
shared maintenance Skill now feed the service-persistence user path. Prepare and
validate a deployable candidate before interrupting the live desktop.

[PR #1](https://github.com/Yu-Yang-Li/RSI-Agent/pull/1) is open for this work.
Recheck its current remote head and CI after each push. The requested 45-minute
heartbeat is ACTIVE in this chat as `rsi-agent-harness`; its first scheduled
invocation produced the service-bundle candidate below.

Candidate `8208c84c355c18bf9167b257efc296515a75fcaf` passed 443 Linux checks,
the notebook HTTP probe and the Mac manifest. Its real-host audit observed
`degraded` at 2026-11-07 16:26:51 UTC (2026-11-08 00:26:51 +08:00): dependency
prerequisites passed, but the 623×667 main layout, attached debugger and transient
desktop services failed the structural checks. See
[`harness/evidence/2026-11-08-horyzon-audit.json`](../harness/evidence/2026-11-08-horyzon-audit.json).
An unauthenticated public-terminal request also redirected to the password form.
Production remained on `fcd16a7`; no UI input, message read or additional send
was part of this engineering audit.

Service candidate `2b265c9d958435ac6fb587ee3017944e8b749a27` adds
`services stage`, six persistent unit templates and private Xauthority/readiness
bootstrap. An exact Git archive passed 450 Linux checks, notebook HTTP and Mac
manifest checks on Horyzon. The real isolated X/VNC fixture verified authorization,
private permissions, handshake and refusal to replace an existing socket's auth;
the staged graph passed systemd verification. Production service PIDs and release
were unchanged. See
[`service-bundle evidence`](../harness/evidence/2026-11-08-horyzon-service-bundle.json).
The bundle is prepared, not installed or activated; this closes the staging and
isolated bootstrap path, not boot persistence.

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

After checking PR #1's actual head/CI, rehearse transient-to-persistent migration
and rollback with independent unit names/display/socket paths. Do not activate
the production bundle until that plan is concrete and a suitable maintenance
window is authorized. The live persistence finding stays open.
