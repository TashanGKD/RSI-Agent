# Priorities

One active improvement at a time. Keep the denominator fixed; add discoveries
as candidates rather than silently expanding the active task.

1. **PR #1: one reviewable WIP.** Runtime audit, shared Skill and memory are
   implemented; the service candidate below stays in this same PR. Check its
   actual head and final remote CI. Merge and production release are separate.
2. **Service persistence: awaiting production window.** Bundle/bootstrap and
   isolated transient→persistent→rollback transport paths are verified. Two rounds
   are complete; do not spend another round repeating those checks. Actual X,
   client and noVNC interruption needs a new appropriate maintenance window,
   possible phone availability and production login/layout acceptance. Preserve
   PR #1 and its exact candidates. No production unit was switched.
3. **Next independent task: cancellation recovery.** Reproduce the partial-clear failure using an owned
   disposable draft in an isolated desktop. Preserve payload and terminal
   checkpoints; prove cancellation and restoration without a second send.
4. **Penguin Formal Baseline.** Resolve one explicit test agent and fixed model,
   build/calibrate a versioned Benchmark with an independent evaluator and a
   held-out companion, then run one bounded candidate. No score yet exists.
5. **Soak and packaging.** Once ordinary startup works, collect sustained
   availability and recovery evidence; simplify install/upgrade/rollback around
   the actual release layout. Additional media and Mac support stay separate.
