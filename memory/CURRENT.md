# Current checkpoint

Checked 2026-11-20. Memory is a checkpoint; verify the host's
`/var/lib/rsi-agent/release.json`, the `current` symlink, both service
working directories and the local receiver's authenticated `/health` before
relying on it.

## Shape

One repository holds the Linux WeChat trigger and the local Codex receiver.
The trigger persists native messages before ACK, binds sender, peer, images,
documents and links to the original message, and hands one frozen request to
the receiver over the authenticated SSH loopback. The receiver queues it once
into a fixed visible Codex conversation: owner-private chat uses the owner
thread, friend and group chat use the friend/group thread, and every
authenticated engineering task goes to the maintenance thread. Reply threads
hand any long work typed into them to maintenance. The executing turn reads the
authenticated packet, freezes one completion and returns it; the trigger sends
it through the original V2 request and the receiver reports that receipt.
Local Codex is the only reply backend. DSH and the `/codex` prefix are retired;
their old inputs and receipts stay private for audit.

## Verified live

- Release `6f350a5` (#122) runs both remote services. The local receiver runs
  the engineering-routing release recorded in the private operator receipt.
- Group, friend and owner text replies complete end to end. The latest fresh
  group input (2026-11-19) went native intake → same friend/group Codex turn →
  V2 `sent` once.
- Expired group work no longer stays pending. Ordinary inputs older than
  15 minutes become `recycled`; a frozen Codex request in that batch, or a
  receiver `desktop_queued` job without a turn, settles as `not_sent` with
  `GROUP_INPUT_EXPIRED`. A stuck job no longer blocks newer group messages.
- WeChat Channels covers and quoted images read reliably.
- The evening astronomy digest sends every item to its three groups; 11-16
  through 11-19 are fully delivered.

## Recurring problems

Local WSL onboarding/persistence is the open #124 code candidate, not an activated
installation. `setup pair` stages one new private receiver/backend pair without
replacing old state; `setup prepare-capture` validates the reviewed client and
prepares only its own-child script. `setup check` separates configuration,
authorization prerequisites, sender and receiver status; delivery remains unverified.
`services stage --profile wsl`, `audit --profile wsl` and the Windows logon task
cover the local desktop startup path. Checks include isolated nested Xephyr,
Windows startup/pairing, secret redaction and preservation of existing work.
Local account authorization and the confirmed owner's native identity are now
verified after one scoped client restart. The debugger detached and the client
is ordinary again. The receiver delivered fresh owner input into its dedicated
Codex conversation and accepted one frozen completion per original. The first
two V2 replies were proven failed/noSend (navigation position drift, then an
empty-editor voice hover hint); both originals remain settled and are not replayed.
Moving the pointer away after an empty draft read removes that hint without
relaxing draft protection; the candidate passes the actual empty-editor check.
An additional fresh original stopped before sending because GTK inherited the
outer WSLg Wayland clipboard. Binding the helper's GTK backend, display and
Xauthority to the configured X11 desktop passed an actual Chinese draft write,
copy and owned cleanup comparison. Its failed original is retained.
One fresh post-fix owner message completed native intake → the dedicated visible
Codex turn → its original V2 `sent`, with exact native text, one Send click and
settled draft/navigation cleanup. The owner confirmed the reply was visible on
the main account's phone. That acceptance used retained `6a0ad63`; later runtime
revisions must be read from the private local receipt. This accepts only this
private text pair. Task Scheduler logon, systemd activation, reboot recovery,
group/attachment paths and sustained availability remain unverified locally.

The current #124 candidate also reconciles proven private pre-input failures
without resending, scopes accepted cleanup to its original job, preserves cleanup
status in desktop receipts, and journals late receipt notices to the original
thread without a new generation. Native account/client/layout observations now
qualify the receiver-only health result. The WSL bundle can explicitly include
the confirmed owner coordinator and interpreter; the launcher refuses a missing
owner worker. Inner X idle blanking is disabled for new displays and reset under
the native guard for existing ones. Host sleep policy is unchanged. Isolated
regression and startup checks are separate from logon/reboot/screen-off acceptance.

| Problem | Cause found | State |
| --- | --- | --- |
| Group messages stuck pending or late | A `desktop_queued` job without a turn held the group inbox; expiry did not settle it | Fixed and live (#117–#119); fresh delivery verified |
| Ordinary group photo not received | 1) images with text add a Translate button, so Save moved and the toolbar check stopped; 2) a delayed image eleven messages up was beyond the four-step history scroll | Both fixed in the cleanup PR; needs a fresh ordinary photo after deploy |
| One failed photo blocked every reply for up to an hour | The failed export left the official viewer open, so cleanup stayed unproven and the job sat in `needs_attention`; nothing advanced it again | Fixed and live (#122): the executor closes only its own viewer, records `failed/noSend`, and a waiting reply settles the blocking image first; needs a fresh failing photo to observe |
| Replies late while a reply thread ran a long task | Owner and group engineering, and long work typed by hand, ran in the reply threads | Engineering routes to the maintenance thread; reply threads hand off long work |
| Group PDF read only by file name (`PDF_CACHE_UNAVAILABLE`) | The 12.5 MB file was downloaded, but the native file budget was 10 MB and every refusal was reported as a cache miss | Fixed and live (#125); oversize reports `PDF_TOO_LARGE`. Fresh delivery verified 2026-11-21: a new 12.54 MB, 25-page group PDF was bound with matching SHA-256, read in the group reply turn, and the same request's V2 receipt is `sent` |
| Word files ignored | The trigger admitted only `.pdf`, `.md` and `.txt` file messages | `.docx` admitted and live (#126) with the same native proof and 25 MB budget; read with `receiver/word_text.py`. An already downloaded group original read correctly on the host; needs a fresh Word message for end-to-end delivery |
| Evening digest reported failure after sending | The local wait for the remote batch was fixed at 175 s; 18 parts take longer | Fixed in the cleanup PR; the remote wait scales with the batch |
| Xiaohongshu notes | Public pages require login | Card metadata only; not fixable without an account |
| Sender SSH dropped | Host-side outage | Recovered by the host; no code change |

Before the image fixes, ordinary group photos succeeded about half the time
since 11-17 (covers and quoted images all succeeded). Every failure kept its
original request, `noSend` result and private preview; none is replayed.
