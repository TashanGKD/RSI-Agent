# PenguinHarness integration

Reference: [PenguinHarness](https://github.com/Prism-Shadow/penguin-harness) at the
exact commit in `PENGUIN.lock.json`. Current upstream describes a fixed model
with versioned prompts, Skills, tools and hooks. The default optimizer requires a
published, frozen Benchmark, a complete Formal Baseline, fixed evaluation runtime
and an independent evaluator before accepting a candidate.

## Integration path

```text
real failure → memory/todo → hypothesis → versioned candidate
     ↑                                     ↓
retained lessons ← PR and decision ← fixed checks / evaluator
```

1. **RSI loop now.** The two reply conversations use the
   [learning skill](../.agents/skills/rsi-wechat-learn/SKILL.md) after a verified
   capability change. Maintenance checks the reported evidence and retains the
   reusable method in the relevant code, skill, or private asset index. This
   loop runs on real cases. Formal evaluation is a separate stage below.
2. **Agent State adapter.** Once an isolated Penguin Project is selected, put the
   role in the test Agent's `agent_state/AGENTS.md` and copy the canonical
   `.agents/skills/rsi-agent-maintenance/` into its `agent_state/skills/`. Give it
   an isolated Git worktree as its workspace. Do not install a second WeChat
   sender or import production account data into that Project. Use Penguin's
   own CLI for its private provider configuration.
3. **Formal evaluation.** Build and calibrate a package with public tasks covering
   dependency-versus-runtime diagnosis, interrupted-request handling, reproducible
   repair and correct PR handoff. Pin the code fixtures, model/provider/thinking
   settings and case matrix. Keep evaluator rubrics and held-out cases outside
   the optimizer's memory/workspace. Do not publish a draft as a frozen Benchmark.
4. **One initial candidate.** Start with the default trial/reflect/improve loop.
   Optimize the test Agent's instructions/Skill using public failure traces.
   Compare on the same runtime; keep the reference on failure or incomplete
   evaluation. Preserve a rejected hypothesis for later diagnosis. A source-code
   fix is reviewed and measured as an engineering change, not relabeled as a
   prompt-optimization gain.

The reusable Task Agent is the first improvement target. Changing the optimizer
itself requires a separate outer benchmark and held-out evidence; repeated PRs
alone do not establish recursive improvement of the optimizer.

## Current acceptance boundary

Shared instructions, memory and local verification commands are implemented.
The reference source has been inspected and pinned. A Penguin server, a chosen
model, calibrated Benchmark, Formal Baseline and optimization run have **not**
been provisioned or executed. There is no RSI performance score yet. This avoids
introducing a second large runtime into the current installation before its
ordinary startup and recovery are reliable.

Source contracts:

- [Default optimization workflow](https://github.com/Prism-Shadow/penguin-harness/blob/c68dc1e9348017702c1b46777821264f1f3c40a5/plugins/default-rsi-toolkit/skills/agent-optimization/SKILL.md)
- [Benchmark package format](https://github.com/Prism-Shadow/penguin-harness/blob/c68dc1e9348017702c1b46777821264f1f3c40a5/plugins/agent-evaluation/skills/benchmark-design/reference/package.md)
- [Agent State setup](https://github.com/Prism-Shadow/penguin-harness/blob/c68dc1e9348017702c1b46777821264f1f3c40a5/plugins/agent-development/skills/agent-initialization/SKILL.md)
