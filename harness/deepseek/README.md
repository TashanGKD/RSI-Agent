# DeepSeek Harness backend

Use `requirements-harness.txt` in a separate Linux virtual environment. The
pinned runtime wheel carries its executable; it does not need system Node.
`scnet.patch.yml` uses the SDK's OpenAI-compatible provider because SCNET serves
Chat Completions rather than the default DSH Messages API. Existing provider
configuration/key files stay private and are referenced, never copied into Git.

The private backend JSON has `backend: "deepseek-harness"`, `provider_config`,
`python`, `state`, and `workspace`. Paths must be absolute; configuration is
owner-only, state/workspace are owner-only directories. Point an explicitly
enabled reply configuration's `model` at it. `chat.patch.yml` removes execution
tools. Each native account/peer gets its own persisted SDK session; original
inputs and completed results are cached before native sending.

Optional `engineering_workspace` enables the owner development route. It is an
isolated clone of this repository on `rsi/runtime/owner-work`, with repository
scoped SSH access configured locally. Only the already-confirmed native owner
can enter this route; group display names/model claims cannot. An unresolved
work marker stops later tool execution until the original result is inspected.
Normal Linux checks precede committing/pushing. `Owner work review` creates one
draft PR; integration checks also run on the branch push. The repository must
allow Actions to create PRs while default workflow permissions remain read-only.
This route does not merge, deploy, manipulate the WeChat UI or send extra messages.

Image input uses native kind 3, the original V2 export, native MD5 and decodable
bytes. Cache XML is excluded from model input. A recent folded three-image album
was rejected as ambiguous; grouped albums are not established as supported.
Single-image automatic delivery still requires a fresh native acceptance receipt.
The real SDK has passed supplied-PNG reading, persisted image follow-up, strict
group JSON and real shell execution in an isolated private pilot. These are
integration evidence, not proof of all client layouts or an RSI score.
