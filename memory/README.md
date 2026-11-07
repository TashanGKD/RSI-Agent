# Project memory

This is RSI Agent's GitHub-backed project memory. It follows the existing
Memory Vault convention, with task history represented by commits and PRs.

Read order: `CURRENT.md` → `todo.md` → `decisions.md`; consult `lessons.md`
when investigating a matching failure. `harness/` defines verification and
the Penguin integration boundary; `.agents/skills/` defines the recurring work.

Update the smallest applicable file after an evidence-backed change. Keep one
current baseline and one next action. Link immutable evidence or the actual PR;
label proposed, tested, merged, deployed and live-accepted states separately.
New observations supersede old notes. Do not update a timestamp alone.

Never store account identifiers, credentials, secret material, raw chats, full
transcripts or private screenshots here. Private run artifacts go under ignored
`var/` or the installation's private runtime. Sanitized evidence belongs in
`harness/evidence/` only when it supports a durable decision.

This directory is product-owned memory. It does not change the user's global
Codex memory vault or copy that vault's personal records into this project.
