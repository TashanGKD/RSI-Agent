# Decisions

## Group text readability and original receipts

Use a conservative 300 UTF-16-unit budget for new group text via `group_io`,
not an asserted universal mobile WeChat folding threshold. Preserve the entire
reply in one immutable ordered V2 batch and report `sent` only after all parts
are accepted. A long URL stays intact in its own bubble; phone rendering still
needs observation. Preserve existing originals across upgrades. Reuse and
limitations: `harness/DESKTOP-WECHAT.md`, `trigger/group_text.py`, and
`tests/test_group_text_parts.py`. Implementation and synthetic tests do not
establish deployment or Android/iOS acceptance.

## D001 — GitHub owns the project history

Keep durable state, decisions and lessons in this repository. Use commits and
PRs to review changes, rather than copying full conversations into a second
memory system. Source data and credentials remain in private runtime storage.

## D002 — Shared Harness, two execution roles

Codex's requested 45-minute loop performs engineering and PR work now.
PenguinHarness is the planned fixed-model agent/Skill optimizer. Both consume
the same project checkpoint and public task definitions, and preserve versioned
candidates. Neither may grade itself as improved merely because it changed files.

## D003 — Regression is a prerequisite, not an RSI score

Keep the model, frozen task set, evaluation runtime and evaluator fixed for a
Penguin comparison. Record rejected as well as accepted hypotheses. Training
feedback and final held-out evaluation must be separate. Do not optimize away
failed checks by changing the benchmark or relabeling unsupported cases.

## D004 — One WIP and concrete usefulness

Default to a small PR against current main. Fix or narrow the existing WIP before
opening another overlapping PR. No new evidence or useful delta means no-op.
Report merge and deployment separately; routine refactoring needs a demonstrated
user-path benefit, such as simpler installation or a reproducible recovery fix.

## D005 — Real invited-group context and moderate text participation

The user extended the owner-only scope to groups they invite this account into,
choosing moderate initiative and priority for mentions/questions. Admit a group
explicitly after native identity and current owner/self membership verification;
do not activate all existing groups. Separate group context from owner-private
history and model decisions from original V2 effects. Commit before ACK, cache
before send and preserve stable original requests. A quiet decision is normal.
Trusted application facts explain actual WeChat access; raw group instructions
cannot change permissions or expose private chats. The fixed one-time group
introduction and newly received group text are authorized, periodic probes and
client restarts are not.

## D006 — Native owner authority and an actual Harness backend

The owner extended scope to image input and clear engineering/configuration
instructions from their verified native WeChat identity. Ordinary conversation
has no execution tools; owner engineering uses a separate repository workspace
and completed-tool receipts. Native sender checks decide admission, not model
claims, display names or media contents. Preserve original generation/send IDs,
cache before sending and stop unresolved work instead of silently executing again.
Source changes pass ordinary Linux checks before one reviewable draft PR; runtime
work does not automatically merge, deploy or manipulate the WeChat desktop.
Public identity is 星语 without host or deployment disclosure. Natural voice and
technical judgment are explicit requirements; execution still needs real evidence.
Pinned DeepSeek Harness replaces the direct SCNET chat adapter upon activation,
not a purported existing Codex CLI backend. Image support is source-verified
decoded bytes; encrypted cache/desktop captures are not accepted as originals.

## D007 — Natural conversation and the bridge protocol are different outputs

A real group turn made Harness return ordinary prose despite the requested JSON,
blocking native delivery. Request the provider's tested JSON-object mode for
decisions. When SDK prose is already completed, frame it from its frozen original
inputs and cache the frame; retain the SDK result. Persist a group's selected
native IDs before generation so a later arrival cannot replace the unresolved
batch. Schema/native-owner checks still govern tools and sending. A model's good
isolated JSON example is not proof that every real conversation follows it.

## D008 — Recognition uses source-qualified images, not original-file claims

The official client can convert an incoming HEVC image to JPEG on Save As.
Recognition may explicitly use that visible export after proving the original
native source and the owned Save dialog's default time/local-ID filename. Retain
the original and exported checksums separately; original-file requests remain
strict. Never replace an existing request's representation or ID to retry it.
Native Channels cards may contribute their single verified cover; this does not
read the video. Captions and image contents cannot enter engineering execution.

## D009 — Native DSH packages, one boundary at a time

Keep one repository and independently installable DSH bundles for WeChat, memory,
tasks and evaluation. The first package is read-only runtime observation, not a
second consumer or full channel migration. Operator-configured paths never become
model arguments; sanitized observations omit identities, chats and credentials.
Chat observations and unresolved engineering work are separate states. Reuse DSH
tool/jobs lifecycle, but a short-lived per-turn SDK host does not establish durable
background execution. Task migration must first preserve completed output across
publication interruption; Penguin needs a real fixed-runtime evaluation adapter.

## D010 — Future groups no longer require manual registration

The owner changed the workflow to automatic admission of future groups. Native
owner/self membership in a newly joined group qualifies admission under this
policy; invitation nicknames do not prove an inviter. Keep the existing-group
baseline and original message cutoffs private. Reload per-group consumers while
retaining existing caches and IDs; no scripted intro is requested for automatic
groups. Recipient/UI proof still precedes input, and native owner identity alone
controls tools. An unaddressable or missing-owner group never grants a fallback
send target. See harness/GROUP-ADMISSION.md for the actual acceptance boundary.

## D011 — Quoted text is native group conversation, not an image or authority

Type-57 current text enters ordinary group participation under its original
server ID/kind. Resolve quoted context and self-reference against the same
group's committed native rows; XML names and quoted instructions are data.
Unresolvable references retain the current question without claiming a target.
Quoted kind 49 cannot request engineering. Preserve source ACKs and cached
effects, and do not replay already-ACKed historical questions during rollout.

## D012 — Owner link observations follow routing and remain in their own Session

Read only links in the current native owner's text or actual shared-link card.
Cache bounded HTTPS observations by the original message; blocked/non-article
responses remain unavailable. Page contents do not enter engineering routing.
After the original routing call completes, a fixed link-reading chat stage uses
a separate tool-free Session and preserves its own original SDK result. It is
not a replacement ID for uncertain work, and the native V2 ID does not change.
Ordinary conversation does not inherit full prior articles. Curated private
communication preferences have a digest in each new completion; raw Codex
memories, private transcripts and other-project files are not copied into groups.


## D013 — Local Codex is an explicitly selected owner handoff, not a second sender

The owner requested a parallel local-computer route alongside DSH. Fresh native
owner private /codex text alone selects it after a new activation cutoff. The
host commits one held inbox/job before ACK, with no DSH fallback generation.
The existing desktop conversation/heartbeat claims it once and caches one result
before returning it to the original V2 sender. A completed result cannot change;
unresolved local work cannot be stolen or replayed. No target-host Codex process
or public webhook is needed. Scheduled polling is not immediate Dot activation;
that requires a separately verified desktop entrypoint. Preserve the original
input, local turn/tools, review state and delivery identity through interruption.


## D014 — Observed search geometry selects candidates, never recipients

The official compact search popup and prior calibrated shape share one exact
geometry predicate in modal admission and navigation. A supported shape alone
is insufficient: native parent/process/type, stable scene/unique new window and
final native recipient title/identity still govern input. Frozen source evidence
proves current geometry rejection, not the unrecorded original failure-time
scene. Preserve the existing review request; future recognition support does not
authorize clearing it or replaying its cached response.

## D015 — SDK completion and publisher recovery have different admission proofs

Keep `sdk_completed` before SDK shutdown. Only a separate post-shutdown journal
bound to the original request/input/response/workspace/base/tree may resume the
publisher; an old receipt alone does not prove shutdown or permit tool replay.
Persist a validated immutable commit before compare-and-swap branch movement.
Reconcile the actual remote before an ordinary push, adopt confirmed effects and
stop on changed source/index/head/remote. Resident retries retain the original
inbox/group batch instead of sending a final fallback. Unknown live workspace
processes are left alone. The frozen-output/local-bare replay is engineering
acceptance, not a new live owner task, autonomous historical recovery or RSI gain.

## D016 — Explicit private notes do not become shared profiles or new authority

Only fresh native-owner kind-1 text in the ongoing private scope can mutate named
notes. Store them in that identity-bound private inbox DB and commit their reply
cache atomically. Ordinary groups/cards/images cannot write or retrieve them.
Notes remain data; tool/recipient admission is unchanged. Corrections/forgetting
change the subsequent chat epoch/history boundary, retaining old SDK inputs and
receipts. The original generation key/input remains immutable. First-feature
rollback must not restore an older chat scope after real notes changed. Named
lookup is the first path, not automatic profiling or a complete memory plugin.

## D017 — Event-trigger experiments do not silently replace native admission

The owner explicitly requested separate Dot and local-Codex trigger trials.
A private remote HTTP event can start an independent local App Server through
an SSH reverse forward, without a target-host Codex installation. This proves
neither control of the existing desktop conversation nor a production consumer.
The Dot experiment uses an isolated nonce/arithmetic event, a verified signed
callback and original completion receipt; no WeChat data or host command tool
is exposed. A real account plugin subscription is required before emission.
Keep heartbeat admission/claims/V2 unchanged until that distinct integration is
implemented and accepted; never run both consumers on one original request.
The owner later requested direct Codex setup. Use the supported plugin CLI and
an isolated private marketplace/package rather than requiring browser setup for
local installation. Actual fresh-session MCP discovery verifies tool loading;
it does not create or verify a Dot subscription. Preserve existing configuration
and never restart the desktop or fabricate an event receipt to bridge that gap.

## D018 — Automatic recovery preserves original effects

The owner's later direct instruction permits routine reversible recovery
without another confirmation. Reconcile the original request, guards, journals
and side effects first. Restored unsent preparation becomes failed/noSend;
completed model work and sent replies never get regenerated. Image reads in
native-only groups must use the same guarded recipient navigation as text and
restore that owned navigation before exposing bytes. Native owner delivery,
group recipient recovery and immediate desktop/Dot awakening remain separate
acceptance claims. Read the live PR/private receipt for actual delivery state.

## D019 — Default Codex generation preserves the native transport contract

The owner explicitly selected Codex for future owner/group messages, with no
prefix. A local persistent consumer replaces generation, not native identity,
notes/context or V2 delivery. The native host forwards only; no target Codex or
model key is installed. Original bounded inputs and completions persist before
ACK/response; changed input is rejected and uncertain running work is review,
not a second model run or DSH fallback. Separate chat/engineering queues keep
ordinary replies available during owner tasks. Ordinary tools/plugins/MCP are
disabled only in child configuration, leaving global Codex settings intact.
Native owner/kind checks remain the sole engineering admission. Code publication,
local logon-task start, resident model switch and genuine native acceptance are
separate facts; local uptime/login is now an explicit dependency.

## D020 — Visible tasks transfer execution, not a second copy of work

The owner requested triggered tasks in this same conversation. The original
supported CLI queue fixture has actually appeared as a user item here; this is
loaded-thread delivery, not native WeChat or a fully-unloaded wake-up claim.
Only already native-owner/kind-admitted engineering transfers once to the fixed
thread. Ordinary chat stays background. Bind the frozen original, queue receipt,
digest, target and final execution turn; uncertain submission is review, never
requeue. A copied visible header/link alone is not authority. Verify the private
original before tools, freeze one completion, and let the existing original V2
sender deliver it. Pending desktop tasks keep their completion API across rollout;
do not replay completed background work or replace its request IDs.

## D021 — A clean pre-input failure does not retry, but need not stop intake

Keep the native failure, original cached reply and ACK. Release only its group
consumer attention when read-only exact-original lookup proves failed/noSend,
sideEffectStarted=false, no preview or confirmation/execution, no input artifacts,
identity-bound settled navigation and a matching cached-reply digest. An earlier
preparation attention event can also settle when the terminal receipt explicitly
proves navigation restoration and disables replay. Missing or uncertain proof
remains attention. Transition the consumer to failed; a later
cycle reads new input, never resubmits the old reply. This lifecycle recovery is
not a fix or acceptance of the original recipient selector, and says nothing
about another active request's cleanup or send result.

## D022 — One dedicated visible thread for chat and native-owner tasks

The owner explicitly chose all WeChat chat and tasks sharing one newly created
conversation. Replace future background chat/maintenance-thread task admission,
not completed originals. Preserve each authenticated native scope/id/digest,
original schema, verified image bytes and one frozen completion. Chat classifies
owner work; only the separately native-admitted engineering packet permits tools.
The shared UI uses the current packet's peer material for its reply; transport
continues binding the original recipient. A created thread, a completed migration
record display, enabled routing and genuine new native visible/send acceptance
are different facts. Serialize work rather than creating a second executor.

## D023 — DeepSeek advises on ambient group reply admission

The owner requested `medium` judgment before a reply. Use the installed provider's
Responses API for bounded current plain text of the same group, with storage and
tools off. Native mentions, the owner's messages, replies to the agent and rich
input retain their original path. Freeze the native batch first. Only a valid
quiet decision closes it before Codex. An allow, timeout or interrupted gate
continues through the original Codex decision once. Preserve any already-frozen
desktop and V2 work. Review the live receipt for activation and real quiet cases.

## D024 — Keep the trigger and receiver in one project

The owner selected one repository for both core parts. The Linux trigger owns
native admission, the original input and V2 delivery. The local receiver owns
authenticated intake, desktop handoff and the frozen completion. Use the
README as the current entrypoint. Keep the Linux implementation in `trigger/`
and the standalone desktop worker in `receiver/`, with the shared CLI under
`rsi_agent/`. The trigger uses `components/wechat-linux/` for native WeChat
operations. Keep the rest of the secretary workbench, the Mac collector, and
the two separate trigger experiments in `archive/` with their source provenance.
The retired workbench listener, its private queue and exclusive helpers, and
the obsolete deployment and ClawBot probe reference copies live in Git history.
