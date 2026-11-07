# Source refresh validation: 2026-11-06

This run uses only the isolated package, synthetic temporary data and offline tests. No production account, business data, model, WeChat window or live send was used. The prior report is preserved in [2026-10-29 validation](releases/2026-10-29-VALIDATION.md).

| Suite | Actual outcome |
|---|---|
| notebook | 261 total, 261 passed, 0 skipped |
| wechat | 285 total, 285 passed, 0 skipped |
| reader | 59 total, 59 passed, 0 skipped |
| clawbot | 182 total, 181 passed, 1 skipped |
| node | 66 total, 59 passed, 7 skipped |
| package | 4 total, 4 passed, 0 skipped |
| host | 3 total, 3 passed, 0 skipped |
| audit | 27 total, 27 passed, 0 skipped |
| recording | 13 total, 13 passed, 0 skipped |

Total: 900; passed: 892; skipped: 8; failed: 0. Skips are one unavailable SILK runtime dependency and seven official desktop-fallback host scenarios. A skip is not live acceptance. Reader compression tests use the already-installed Homebrew libzstd through a test-process-only DYLD_FALLBACK_LIBRARY_PATH; no dependency or production environment was changed.

Additional checks: 20 public entrypoints with no arguments show usage or reject missing explicit arguments. A new synthetic workspace was seeded and served on loopback; actual HTTP capabilities version4.4, bootstrap and query_work succeeded with an explicitly disabled model runner. Python syntax and27 JavaScript source syntax checks passed. No new desktop GUI/phone/WeChat/group, Windows, arbitrary-format or long-running scheduler acceptance is claimed.

The package contract tests first showed the old package lacked the shared Skill, Policyv2 behavior and de-instantiated original-case module. They now verify those boundaries and no native daemon start on missing configuration. Legacy client-ACL expectations were updated to the actual published Policyv2 contract; geometry without native parent evidence now correctly rejects, with a separate synthetic verified-parent/frozen-scene positive. Existing identity/lock/receipt safety was not weakened. Font and document fixtures are synthetic. Schema compatibility uses source-code baselines, never a real database.

Privacy/secret scan and independent remote readback are separately recorded in the private delivery receipts. Logs and detected raw values are not uploaded. No original-case registration, author-acceptance record or real message/request identity is included. Installation dependencies and remaining conditions are in [INSTALL](INSTALL.md) and [refresh boundaries](REFRESH-20261106.md).

## Coverage addendum: unified inbound, read-only monitor and ordinary MCP

The initial 900-test result above remains the first-phase record. In the final isolated addendum: continuity127, monitor backend193, monitor web28, package contracts16, existing WeChat285 and host3 all passed, zero skips in these reruns. These overlap earlier package/WeChat/host suites and must not be added to900 as independent unique tests. Web typecheck/build passed with no missing external font/image assets.16 new default entrypoints printed help without starting anything.322 Python and51 module-JavaScript files compiled/parsed. The synthetic HTTP test checked a public manifest/version, GET/HEAD, private/traversal refusal, foreign Host refusal and no POST route.

Using mcp2.3.0 (the version independently read from the original AUP sender venv), a private test environment performed actual stdio discovery: sender8 tools/caller2 tools; a missing-config capabilities call failed before any host execution. Synthetic adapter tests cover inactive owner refusal, exact request forwarding, quoted configured paths/stream command compatibility and pinned Mac transport refusal. No actual native daemon, Mac gateway, source account or WeChat was called.

The five new component contracts first failed on the missing exports/default boundaries, then passed. Source-instance tests requiring private acceptance files, current onboarding records or original workbooks were not exported as portable tests; generic source-only tests were converted to synthetic IDs/files and explicit test-only installation maps. Old business-specific seed/obligation/acceptance paths were removed or disabled in the package, never in production. No retained historical business was marked complete as part of these tests.

## Installation-config review correction

The later review removed package-added absolute-path, symlink, owner/mode and size gates from installation_config only. Ordinary readable JSON, a relative config-file symlink, a0644 file above the old262144B cap, tilde paths and consistent config-directory-relative path/list/map/role fields are exercised by one synthetic compatibility test. Duplicate-key/structure/type checks and empty, non-instance defaults remain. All original tool/runtime contracts and production files remain unchanged. Prior test/publication results above retain their original dates and scope.

## Published phase2 resource delta

Only14 already-selected AUP modules and2 Mac wrappers were captured with before/after stability and exact approved after-SHA matching; runtime621 was hashed unchanged, not replaced.2 business-specific helpers and the unpublished phase3 candidate are excluded.36 synthetic resource/transport/source-reuse/owned-read-yield cases were added. The first28 showed the old package mismatch before the source merge; they then passed.8 old assertions for removed client/resource/path gates were aligned to the published contract; identity, changed bytes, missing asset, ambiguity, unrelated ownership and unknown protection tests remain.

Final reruns: operations321, reader59, package17 all passed (397 overlapping regression tests, not additional unique tests on top of prior totals). Reader compression cases used the existing Homebrew Python/libzstd through a test-process-only library path; the initial Apple-Python library-resolution failure is retained privately and was not a production decoder change. Tests use synthetic files and simulated controls; no real UI/Send/source-data call or production editing occurred. The package-only installation configuration correction remains included. New-machine, real-phone, all-format, multi-day and complete automatic-target claims remain unaccepted.

## 2026-11-07 published common-method delta

Both formal source manifests, all33 source files and both ZIP contents matched at capture. Only3 digital-employee docs and2 handoff docs plus the formal one-shot queue_closeout.mjs were merged into the portable tree; existing installation adaptations remain. The script's functions match the released source, with only the CLI RPC import/socket adapted to this repository's existing host interface. The6 original fake-RPC cases cover dry/no-call, archive-before-removal with unfinished rows retained, changed-body retention, positive merged input before dependent removals, same-ID readback after lost response with no re-add, and failed merge preserving original increments. Actual queues,10 historic cleanup originals, instance plans, job IDs and employee data were not used as fixtures. Default help and a synthetic plan without execute were checked separately without connection or archive creation. This is method/source-package acceptance, not new live queue cleanup, WeChat delivery, production/runtime changes or proof that every employee adopted the method. No old operations/reader suites were rerun for this documentation/script delta.

## 2026-11-07 responsibility/recovery/adoption documentation delta

The later formal31eb12ed0ba6 release was verified against both33-file source manifests and ZIPs, then only the specified6 documentation deltas were incrementally merged. Existing portable text, relative references, the previous queue script, installation helper and WeChat snapshot remain unchanged. Current method wording keeps final delivery with the business owner, removes an extra sending-AI approval dependency and blanket terminal-ack requirement, and separates published files, actual role reading/correction and later task adoption effects. Targeted document/reference checks and the existing package contracts were run; no new gate, worker, runtime or scheduler was added and no old397-test/WeChat acceptance was repeated. This source publication does not prove all11 roles adopted the method.

## Fixed duty profiles and complete synthetic workbook

Five selectable duty profiles were added under workspace-template (not five employee registrations): people/common methods, WeChat tools, read-only workbench monitoring, shared business notebook maintenance and optional mechanical execution. The existing7-template format is reused for one synthetic role, three independent work notes, generated CURRENT, empty actual channels/receipts, source texts, local artifacts and a clearly simulated experience case. Existing seed_monitor now previews by default or explicitly copies that bundled fixture into a new caller-selected temporary output; it uses the original workbook parser/refresh/check and monitor publisher, without source-account/model/RPC/sender/scheduler calls. The output's installation.example.json uses the existing ordinary configuration schema.

Actual checks:25 package tests including8 new example/negative tests,29 web tests including1 new real React SSR example test, and existing typecheck/build all passed. These are54 overlapping suite tests, not54 entirely new cases. Rejections cover existing output/aliases without overwrite, a missing required workbook field, non-synthetic channels/fabricated native receipt input, and publication failure cleaning only the invocation's new output; relative and parent-alias temporary paths are accepted. The original workbook script generated/checked three states separately.88 local document/template links resolved with no unfilled example placeholders. A real loopback GET/HEAD renderer served the synthetic manifest/snapshot/profile and built index, while private fixture/STATE routes and POST were refused. SSR displayed the actual synthetic relationship/role views and outstanding tasks; the original filter model keeps all3 notes and2 open notes.

The first unit checks exposed missing profiles/complete temp example; an additional real SSR test caught a missing discovery envelope that backend-only validation had allowed. The synthetic publisher was corrected, not the existing monitor implementation. No screenshot/manual browser, real hosted workbench, employee reading/adoption, official account, native delivery or continuous runtime acceptance is claimed. No old397 regression, production write, template/Skill-original change or new service/gate/timer occurred. Existing component/source cutoffs remain their original facts.
