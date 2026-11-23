# Priorities

One active improvement at a time. Keep the denominator fixed; add discoveries
as candidates rather than silently expanding the active task.

0. **M6 batches 1–2 accepted (deployed `6475450`).** Inline protocol,
   ledger-only settled receipts and auto-wake all live-accepted: the npm
   standalone CLI installed the managed app-server daemon, and a fresh
   message ran with no manual step (queue → turn in ~7 s, completion at
   42.2 s vs 107.2 s baseline, V2 sent, no notice row). Remaining: daemon
   survival across logoff/reboot folds into M1; optional warning triage for
   `already has an active writer`. Later M6 batches (Router/Worker,
   subscription, Spill/recall) stay design-gated per docs/ROADMAP.md.
0b. **M1 reboot window (prepared, deferred 2026-11-23).** Snapshot scripts
   and pre-checks are ready in var/local-setup; the daemon now starts from
   the receiver launcher (#160) and `Desktop-Control.ps1` provides an
   explicit pause/resume entry. In the window: owner reboots, scripts diff
   the snapshots, phone confirms login once, grade each item
   auto/one-manual-step/needs-fix. Also decouple the reply worker from
   `wechat-gui.target` so a trigger upgrade stops restarting the client.
1. **Photos and documents, fresh acceptance.** Ordinary photos work; follow
   the next slow-painting viewer (#132) and the next fresh Word file from native
   export to their original V2 reply. Grouped photo albums stay unsupported until
   a separate design exists. Failed originals stay failed; do not replay them.
2. **Delivery stages stay separate.** Queue receipt, visible user item, frozen
   completion and native send are distinct; report each from its own record.
3. **Dafeiyu sticker output (Issue #26).** Verify favourite-to-asset selection
   without sending, then bind it to one original V2 effect.
4. **Group and semantic memory.** Keep native identities and peer stores
   separate; no raw Codex mirror, automatic profiling or nickname authority.
5. **Service persistence (PR #1).** Isolated transient → persistent → rollback
   is verified. Switching production units interrupts X, the client and noVNC,
   so it waits for a scoped maintenance window with phone availability.
6. **Draft cancellation.** Released and reproduced under Qt/Openbox. Official
   client acceptance needs a separately scoped unsent draft.
7. **Penguin baseline.** Fix one test agent and model, build a versioned
   benchmark with an independent evaluator and held-out set, then run one
   bounded candidate. No score exists yet.
8. **Soak and packaging.** Collect sustained availability evidence. Watch the
   late-receipt notices from #124 for reply-queue delay. For local WSL installs,
   validate Task Scheduler logon and restart recovery in a separately
   authorized window.
