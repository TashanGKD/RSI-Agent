# Invited group participation

The owner/private service now supplies truthful runtime facts to the model and,
when asked about an enabled group, reads that group's actual recent text.
Previously the model received only private conversation history and incorrectly
denied having a WeChat connection. Native group context is data, never a system
instruction; the group worker receives no owner-private history or other groups.

`python3 -B -m rsi_agent --config /var/lib/rsi-agent/groups/config.json groups check`
checks the private registry, model configuration, native group identity and
membership without sending or probing the model. `groups run` is the independent
server worker; it does not depend on Codex maintenance. Use the fixed-release
unit in `deploy/group-replies/`, after preparing a verified native UI binding.

The root-owned registry contains only `{"groups":["/absolute/private/config.json"]}`.
Each private config uses the same six fields as owner replies: installation,
binding, model, state, enabled and binding_token. The dedicated-user binding
contains account, owner_peer, group_peer, confirmed_by_user=true,
invited_by_owner=true, auto_reply_enabled, reply_model_binding, and send_scope
with mode=invited-group-text, since (integer epoch), and exact native name.
The group fingerprint is separate from, and does not change, the owner token.
Confirm both account and owner remain current members. Do not infer permission
from the presence of an arbitrary existing group or automatically join one.

Activation posts one fixed introduction through a stable original V2 request.
Subsequent participation considers newly received, nonself group text after
activation, plus at most 20 recent text messages. Decisions can remain silent.
Native mentions and explicit RSI references bypass the one-minute spacing for
ordinary proactive comments; they still pass the model's relevance decision.
Several incoming texts produce at most one cached reply per decision. Historical
messages provide context, not a backlog of replies. Images/voice are not decoded.

Root commits incoming events before source ACK. It stores generated text before
submitting the original V2 sender and keeps the same request through lost
responses/restarts. Unknown/review/unproved cleanup stops later sends. The shared
executor lock and targeted queue claim preserve other active/queued operations.
Only text is accepted; model tools and server commands have no execution path.

Code promotion and worker activation are separate. Check all original jobs and
the inbox before stopping a quiescent worker; retain its private DB, ACKs and
binding. Pin both units to the reviewed release, then independently verify their
actual cwd/PID and private status. Stop the group unit and disable its private
switches to pause participation; keep its receipt/cache to avoid replay on resume.
Do not roll back by changing `current` alone while a worker remains on old code.
This does not solve desktop restart/layout recovery or establish long-term
stability. New group enrollment requires a verified identity/window binding.
