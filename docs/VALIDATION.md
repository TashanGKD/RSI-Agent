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

## Follow-up host validation, 2026-11-08

- `fcd16a78014c225d6d9833afd5c0a5dba41636c2`: 437 checks passed on Linux: 12 adapter, 325 operations, 10 snapshot, 31 native-tool and 59 reader checks. The notebook HTTP check and Mac source manifest also passed.
- New regressions first reproduced the missing Gtk namespace, read-only source lock failure, Openbox relative-coordinate error, localized File Transfer identity, input-frame false positive and WCDB zero-preallocation failure. The snapshot cases also reject invalid size counters, zero active pages and nonzero tails, and cover committed WAL growth into preallocated space.
- [GitHub CI passed for this exact code commit](https://github.com/Yu-Yang-Li/RSI-Agent/actions/runs/42389024933).
- Real-account testing is separate from these synthetic checks: one text to native peer `filehelper`, one Send click, status 2, exact text/sender/peer proof, unified-CLI readback and same-ID receipt replay. Three earlier preparation requests terminated with explicit no-send evidence before the successful request. No second native attempt was created.
- The interrupted pre-send request required manual cleanup of its own test draft before cancellation could be verified. This is retained as an unresolved recovery limitation, not counted as autonomous recovery acceptance.

After a further authorized normal restart, cached login succeeded without a new phone prompt. The new process was untraced, and the existing exact test message was read back without another send. Layout and binding were restored manually; the structural audit retained only `SERVICES_NOT_PERSISTENT`. See the [sanitized normal-startup evidence](../harness/evidence/2026-11-08-horyzon-normal-startup.json).

The complete controlled result and deployment limits are in [HORYZON-ACCEPTANCE.md](HORYZON-ACCEPTANCE.md). Service persistence, automatic layout recovery, additional layouts/recipients/media, disruptive recovery and a 24–72 hour live trial remain installation work. The Mac component still lacks the dependencies documented in its original `docs/BUILD_GAPS.md`.
