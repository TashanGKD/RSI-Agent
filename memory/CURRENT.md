# Current checkpoint

Checked 2026-11-23. Memory is a checkpoint; verify the WSL distribution's
`/opt/rsi-agent/current` symlink, both reply services' working directories,
the Windows receiver task's release and the receiver's authenticated
`/health` before relying on it.

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

- Production moved on 2026-11-22 01:13 from the remote host to the local WSL
  distribution `RSI-WeChat-Main` (WeChat 4.1.13.26, same account). The remote
  host's reply services are stopped and kept as a cold standby. Both reply
  services and the Windows receiver task run release `6475450` (#152, #155)
  since the 2026-11-23 maintenance window. The owner unit was swapped with a
  scoped stop/start (client untouched); the desktop session later restarted
  and the client needed one phone-confirmed Log In. The task now uses
  `conhost --headless` with the five-minute restart timer (#148). Prior
  releases and unit backups are kept for rollback. Exact revisions, PIDs and
  backups are in the private operator receipt.
- The official client's built-in browser reaches the internet through a private
  systemd drop-in with the Windows proxy (2026-11-23); WeChat articles opened in
  the client can be copied out and read.
- M6 batches 1–2 merged as `a6a6abb`
  ([PR #152](https://github.com/TashanGKD/RSI-Agent/pull/152)): chat handoffs
  inline the read/complete/status ceremony with absolute paths and the original
  ID/digest, every desktop queue uses `--resume` to wake an unloaded
  conversation, and a settled success stays in the V2 ledger without a visible
  notice. Live acceptance on 2026-11-23 with a fresh owner message: the
  inlined protocol was used with no protocol/skill file reads, ID/digest
  verification unchanged, V2 receipt `sent`, and the settled success produced
  no notice row. Turn time 88.0 s vs the 11-22 baseline's 96.3 s for the same
  shape of request; queue-to-completion 414.8 s vs 107.2 s because the wake
  did not fire (below).
- Wake limitation found live: the Store CLI has no complete local package, so
  `app-server daemon start`/`bootstrap` and `remote-control start` all refuse,
  and `queue --resume` warns `start a local daemon or specify a server with
  --remote`. The queued message waited until a user-authorized
  `send_message_to_thread` nudge loaded the conversation; the queued item was
  then processed normally with no resubmission. This matches the documented
  historical boundary in harness/LOCAL-CODEX.md (direct activation of an
  unloaded conversation was never accepted). Auto-wake needs either a packaged
  standalone CLI daemon or an accepted desktop-side activation path; recorded
  as the remaining M6 batch-2 gap.
- Link reading was broken for every link after the WSL move: the local DNS is
  a fake-IP resolver that answers `198.18.x.x`, which the public-destination
  check refused (`PUBLIC_PAGE_UNAVAILABLE`). Names that resolve only to
  `198.18.0.0/15` now tunnel by hostname through the loopback proxy in
  `RSI_LINK_PROXY`, set by a drop-in on both reply services (#157).
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
- The evening astronomy digest sends every item to its two groups, with an
  optional verified "今日 Top 速览" image as part 0 (#146, #147). The first
  image issue went out on 2026-11-22 with matching native receipts.
- Favourite stickers are sent natively (type 47) through the public
  `send_sticker` action (#153). The favourite order in `emoticon.db` locates
  the cell, a private 68×68 reference crop must match it pixel for pixel, and
  the receipt is one new self type-47 message with the same MD5 and status 2.
  A live send to the owner chat matched. The six informal groups now use
  sticker mode `send` with an MD5 for each label (3-hour gap); the formal
  observatory group has no stickers. A fresh group sticker has not been
  observed yet. `open_chat` now uses the owned navigation and was verified live.

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
| Group replies not sent after the WSL move (`RECIPIENT_NOT_VISIBLE`) | The local client draws the search section labels differently | Fixed and live (#143, #144) |
| Replies sent but recorded `unknown`, blocking the queue | The post-click native proof raised while WeChat was writing its database, and nothing re-read the receipt | Fixed and live (#145): the proof is re-read, and an `unknown` original is reconciled from native evidence without another click. The exact exception is now recorded as `causeType`/`lastProofError` |
| Receiver down for 3.5 h (11-22 16:51–20:28) | Its console was hosted by Windows Terminal, which sent Ctrl+C on exit; the task's restart setting covers only launch failures; an orphan ssh forward then held the return port | Fixed and live (#148); a forced exit was restarted by the timer in 16 s |
| First send after a client restart failed (`UNSUPPORTED_LAYOUT`) | The main window reopened at 903×667, which the resize helper ignored | Fixed and live (#149) |
| Group inputs expired while a reply turn was interrupted or waiting | An owner message typed into a reply thread interrupts the running WeChat turn; a model error ends one at once; the reply thread also waited on maintenance work | Interrupted or failed requests not yet read are requeued once (#150, live); reply threads must end the turn after handing work to maintenance |
| Reply threads idle after a Codex Desktop restart | Reloaded conversations stay `notLoaded` and do not drain their queue; the receiver cannot wake them without the private desktop IPC | Open: wake each reply thread by hand after a desktop update |
| New installs stopped at the WeChat download | Tencent replaced the package at the same URL on 2026-11-20 | The installer reuses a verified 4.1.13.26 copy from `RSI-WeChat-Setup/packages/<sha256>`; newer builds need recalibration |
| Group stickers never sent; `open_chat` failed with `SEARCH_RESULTS_NOT_SUPPORTED` | Groups only recorded sticker intents, and `open_chat` still used the old popup search | Fixed and live (#153); File Transfer is not found by the owned search, and animated favourite thumbnails cannot be pixel-matched |

Before the image fixes, ordinary group photos succeeded about half the time
since 11-17 (covers and quoted images all succeeded). Every failure kept its
original request, `noSend` result and private preview; none is replayed.
