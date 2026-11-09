# Current checkpoint

RSI Agent uses one repository for the Linux WeChat trigger and the local Codex
receiver. New private and group requests share the dedicated Codex conversation.
The trigger retains the native inbox and V2 delivery, and the receiver retains
the original job and result. See the [repository entrypoint](../README.md) for
code and operator commands. The independent SCNET group gate is disabled on the
current deployment. Use the live release and process records to verify activation.

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
a bounded stage for the next real image investigation. Both reply services
use the PR #39 release. An isolated Codex run recognized a PNG. A fresh
ordinary WeChat photo still needs end-to-end verification.
