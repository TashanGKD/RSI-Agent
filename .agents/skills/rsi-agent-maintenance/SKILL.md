---
name: rsi-agent-maintenance
description: Improve RSI Agent usability through a bounded runtime check, one reproducible engineering change, shared project memory and a reviewable GitHub PR. Use for this repository's recurring maintenance loop.
---

# RSI Agent maintenance

Find the repository root with Git. Read `AGENTS.md`, `memory/CURRENT.md`,
`memory/todo.md`, `memory/decisions.md` and the current PR before selecting work.
Resolve disagreement against current source, the running installation and the
user's latest instruction. Keep a single active problem and its acceptance path.

Each round should improve a user's ability to install, diagnose, operate,
recover or maintain the product. Start with the highest-value reproducible
failure. Write the hypothesis and what observable result would disprove it.
Use the smallest suitable check during development. Run the relevant complete
gate once the change is concrete; use `harness/README.md` for the two existing
evaluation entrypoints. Preserve a baseline and candidate comparison.

For a live installation, first inspect it without input. `doctor` checks
dependencies; `audit` checks the actual visible client, traced process and
service persistence. A successful structural audit is still not a send test.
Keep authenticated configuration on the host. Never copy keys, raw messages or
full desktop images into memory or a PR. Do not repeat the one-shot live send.

Create or update one PR against current main. Include the trigger, resulting
behavior, hypothesis, baseline/candidate evidence, limitations and rollback.
Verify remote CI for the actual head. Keep an existing PR as the WIP instead
of opening overlapping ones. Merge and deploy status must be explicit; do not
describe an open PR as released. Do not expand a live operation's authorization.

Update the smallest existing project-memory entry when there is a durable
delta. Git history and PRs retain the history; do not append repeated timestamps
or duplicate progress logs. Preserve rejected hypotheses and unresolved failures
when they change the next decision. No material delta means no commit or PR.

If a local detail is stuck, move through the user path, cross-module workflow,
architecture and external alternatives while keeping the same user outcome.
Spend at most two rounds on one stalled capability before recording its specific
blocker and choosing an independent item. Every four rounds review real user
outcomes; if fewer than two paths improved, retune the loop. Test counts, tidy
registries, status documents and scheduled execution alone are not improvement.

For PenguinHarness integration, read `harness/PENGUIN.md`. Keep regression
success, useful engineering progress, fixed-model agent improvement and
improvement of the optimizer itself as distinct claims. Do not invent a
published Benchmark, a Formal Baseline, model credentials or evaluation scores.
