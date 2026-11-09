# Two separately accepted trigger experiments

These are operator-run experiments, not a replacement WeChat consumer. They do
not claim the production `/codex` path is immediate or that an existing desktop
conversation has been awakened. Ordinary DSH replies and the native V2 sender
are unchanged. Never insert a fixture into the production inbox.

## Local Codex: a remote event starts work

`local_codex_probe.py` starts an authenticated loopback HTTP receiver and a
temporary SSH reverse forward. A remote HTTP event starts this computer's
independent `codex app-server --stdio`, using the existing ChatGPT login. It
creates an ephemeral read-only thread, reads a random local challenge through
the shell, freezes the completed result, and returns it to the remote caller.
The target host does not install or run Codex. The tunnel is closed afterward.

```powershell
python -B experiments/triggers/local_codex_probe.py `
  --codex <existing-local-codex.exe> --ssh <existing-destination> `
  --identity <existing-private-key-path> --state var/trigger-probe/<new-run>
```

The run directory must be new. It retains the original input/digest, journal,
App Server events and acceptance receipt. A duplicate event gets the same
completion; changed input is rejected. An uncertain run is retained for review,
not automatically rerun. This bounded process is not an installed background
worker, a desktop-thread control connection, or a crash-recoverable production
queue. Integration with native `/codex` admission/claims remains separate.

## Dot: a genuine MCP subscription is required

`dot_events_probe.py` implements Streamable HTTP discovery, one MCP Events
catalog, signed callback verification, persistent subscriptions, and a single
receipt tool. It has no WeChat input, arbitrary URL-reading tool or host-command
tool. The capability URL is private; keep configuration, SQLite and callbacks
outside Git. Callback delivery accepts only pinned public HTTPS destinations,
checks TLS, rejects redirects/private addresses, and uses Standard Webhooks
signatures. Repeated subscriptions, events and completions retain their IDs.

### Install directly into local Codex

After hosting/verification, `install_codex_plugin.py` renders the private URL
into a portable MCP plugin, creates a separate local marketplace and installs
it using supported `codex plugin marketplace add` / `codex plugin add` commands.
It backs up local config and retains CLI receipts; it does not automate or
restart the desktop. Existing plugin/marketplace entries are preserved by the
CLI. Generated packages and config backups contain private data; keep them
under the ignored `var/` directory.

```text
python -B experiments/triggers/install_codex_plugin.py --codex <existing-local-codex.exe> --connection <private-connection.json> --state var/trigger-probe/<new-install>
```

The plugin's display name is **RSI Trigger Lab**. A fresh App Server inventory
must actually discover `complete_trigger_probe` with no tools error before
calling local MCP loading verified. This does not establish a Dot subscription
or immediate awakening of an existing desktop conversation. Do not call the
receipt tool against a made-up or production request to test installation.

### Connect an event-receiving Dot

Private configuration:

```json
{"bind":"127.0.0.1","port":35472,"capability":"<random-secret>","database":"<private-db>"}
```

Expose `/<capability>/mcp` through an isolated HTTPS route or a supported Secure
MCP Tunnel. This experiment uses protocol version `2025-03-26`; it does not
implement MCP 2.0. Create a custom MCP plugin in a signed-in ChatGPT account,
then enable it for the intended Dot. The direct local plugin above provides
the local MCP connection, but does not itself establish a cloud/Dot subscription.

Give that Dot this instruction:

> Subscribe to `rsi.trigger_probe` with `experiment=dot-nonce-v1`. For each event,
> calculate `a * b`, call `complete_trigger_probe` with the original `probe_id`
> and the answer, then report the result. This is a separate fixture; do not
> read or send WeChat messages or run other tasks.

After an actual subscription has passed callback verification:

```text
python -B dot_events_probe.py status --config <private-config>
python -B dot_events_probe.py emit --config <private-config>
```

`emit` requires exactly one unexpired subscription. One-hour subscriptions can
refresh; no replay cursor or unattended event producer is implemented. A retry
keeps the original pending event. HTTP 2xx proves only webhook acceptance.
The original probe becoming `completed` through the tool is the additional
Dot-processing evidence. A simulated callback/unit test cannot supply it.

Offline contract checks (no model/network request):

```text
python -B -m unittest discover -s experiments/triggers -p 'test_*.py' -v
```

## Acceptance and removal

Keep local-trigger, Dot-subscription, actual WeChat source, native delivery and
desktop-thread activation as separate results. See the sanitized evidence in
`harness/evidence/2026-11-09-trigger-experiments.json`. Never copy raw transcripts,
callback secrets, capability URLs or private operator metadata into a PR.

The local run closes its listener/tunnel. An independently hosted Dot fixture
must have its own unit, immutable source and private state; removing its exact
proxy route and stopping that unit must not alter `/opt/rsi-agent/current`,
owner/group residents, client, pending original requests or production queues.

Official contracts: [MCP Events](https://developers.openai.com/plugins/build/mcp-events),
[connect a custom MCP plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[App Server](https://learn.chatgpt.com/docs/app-server).
