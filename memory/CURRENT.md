# Current checkpoint

## Delivered baseline

PR #16's delivery receipt supersedes its candidate checkpoint. Current, release
metadata and both resident reply workers are at main 22bb0c6b21de, with pinned
DeepSeek Harness and SCNET. The actual Channels cover entered the production
model and received one independently audited native group reply. Ordinary-photo
official-visible export and isolated recognition passed; a fresh ordinary-photo
automatic-reply turn remains unobserved. Do not replay old image requests.

## One WIP: owner tools and first native DSH plugin (PR #17)

A native confirmed-owner text generated this change in the isolated runtime
workspace. Its original SDK session has a completed turn, matching frozen input
and paired tool results, but the outer bridge did not persist completion or
publish the source before its bounded invocation expired. Session/work/call
locks were free. Preserve the original input, completed session and already-sent
fallback reply; do not regenerate or send another reply under a new ID.

Candidate loads engineering.patch.yml only in owner engineering mode. Actual
runtime request headers register read/write/edit/read_image/web_fetch plus the
existing bash/working_directory. Independent SCNET verification exercised exact
random-file reading, write/edit/readback, public fetch and loopback refusal.
The model also issued an extra pwd; strict no-bash prompt adherence is not
claimed. Production chat request headers omit tool definitions and contain no
tool calls. Ordinary chat stays tool-free; media does not grant owner authority.

web_search has no configured provider and remains disabled. The attempted
tool-fs-search insertion never registered in sdk-minimal and was removed;
filesystem search still uses the existing engineering shell. Do not describe
these unavailable tools as installed. Read-image is registered, not separately
exercised by this tool probe.

Original publication was reconciled without rerunning the model/tools or sending
another message. The work marker is now clear and the original call is completed;
the PR's recovery receipt is authoritative. Runtime-generated owner work is not
automatically merged, deployed or activated. Production stays at the delivered
baseline.

The owner requested several DSH plugins. `harness/DSH-PLUGINS.md` defines WeChat,
memory, tasks and evaluation boundaries; only `dsh-rsi-wechat-status` is implemented
as a native bundle. Its tarball was installed in an isolated SDK profile and the
configured SCNET model actually called `rsi_wechat_status`, returning a successful
native tool/result. Both production workers were fresh/idle on the current code,
with no pending/attention items; original records, configs and PIDs were unchanged.
The frozen unresolved-work fixture separately reports needs_review even with idle
chat. The package was not mounted in production replies and does not send or retry.
Keep the increment in the existing PR and verify CI for the combined actual head.

## Unique next step

Persist completed SDK output before the slower verification/publication phase,
so a wrapper timeout cannot strand completed work as running. Use this frozen
completed-session/publication interruption as the acceptance case; do not merely
increase a timeout or rerun the model/tools. No client restart or test send.

Penguin's fixed-model Benchmark/Formal Baseline remains unestablished. Raw chats,
native IDs, private traces, pictures and credentials stay outside Git.
