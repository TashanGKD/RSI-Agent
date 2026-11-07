# Priorities

One active improvement at a time. Keep the denominator fixed; add discoveries
as candidates rather than silently expanding the active task.

1. **PR #1: runtime audit and PR loop.** Implementation, 443 checks, real-host
   audit, shared Skill, memory and initial CI are complete. Review the current
   PR head and its final CI; merge and production release remain separate work.
2. **Service persistence and layout recovery.** The authorized ordinary restart,
   cached login and original-message readback are complete; TracerPid is 0.
   Prepare persistent service definitions and rollback, then verify activation
   in an appropriate maintenance window. The manual layout restoration is not
   automatic recovery. Do not repeat the send test.
3. **Cancellation recovery.** Reproduce the partial-clear failure using an owned
   disposable draft in an isolated desktop. Preserve payload and terminal
   checkpoints; prove cancellation and restoration without a second send.
4. **Penguin Formal Baseline.** Resolve one explicit test agent and fixed model,
   build/calibrate a versioned Benchmark with an independent evaluator and a
   held-out companion, then run one bounded candidate. No score yet exists.
5. **Soak and packaging.** Once ordinary startup works, collect sustained
   availability and recovery evidence; simplify install/upgrade/rollback around
   the actual release layout. Additional media and Mac support stay separate.
