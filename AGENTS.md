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
The user subsequently authorized restoring the latest confirmed-owner private
text reply and ongoing replies in that same private conversation. This permits
the explicitly scoped owner reply service, not periodic test messages, other
contacts/groups, model tool execution or additional client restarts.
The user subsequently authorized participation in owner-invited groups, with
moderate initiative and priority for mentions/questions. Start with the uniquely
verified group shared by the owner and this account; register each group
explicitly. This permits scoped group text and a one-time introduction, not
all existing groups, command execution, periodic probes or client restarts.

One user-approved ordinary client restart and cached login have been verified.
That one-shot restart and the earlier one-shot send are not a recurring
maintenance window. Use the latest user authorization and checkpoint when a
later operation would interrupt login or require phone availability.

`scripts/check.py --linux` is a regression gate. `python -m rsi_agent audit`
checks live process/layout/service conditions without input. Neither establishes
general message delivery or RSI gains. Keep code, CI, merge, deploy and live
acceptance states separate in the PR and project memory.
