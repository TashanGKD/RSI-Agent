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

| Problem | Cause found | State |
| --- | --- | --- |
| Group messages stuck pending or late | A `desktop_queued` job without a turn held the group inbox; expiry did not settle it | Fixed and live (#117–#119); fresh delivery verified |
| Ordinary group photo not received | 1) images with text add a Translate button, so Save moved and the toolbar check stopped; 2) a delayed image eleven messages up was beyond the four-step history scroll | Both fixed in the cleanup PR; needs a fresh ordinary photo after deploy |
| One failed photo blocked every reply for up to an hour | The failed export left the official viewer open, so cleanup stayed unproven and the job sat in `needs_attention`; nothing advanced it again | Fixed and live (#122): the executor closes only its own viewer, records `failed/noSend`, and a waiting reply settles the blocking image first; needs a fresh failing photo to observe |
| Replies late while a reply thread ran a long task | Owner and group engineering, and long work typed by hand, ran in the reply threads | Engineering routes to the maintenance thread; reply threads hand off long work |
| Evening digest reported failure after sending | The local wait for the remote batch was fixed at 175 s; 18 parts take longer | Fixed in the cleanup PR; the remote wait scales with the batch |
| Xiaohongshu notes | Public pages require login | Card metadata only; not fixable without an account |
| Sender SSH dropped | Host-side outage | Recovered by the host; no code change |

Before the image fixes, ordinary group photos succeeded about half the time
since 11-17 (covers and quoted images all succeeded). Every failure kept its
original request, `noSend` result and private preview; none is replayed.
