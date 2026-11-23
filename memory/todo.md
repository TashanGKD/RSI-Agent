# Priorities

One active improvement at a time. Keep the denominator fixed; add discoveries
as candidates rather than silently expanding the active task.

0. **M6 batches 1–2 (PR #152).** Review candidate: inline chat protocol,
   `--resume` wake on every desktop queue, settled successes stay ledger-only.
   Local Windows/Linux gates pass. Next: CI + review, then a scoped upgrade
   window to deploy and compare real-message timing before/after. Later M6
   batches (Router/Worker, subscription, Spill/recall) stay design-gated per
   docs/ROADMAP.md.
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
