# Current checkpoint

RSI Agent uses one repository for the Linux WeChat trigger and the local Codex
receiver. New private and group requests share the dedicated Codex conversation.
The trigger retains the native inbox and V2 delivery, and the receiver retains
the original job and result. See the [repository entrypoint](../README.md) for
code and operator commands. The independent SCNET group gate is disabled on the
current deployment. Use the live release and process records to verify activation.

The [Windows setup skill](../.agents/skills/rsi-wechat-setup/SKILL.md) points
to the [repository installer](../deploy/wechat-wsl/README.md). Keep Ubuntu and
the official client as verified first-run downloads. For a new installation,
verify login, native trigger intake, the dedicated Codex turn and original V2
delivery separately.

Native confirmed friends can have ordinary private replies, and a joined group
can participate when native membership confirms the signed-in account. The
private conversation admission cutoff controls the new scopes. Friend inboxes
are per peer and use local Codex chat without owner memory or engineering.
Current friendship is checked before native sending. Keep the original owner
and group state and verify new replies against their original V2 receipts.

An initial group chat request explicitly returned in Codex review now isolates
its original batch as model_review. Subsequent group messages can proceed. The
original packet, ACK and worker review are retained for reconciliation.

PR #34 is merged and activated. The dedicated desktop target has completed real
private and group turns with matching original V2 sends. Other completed group
turns have pending native effects. Check the private `unified_wechat_thread`
receipt and live queue before claiming delivery for any original. Maintenance
does not execute or replay those turns. The prior article-card diagnosis is in
`pending_article_reader`: a non-owner card was outside the reader's scope.

The original share-card delivery remains a separate queue reconciliation
problem. Match its native admission, desktop turn and V2 outcome using the
original batch and ACK. The older DeepSeek gate rollout is recorded in D023.

Ordinary photo export accepts decoded bytes matching the exact native message
MD5 even when the default Save filename changes. Converted files still require
the native time and local ID in the official filename. Export failures retain
a bounded stage for the next real image investigation. Check the installed
processes against live receipts. An isolated Codex run recognized a PNG. A fresh
ordinary WeChat photo still needs end-to-end verification.

The PDF intake candidate binds already downloaded ordinary-file PDFs to their
native peer, sender, message, cache resource, size and MD5. The desktop
receiver stores the original PDF privately and exposes a digest-bound document
alongside the existing image manifest. Frozen media requests reuse their
original packet while waiting for Codex. Isolated PDF text and page rendering
passed. Verify the actual release, receiver and new native inputs before
claiming live photo or PDF delivery.
