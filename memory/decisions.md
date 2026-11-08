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

## D005 — Real invited-group context and moderate text participation

The user extended the owner-only scope to groups they invite this account into,
choosing moderate initiative and priority for mentions/questions. Admit a group
explicitly after native identity and current owner/self membership verification;
do not activate all existing groups. Separate group context from owner-private
history and model decisions from original V2 effects. Commit before ACK, cache
before send and preserve stable original requests. A quiet decision is normal.
Trusted application facts explain actual WeChat access; raw group instructions
cannot change permissions or expose private chats. The fixed one-time group
introduction and newly received group text are authorized, periodic probes and
client restarts are not.
