# Current checkpoint

## Delivered baseline

Latest main/current checked: `2a6d61d5d569470cc08894bb3edd65f16724ac19`.
PR #7 delivered owner-private replies; PR #8 delivered admitted group intake,
context, moderate decisions and a native accepted introduction; PR #9 delivered
natural conversational tone. Their live delivery receipts supersede the old
candidate states. Both server workers are active and independent of Codex.
Owner PID 259347 and group PID 259346 are pinned to that release; verify live
again before acting. The admitted group still contains account and owner.

## One active failure: follow-up incorrectly ignored

A natural incoming group text immediately after the account's introduction was
received, ACKed and marked quiet. The user explicitly pointed out that someone
was replying and expected the account to answer. The earlier receipt's quiet
observation established intake, not correct conversational behavior.

Hypothesis: classifying general chatter as usually quiet, while supplying only
mentions/questions as direct priority, misses replies to the account's own turn.
Native previous-message identity can distinguish this case without requiring an
@ or punctuation. Candidate: carry follows_self from the same committed native
metadata order, persist it in the private group inbox, prioritize the message
through spacing, and tell the model to answer actual conversational follow-ups.
Finished acknowledgements and other people's conversations may still be quiet.
Original message text, source ACKs and request identities remain unchanged.

The frozen fixture fails baseline in three places (missing relation, withheld
priority and lost model retry); candidate passes all 22 group/owner checks. The
real SCNET isolated analogue speaks for an introduction follow-up, remains quiet
for a closing acknowledgement and an unrelated exchange; no production send.
The native fixture covers same-second ordering and multiple current members.

## Authorized recovery and next step

The user specifically asked why this already-received follow-up was unanswered.
After review/CI and fixed release, stop only the quiescent group worker. Retain
private backup and original SDK records; verify that the identified quiet event
belongs to the confirmed owner, follows the account's actual introduction, has
no cached send text and no original V2 request. Enrich only its adjacency flag
and reconsider this exact original event once. Let the updated server worker
perform model/cache/original V2 sending; do not inject a fixed reply, replace an
ID, replay other quiet history or repeat the introduction. Verify its native
exact-text/one-click/cleanup receipt separately. Keep owner worker pinned and
uninterrupted because its source is unchanged. Latest PR receipt will supersede
this candidate checkpoint.

## Boundaries

Only confirmed owner-private incoming text and the admitted invited-group scope
are enabled. No blanket activation of existing groups, periodic probes, other
contact private replies, arbitrary old-history replay, model tools, commands or
client restarts. Unknown/review/unproved cleanup preserves the original request
and blocks later sends. No raw chats, identity IDs, keys or screenshots in Git.

Desktop services remain transient; cross-boot recovery and long stability are
unverified. Existing permission/receipt/install rehearsals are completed, not
new WIP. Penguin fixed-model Benchmark, Formal Baseline and independent
assessment remain unestablished; engineering repairs are not RSI score gains.
45-minute automation is currently PAUSED; server workers remain independent.
