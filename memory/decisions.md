# Decisions

## D001 — GitHub owns the project history

Keep durable state, decisions and lessons in this repository. Use commits and
PRs to review changes, rather than copying full conversations into a second
memory system. Source data and credentials remain in private runtime storage.

## D002 — Shared Harness, two execution roles

Codex's requested 45-minute loop performs engineering and PR work now.
PenguinHarness is the planned fixed-model agent/Skill optimizer. Both consume
the same project checkpoint and public task definitions, and preserve versioned
candidates. Neither may grade itself as improved merely because it changed files.

## D003 — Regression is a prerequisite, not an RSI score

Keep the model, frozen task set, evaluation runtime and evaluator fixed for a
Penguin comparison. Record rejected as well as accepted hypotheses. Training
feedback and final held-out evaluation must be separate. Do not optimize away
failed checks by changing the benchmark or relabeling unsupported cases.

## D004 — One WIP and concrete usefulness

Default to a small PR against current main. Fix or narrow the existing WIP before
opening another overlapping PR. No new evidence or useful delta means no-op.
Report merge and deployment separately; routine refactoring needs a demonstrated
user-path benefit, such as simpler installation or a reproducible recovery fix.
