# Current checkpoint

## Delivered baseline

PR #18's live delivery receipt supersedes its candidate checkpoint. Main/current,
release metadata and both resident workers were verified at 5cbb011bbfa2, with
DeepSeek Harness/SCNET and automatic admission of future owner-shared groups.
No new actual group has yet established end-to-end admission/reply acceptance.
PR #19 was closed after review: its original completed result and commit remain,
and the isolated owner branch now has the delivered main tree without resetting
its history. Private receipts and the PR bodies are authoritative. The user's
maintenance interval is now 30 minutes; resident replies run independently.

## One WIP: native quoted-text group replies

The user reported that the existing group stopped replying. Actual native
records show a type-49/subtype-57 quoted question after the last ordinary text
reply. SourceInbox ACKed it, but GroupLoop admitted only plain text and images;
the consumer never stored the question and no model turn occurred for it.

Candidate extracts the current title of a bounded native type-57 message and
resolves its quoted server ID against the same group's committed native rows.
Only that actual row supplies quoted text and whether it was Xingyu's message;
XML names/quoted contents cannot grant identity or engineering authority. Keep
the original kind 49 and server ID, treat this as chat rather than an image, and
retain the existing commit-before-ACK/cache-before-send/restart behavior.

The frozen SQLite path fails on the delivered baseline (idle/drop) and passes
on the candidate (pending original reply, lost-result/restart without duplicate
generation). An isolated copy of source receipts with the actual native inbound
question reproduces that difference, including verified self-reference, while
production ACKs/consumer rows remain intact. Its model is a fixture: no provider
call or live send is claimed. Targeted and complete Linux checks passed. The
previously ACKed old question is not silently replayed into production.

## Unique next step

Review the actual quoted-reply PR head/CI, publish and activate it reversibly,
then observe fresh real quoted-text input. Do not reopen #17/#18/#19 or replace
an old SDK/V2 request. Publication recovery from the original sdk_completed
result is the next independent task once this repair is delivered.

The PR #16 native cover reply remains delivered; fresh ordinary-photo automatic
reply, folded albums, whole-video understanding and cross-boot desktop recovery
remain outside proven acceptance. Penguin's DSH evaluation adapter, frozen
Benchmark, fixed-model Formal Baseline and independent evaluation remain open.
Secrets, raw chats, native identities and private images stay outside Git.
