# Project memory

This is RSI Agent's GitHub-backed project memory. It follows the existing
Memory Vault convention, with task history represented by commits and PRs.

Read order: `CURRENT.md` → `CURRENT.workbook.md` → `todo.md` → `decisions.md`;
consult `lessons.md` when investigating a matching failure. `harness/` defines
verification and the Penguin integration boundary; `.agents/skills/` defines
the recurring work.

Update the smallest applicable file after an evidence-backed change. For a
specific work item, update its `workbook/` note and refresh the derived view;
for the project baseline, update `CURRENT.md`. Keep one current baseline and one
next action. Link immutable evidence or the actual PR; label proposed, tested,
merged, deployed and live-accepted states separately. New observations
supersede old notes. Do not update a timestamp alone.

## Per-item workbook

`workbook/` holds one note per independently deliverable result. Each note has
one `rsi-work` block with the eight fields in order: 事情, 怎么来的,
这次想做到什么, 我的想法, 现在怎么样, 下一步, 时间, 过程笔记. The state is one of
待推进, 等反馈, 先放放, 已办好, 不做了.

Create a note with real provenance and a checkable result, then derive the view:

```sh
python -m rsi_agent workbook new --root memory --title "..." \
  --source "..." --goal "..." --next "..."
python -m rsi_agent workbook review --root memory
python -m rsi_agent workbook set --root memory --title "..." \
  --state 已办好 --next "..." --log "..."
python -m rsi_agent workbook archive --root memory --title "..." --execute
python -m rsi_agent workbook refresh --root memory --execute
python -m rsi_agent workbook check --root memory
```

`set` changes only the current-summary fields and may append one dated line
under `过程`; it does not rewrite history. `archive` is a move, not a delete:
only `已办好` or `不做了` notes can move to `workbook/archive/`, where they stay
out of the active view and remain readable. `review` reports active and visible
counts, archived notes, the generated view state and any budget overflow without
writing anything.

`CURRENT.workbook.md` is generated; do not hand-edit it. `CURRENT.md` remains
the curated project checkpoint. `refresh` without `--execute` only reports
whether the view is current. The generator rejects symlinks, missing or unknown
fields, duplicate titles, unknown states and a view that differs from the
notes. It also enforces these default budgets: 20 active notes (`待推进` or
`等反馈`), 30 visible non-archived notes, 1,200 characters per current summary
and 8,192 bytes for the generated view. Exceeding a limit blocks `new`, `set`
and `refresh`; close and archive finished work or shorten the summary. An
archive-only workbook may still generate an empty view. Refreshing does not
edit notes, send messages or prove business truth; `new` only creates a note.

For release completion, consult the actual PR's delivery receipt and the host's
`/var/lib/rsi-agent/release.json` plus current symlink. An earlier acceptance
revision in a checkpoint is historical evidence, not a lock on deployment.

Never store account identifiers, credentials, secret material, raw chats, full
transcripts or private screenshots here. Private run artifacts go under ignored
`var/` or the installation's private runtime. Sanitized evidence belongs in
`harness/evidence/` only when it supports a durable decision.

This directory is product-owned memory. It does not change the user's global
Codex memory vault or copy that vault's personal records into this project.
