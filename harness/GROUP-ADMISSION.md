# Automatic admission of future groups

The owner no longer needs to register each future group. Native membership of
both the confirmed owner and this account is the admission rule for groups first
joined after activation. Existing groups are frozen in a private baseline;
the already admitted group keeps its original configuration and source cutoff.
Observed invitation system messages have nicknames without a trusted inviter ID.
Do not turn those nicknames into authority or claim the inviter was proved.

The existing group reply service scans native contact membership every 15 seconds
when its loop is available. `groups/admission.json` is private and optional:

```json
{
  "enabled": true,
  "owner_config": "/var/lib/rsi-agent/owner-replies/config.json",
  "account": "native-account-id",
  "owner_peer": "confirmed-native-owner-id",
  "since": 100,
  "last_checked": 100,
  "initial_groups": ["previously-existing-group@chatroom"]
}
```

Populate identities and the initial baseline from the actual native catalog,
never from chat text. The catalog runs as the existing dedicated native user;
the service writes private per-group bindings/configs and appends them atomically.
The prior successful catalog time sets the new group's immutable input cutoff,
so messages arriving during discovery can be handled. Admission never reads raw
message bodies. Other groups' in-memory loops, cached results and source ACKs are
retained while newly admitted groups are loaded without restarting the service.

New groups have no scripted introduction. Participation starts from scoped
incoming messages, using the established moderate/@/question policy. An identity
seed has no invented header pixels or editor coordinates: the existing native
navigation must prove the actual recipient before input. Unnamed or ambiguous
targets remain `unaddressable`; the current native sender needs a uniquely
resolvable name. Do not guess a conversation or silently confirm review.

`admission-status.json` and the operator-only status tool expose discovery state,
freshness and waiting counts without names/IDs. A catalog failure preserves prior
bindings and does not stop other groups. Disabling `admission.json` stops future
admission; already admitted scopes remain explicit private records and can be
disabled individually without deleting their original inboxes or send IDs.
