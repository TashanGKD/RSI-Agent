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

## Known operational limits

Ordinary startup after GDB bootstrap has not been verified. The normal startup
script was restored, but the current client was still traced at last inspection.
Desktop units were transient. The send used a calibrated 905×667 main window and
623×667 conversation; layout changes can block later preparation. One cancelled
test draft needed manual cleanup. Do not claim general recovery or long stability.

The user has not answered the outstanding question about another normal restart
and possible phone confirmation. Continue independent engineering without
restarting the live client or sending another test message.

## Next checkpoint

Run the new audit against the current host, preserve its sanitized result and
attach CI plus the actual PR. Then select the highest-value item in `todo.md`.
