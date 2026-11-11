# Local Codex receiver

The receiver is one of the two core parts of [RSI Agent](../README.md). The
Linux trigger admits native WeChat input and submits the frozen packet. This
computer receives it, holds its original state and hands it to the dedicated
Codex conversation. The original V2 queue delivers eligible replies.

## Current configuration and operation

Run `python -B -m receiver.codex_worker --config /private/local-codex.json`
on the computer with the signed-in Codex user. The old `rsi_agent.codex_worker`
module command still forwards to the receiver. For a standalone installation,
copy [`receiver/codex_worker.py`](../receiver/codex_worker.py) as the worker script.
The installed per-user logon task
keeps it running in the background, independently of the maintenance heartbeat.
The computer must be awake and the Codex user signed in.

Set `desktop_thread_id` to the dedicated conversation and
`desktop_all_requests` to true for both chat and admitted engineering. The
worker binds HTTP on loopback and maintains an SSH reverse tunnel for the Linux
trigger. Keep the token, SSH identity, local paths, target, and queue state in
private configuration. The native host needs the authenticated loopback
connection. The Codex process runs on this computer.

1. The trigger submits the frozen original to authenticated `POST /requests`.
   The receiver records the ID and digest before it can claim the job. A repeat
   with the same input returns the original state; changed input is rejected.
2. The receiver records `desktop_submitting` before `codex queue` and saves the
   original queue-message ID in `desktop_queued`. If submission is uncertain,
   inspect the original queue and conversation records in review.
3. The dedicated conversation verifies the original request, its native scope
   and bound images or PDFs through [the desktop protocol](DESKTOP-WECHAT.md). Only
   the native-owner gate can admit an engineering task. The shared conversation
   uses the current packet's peer context.
4. Authenticated `POST /desktop-completions` saves the frozen result. The
   trigger gets that result through the original `POST /requests` and, when a
   reply is needed, records the original V2 delivery receipt.

Authenticated `GET /health` reports readiness, state counts, source version and
target configuration. On Windows, when the configured Microsoft Store Codex
file disappears during an update, the receiver looks up the same registered
Store package for the signed-in user. It can resume on the replacement
executable without a restart. While the replacement is unavailable,
`codex_executable_present` and `ready` are false and accepted originals stay
queued. For a moved standalone executable, verify the new explicit path and
restart with the same private state. Check the installed worker and the active
Linux release in the live delivery receipt. `POST /drain` stops
new claims before shutdown. Check native V2 state and local queued, running and
review work before an upgrade. Retain each original ID, input, completion and
receipt across a restart or rollback.

## Historical route: engineering in the maintenance conversation

The earlier deployment sent admitted engineering to the existing maintenance
conversation while ordinary chat used peer-isolated background turns. An
interface fixture reached a loaded conversation after its active turn finished.
Direct activation of a fully unloaded conversation was not verified. The
dedicated conversation above now handles new chat and engineering.

## Historical prefix handoff experiment

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

## Historical heartbeat consumer boundary

The first consumer used the desktop heartbeat to check one queued prefix request
every 30 minutes. Today the local worker and dedicated conversation handle new
chat and tasks; the maintenance heartbeat only audits them.
The local bundled CLI's documented `app-server proxy`/daemon version probes fail
to connect to the desktop control socket (Windows error 10050). Only the probe's
own process was stopped. This does not prove that every possible desktop entry
point is unavailable. No private IPC/authentication bypass or target-host CLI is
used. Direct event activation remains a separate, unaccepted experiment.

Official protocol: [App Server](https://learn.chatgpt.com/docs/app-server) supports
initialize → thread/resume → turn/start, with turn/completed as the completion
evidence. Its existence alone does not prove a connection to the running desktop.

### Private activation and original work

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
The original input stays pending while local Codex is offline or uncertain.

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

### Historical heartbeat worker

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
task remains attached to its original consumer. Pending cached replies can
still use their original sender. Keep this release available to inspect/complete
held records if older code is selected. Client/X/noVNC remains unchanged.
