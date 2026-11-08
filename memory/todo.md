# Priorities

One active improvement at a time. Keep the denominator fixed; add discoveries
as candidates rather than silently expanding the active task.

1. **Recognize replies to the account's own group messages: one WIP.**
   PRs #8/#9 are delivered. The first natural response to the introduction was
   received but incorrectly classified quiet; the user says it should be answered.
   Preserve native turn adjacency across ACK/retry, prioritize it without @ or
   question marks, and recover only that identified unsent event after release.
   Keep prior caches/requests and the owner service unchanged. See CURRENT.md.
2. **Service persistence: awaiting production window.** Bundle/bootstrap and
   isolated transient→persistent→rollback transport paths are verified. Two rounds
   are complete; do not spend another round repeating those checks. Actual X,
   client and noVNC interruption needs a new appropriate maintenance window,
   possible phone availability and production login/layout acceptance. Preserve
   PR #1 and its exact candidates. No production unit was switched.
3. **Cancellation recovery: code released, official UI acceptance pending.**
   Qt/Openbox reproduces partial deletion and verifies restoration of owned and
   prior drafts while protecting foreign text and original attempt checkpoints.
   Official-client acceptance still needs a separately scoped unsent draft.
   Do not repeat live sends or manufacture another delay change.
4. **Penguin Formal Baseline.** Resolve one explicit test agent and fixed model,
   build/calibrate a versioned Benchmark with an independent evaluator and a
   held-out companion, then run one bounded candidate. No score yet exists.
5. **Soak and packaging.** Once ordinary startup works, collect sustained
   availability and recovery evidence; simplify install/upgrade/rollback around
   the actual release layout. Additional media and Mac support stay separate.
