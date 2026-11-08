# Current checkpoint

## Delivered baseline

PR #16's delivery receipt superseded its candidate checkpoint. Current, release
metadata and both resident reply workers are now at main fdaa77861705, with
pinned DeepSeek Harness and SCNET. The actual Channels cover entered the production
model and received one independently audited native group reply. Ordinary-photo
official-visible export and isolated recognition passed; a fresh ordinary-photo
automatic-reply turn remains unobserved. Do not replay old image requests.

## PR #17 merged and deployed (fdaa778)

PR #17 merged into main as fdaa778 (parents 22bb0c6 and 4bf8810) and was
deployed as `/opt/rsi-agent/releases/fdaa77861705`: `current`, `release.json`
and `DEPLOYMENT.json` all name fdaa77861705a065800954125c4b277a59733ae2, with
22bb0c6b21de as prior release. Both resident reply workers (974922 owner, 974921
groups) started at 23:25 on that release and report fresh/idle, current code,
empty queues; engineering state is clear; the DSH worker runs on
deepseek-harness 0.2.1rc2. `scripts/check.py --linux` passes at this head
(10/41/59-test suites plus the unified-notebook check). Remote CI status is not
readable from this host (no `gh`, no token, the private repo API returns 404),
so merge/deploy is verified from Git, host release metadata and systemd rather
than from a CI receipt.

The release ships `plugins/dsh-rsi-wechat-status`, but production chat still
mounts only `harness/deepseek/chat.patch.yml` and `engineering.patch.yml`; the
bundle is installed in the isolated `rsi-ops` SDK profile, not mounted in owner
or group replies. `DEPLOYMENT.json` records `publication_recovery_implemented:
false`.

The owner engineering mode still loads read/write/edit/read_image/web_fetch plus
bash/working_directory; ordinary chat stays tool-free and media grants no owner
authority. web_search has no provider and stays disabled; the failed
tool-fs-search insertion was removed. Read-image is registered, not separately
exercised by the tool probe.

## Audit signal worth knowing

Run as the runtime user against `installation.json`, `audit` reports only
`SERVICES_NOT_PERSISTENT`, matching the install-time receipt. The same audit run
as root with the pilot venv instead reports
`INSTALLATION_PREREQUISITES_INCOMPLETE`: `db-keys.json`, `native-ui.json` and
`operations-state/config.json` are 0600 wechat-gui files that the uid check
rejects, and PyGObject/Pillow exist only in system python. That combination is
an invocation artifact, not a production regression.

## Unique next step

Treat publication recovery as the next task boundary: recover publication from
the frozen original sdk_completed response, reconciling actual Git/remote effects
before any retry. Preserve the original input, completed session and generated
output; do not rerun tools, resend, or merely raise a timeout. No automatic merge,
client restart or test send.

Penguin's fixed-model Benchmark/Formal Baseline remains unestablished. Raw chats,
native IDs, private traces, pictures and credentials stay outside Git.
