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

After review and gates pass, complete an already-authorized, reversible code-only
release before adding more WIP. Preserve the prior immutable release, rehearse
pointer rollback and verify the actual current entrypoint. This does not grant
client restarts, real composer input, message sends or service activation. Read
the live PR delivery receipt and host release metadata for rollout state rather
than treating a historical acceptance revision as the current deployment.

Update the smallest existing project-memory entry when there is a durable
delta. Git history and PRs retain the history; do not append repeated timestamps
or duplicate progress logs. Preserve rejected hypotheses and unresolved failures
when they change the next decision. No material delta means no commit or PR.

## RSI 经验分层

维护会话按角色分配有明确结果的协作任务，让执行会话保留自己的上下文、
验收和范围内的迭代。核对按[会话侧 skill](../rsi-wechat-learn/SKILL.md)返回的
脱敏报备与实际产物或原回执。共享改进进入同一个可审查的 GitHub PR，
原聊天、图片和素材留在私有存储。

- **触发**：身份、原生入站、媒体来源和 ACK 的重复问题，落到触发器或 Linux
  微信适配的代码与回归。
- **接收**：原请求、目标轮次、附件、完成结果和 V2 对账，落到相应协议或实现。
  Codex 已完成、桌面显示和微信送达分别核证据。
- **RSI**：把可泛化的做法写到下次会读的 skill 或规则。单次成功、失败假设和
  适用范围只留一条[脱敏经验](../../../memory/lessons.md)。用户认可可复用的素材用私有索引按场景检索。

收束时指出下一次从哪个入口命中这条经验，并用新的适用案例验证是否实际复用。
一条报备可以作为候选。反复遇到的问题用定向前后对照验证，再固化到代码。

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
