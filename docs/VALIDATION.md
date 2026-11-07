# First integration validation

2026-11-07, Asia/Shanghai. Both source branches were checked against their upstream main commits before import. Their exact commits are in `SOURCES.lock.json`.

## Executed checks

- 11 new adapter checks: unconfigured installation diagnostics, configuration-relative paths, invalid display/flags, read/send separation, forwarding the original request ID/body, shared display and Xauthority, demo overwrite refusal, validation before demo side effects, and both source identities.
- On Horyzon Linux, the imported V2 operations suite passed 321 tests; snapshot consistency passed 7; native-read/receipt/replay checks passed 31; reader regressions passed 59. These are 418 inherited synthetic checks, not 418 newly written tests.
- The unified notebook command actually created a NEW synthetic workspace, started the existing loopback server and returned HTTP 200 with meaningful HTML. Its own test processes were stopped afterwards.
- Mac package verification passed: 160 selected sources, 173 package files. This is source integrity, not an application build or macOS runtime acceptance.
- The adapter exposed an invalid-port ordering issue during review: the new regression first failed, then port validation was moved ahead of demo initialization and the test passed.

The Linux suites use empty account/profile paths, mock drivers and temporary databases. No GUI input, real chat body read, key extraction, message send, model call or production WeChat restart was part of these checks. Existing queues and server-side account data were not imported.

CI executes the same `python -B scripts/check.py --linux` entry on Ubuntu 24.04 / Python 3.12. Its result must be checked separately on GitHub; adding the workflow alone is not proof it passed.

## Remaining acceptance

Current-account authorization, desktop layout calibration, native send receipts, manual takeover, persistent service migration, disruptive recovery and a 24–72 hour live trial remain installation work. The Mac component still lacks the dependencies documented in its original `docs/BUILD_GAPS.md`. The new repository does not relabel those gaps as completed features.
