# RSI Agent collaboration

User instructions take precedence. Keep changes narrow and preserve unfinished work.

For ongoing maintenance, read `memory/CURRENT.md`, `memory/todo.md` and
`memory/decisions.md` before acting. Check the actual branch, open PR, deployed
revision and runtime again; memory is a checkpoint, not proof of current health.

Use `.agents/skills/rsi-agent-maintenance/SKILL.md` for the recurring engineering
loop. There is one active improvement at a time. Work on a branch and leave a
reviewable PR with the problem, resulting behavior and relevant verification.
Do not manufacture a commit or another PR when no useful change is supported.

Keep account data, credentials, raw chats, desktop captures and full production
logs outside Git. Only sanitized facts belong in project memory. Preserve the
original request when a send result is uncertain; never change its ID to retry.
The one authorized File Transfer test has already been sent. Recurring checks
use read-only probes; additional live sends require a new specific instruction.

The current ordinary-startup cleanup needs the user's phone availability.
Do not treat the recurring request as an answer to the outstanding restart
question. Work on independent engineering items while it remains pending.

`scripts/check.py --linux` is a regression gate. `python -m rsi_agent audit`
checks live process/layout/service conditions without input. Neither establishes
general message delivery or RSI gains. Keep code, CI, merge, deploy and live
acceptance states separate in the PR and project memory.
