# Current checkpoint

Checked 2026-11-21. Memory is a checkpoint; verify the host's
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

- Release `d59e490` (#124, #131, #132 on top of the Word and PDF work) runs both
  remote services. The local receiver runs the same commit from a full release
  directory as `python -m receiver.codex_worker`; a lone copied `codex_worker.py`
  is no longer a valid install. Exact revisions, PIDs and backups are in the
  private operator receipt.
- The receiver's `/health` now separates `ready` (receiver only) from
  `pipeline_ready`, which also needs a fresh owner-worker heartbeat with native
  account, client and layout checks. After deploy all three checks were true.
- Group, friend and owner text replies complete end to end. Ordinary group
  photos, Channels covers and quoted images have reached the friend/group turn
  and been sent repeatedly since 11-20. PDFs up to 25 MB are verified end to end
  with a fresh group original; Word `.docx` is live but still needs a fresh one.
- Expired group work no longer stays pending. Ordinary inputs older than
  15 minutes become `recycled`; a frozen Codex request in that batch, or a
  receiver `desktop_queued` job without a turn, settles as `not_sent` with
  `GROUP_INPUT_EXPIRED`. Expiries fell from 9 (11-19) and 12 (11-20) to 2 (11-21)
  after engineering moved to the maintenance thread.
- The evening astronomy digest sends every item to its three groups.

## Recurring problems

Local WSL onboarding/persistence (#124) is merged and its shared runtime
changes are deployed: proven private pre-input failures settle without resending,
accepted cleanup stays scoped to its original job, receipts keep
`cleanup_pending`, and a receipt arriving more than 18 s after completion queues
one read-only 微信送达更新 item into the original reply thread. Watch that these
notices do not delay new WeChat input. On the owner's own Windows/WSL machine,
one fresh private message completed intake → dedicated Codex turn → V2 `sent`,
confirmed on the phone. Task Scheduler logon, reboot recovery, group/attachment
paths and sustained availability remain unverified for local installs.

| Problem | Cause found | State |
| --- | --- | --- |
| Group messages stuck pending or late | A `desktop_queued` job without a turn held the group inbox; expiry did not settle it | Fixed and live (#117–#119); fresh delivery verified |
| Ordinary group photo not received | 1) images with text add a Translate button, so Save moved and the toolbar check stopped; 2) a delayed image eleven messages up was beyond the four-step history scroll | Both fixed and live (#121); fresh photos verified and sent since 11-20 |
| Photo burst failed (11-21 20:15) | 1) the viewer had not finished painting after the 0.45 s recapture budget, so the toolbar crop still showed the chat; 2) the next photos of the burst had no stable location, consistent with a grouped album | 1) Recapture budget raised to about 2.25 s, capture-only (#132, live); needs a fresh slow viewer to observe. 2) Grouped albums remain unsupported |
| One failed photo blocked every reply for up to an hour | The failed export left the official viewer open, so cleanup stayed unproven and the job sat in `needs_attention`; nothing advanced it again | Fixed and live (#122): the executor closes only its own viewer, records `failed/noSend`, and a waiting reply settles the blocking image first; needs a fresh failing photo to observe |
| Replies late while a reply thread ran a long task | Owner and group engineering, and long work typed by hand, ran in the reply threads | Engineering routes to the maintenance thread; reply threads hand off long work |
| Group PDF read only by file name (`PDF_CACHE_UNAVAILABLE`) | The 12.5 MB file was downloaded, but the native file budget was 10 MB and every refusal was reported as a cache miss | Fixed and live (#125); oversize reports `PDF_TOO_LARGE`. Fresh delivery verified 2026-11-21: a new 12.54 MB, 25-page group PDF was bound with matching SHA-256, read in the group reply turn, and the same request's V2 receipt is `sent` |
| Word files ignored | The trigger admitted only `.pdf`, `.md` and `.txt` file messages | `.docx` admitted and live (#126) with the same native proof and 25 MB budget; read with `receiver/word_text.py`. An already downloaded group original read correctly on the host; needs a fresh Word message for end-to-end delivery |
| Windows startup tests failed under a Chinese checkout path | Generated test scripts had no BOM, so Windows PowerShell 5.1 read them as ANSI | Fixed (#131); every repository `.ps1` must be ASCII or BOM-marked |
| Evening digest reported failure after sending | The local wait for the remote batch was fixed at 175 s; 18 parts take longer | Fixed in the cleanup PR; the remote wait scales with the batch |
| Xiaohongshu notes | Public pages require login | Card metadata only; not fixable without an account |
| Sender SSH dropped | Host-side outage | Recovered by the host; no code change |

Before the image fixes, ordinary group photos succeeded about half the time
since 11-17 (covers and quoted images all succeeded). Every failure kept its
original request, `noSend` result and private preview; none is replayed.
