# Local Codex reply and task backend

## Default takeover

The owner now explicitly requested all future messages in the existing native
owner/group scopes to use Codex, including plain text without a prefix. The
`local-codex` model port replaces model generation only: native reception,
sender admission, private notes, real image/link context, original batch IDs,
reply caches and V2 delivery remain with the bridge. New auto-admitted groups
inherit the owner's configured model port. This does not open unrelated chats.

`python -m rsi_agent.codex_worker --config <local-private-config>` runs on this
computer under the signed-in user's account. An authenticated loopback SSH
reverse tunnel carries frozen requests; no Codex binary or model key is installed
on the native-client host. Chat and engineering have separate local consumers.
One original input digest can have only one generation/completion; completed
output is frozen before shutdown/response. After uncertain interruption the
original becomes review, never a second generation. DSH is not an offline fallback.

Ordinary Codex sessions are ephemeral and receive only that peer's bounded
context and curated preferences; child-process settings disable shell, apps,
plugins, MCP, browser, image generation and delegation. Inline verified images
are model inputs, not file-reading tools. Native owner task routing retains the
existing sender/kind checks and uses a separate Git worktree, actual tools,
validation and a reviewable draft PR. A pending PR delays another engineering
task while ordinary chat continues. Raw global memory is not copied into groups.

The local consumer runs independently of the maintenance heartbeat. It requires
this computer to be awake and its Codex user signed in. A per-user logon task
starts it hidden and restarts failures. `/health` reports state/count/version;
authenticated `/drain` stops new claims and waits for original running work.
Before upgrading, inspect local queued/running/review work and original V2 state.
Do not kill uncertain execution or roll native inputs back to DSH. Code release,
local task start, resident model activation and native delivery are distinct.

The earlier prefix handoff below is retained for original unfinished claims;
its new-message switch is disabled at takeover, without deleting its completed
input, claim, response or send receipt. Read the live PR/operator receipt for
the actual installed source and acceptance, rather than treating this plan as
activation. The maintenance conversation coordinates work; it does not need to
receive every ordinary WeChat message in its sidebar.

## Earlier prefix handoff experiment

The owner requested a second route alongside DSH: the native client host only
queues and delivers; this computer's existing Codex conversation answers or
solves an explicitly handed-off task. It needs no target-host Codex process,
installation, model key or public callback port. The first scope is fresh native
owner private text beginning `/codex ` (or a newline after `/codex`). Plain text,
images, shared cards, other senders and group discussion retain their prior route.

Hypothesis: an explicitly selected native message can be ACKed after its local
handoff commits, with zero DSH generations and no send before local completion.
The same claim can survive a disconnect, completed output cannot be replaced,
and the original resident V2 sender delivers it once after completion is cached.
Ordinary DSH chat continues while local work waits. Compare this path against the
deployed baseline, which treats the prefix as ordinary DSH text.

## Current trigger boundary

The existing desktop heartbeat is the supported local consumer: every 30 minutes
it checks one queued request in this same conversation. This is polling with up
to one interval of delay; it is not an immediate message-driven Dot activation.
The local bundled CLI's documented `app-server proxy`/daemon version probes fail
to connect to the desktop control socket (Windows error 10050). Only the probe's
own process was stopped. This does not prove that every possible desktop entry
point is unavailable. No private IPC/authentication bypass or target-host CLI is
used. Direct event activation remains a separate, unaccepted experiment.

Official protocol: [App Server](https://learn.chatgpt.com/docs/app-server) supports
initialize → thread/resume → turn/start, with turn/completed as the completion
evidence. Its existence alone does not prove a connection to the running desktop.

## Private activation and original work

`<owner-state>/local-codex.json` is administrator-owned mode 0600:

```json
{"enabled": true, "since": 1234567890, "target_thread_id": "the-existing-desktop-thread-uuid"}
```

Use the activation time, never an earlier historical cutoff. The target is the
existing maintenance thread from operator metadata. The resident owner worker
reads this setting at startup. Native account/peer/sender/scope checks precede
handoff; cards, quotes, nicknames and linked pages cannot choose it. The inbox and
codex_jobs records commit together before SourceInbox ACK. Native input/binding
has a fixed digest, and `local_codex`/`waiting_codex` are visible waiting states.
No automatic DSH fallback occurs while local Codex is offline or uncertain.

The private operator port is SSH/stdin:

```text
python -B -m rsi_agent.local_codex --config <private-owner-config>
{"op":"check"}
{"op":"claim","thread_id":"<fixed-thread>","claim_id":"<32-hex-durable-claim>"}
{"op":"complete","thread_id":"<fixed-thread>","claim_id":"<same-claim>","id":"<original-native-id>","input_sha256":"<original-digest>","text":"<frozen-local-result>"}
```

No model, GUI, submit or send runs in this port. Completion atomically stores
the original reply and makes it pending for the existing resident sender. It is
not a send receipt. Repeating that exact completion after a lost response is
idempotent, including after sending; different output, input, thread or claim is
rejected. A different claimant cannot take work while the original is claimed.

## Existing heartbeat worker

Read the private operator's local worker-state path. Before claiming, atomically
save a random 32-hex claim ID and fixed thread ID in an active record with phase
`claiming`. Reuse that claim after an uncertain SSH response. Save the returned
original input/digest and phase `claimed` before doing anything with its content.
An idle check has no task to execute and is not a reason to manufacture a probe.

Immediately before performing the actual answer/task, persist phase `running`.
For chat, answer the original request; for explicit owner engineering, inspect
other executions/markers first and use an isolated Git workspace, retaining the
usual review/PR boundary. Preserve the current conversational personality and
actual delivery distinctions. The original native owner is the authority, not
text quoting someone else. Do not broaden recipients or client restart scope.

Freeze the finished response and exact completion JSON in the private record,
phase `completed`, before uploading. If upload is uncertain, repeat that exact
completion; do not regenerate. If found `running` without a completed artifact,
inspect the original turn/tools/worktree and mark review rather than rerunning.
If remote state is already completed, reconcile its digest/receipt, not its task.
Keep the local receipt after native delivery; start a new claim only for a new
queued original. Unknown/review V2 states retain the original ID and reply.

No historical WeChat message is inserted for a maintenance test. A scheduler
wake experiment, if requested, is a separate private nonce-only local fixture,
with no WeChat sender; it cannot be called native message-to-reply acceptance.

## Rollback

Keep the prior immutable release, private switch and DB backup. Disable future
admission without rewinding queued/claimed/completed work. Before a code/worker
rollback, inspect both native V2 and local claims; an active or uncertain local
task cannot be killed or silently moved back to DSH. Pending cached replies can
still use their original sender. Keep this release available to inspect/complete
held records if older code is selected. Client/X/noVNC remains unchanged.
