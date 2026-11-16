# Recover one failed native group text after a client restart

Use this private admin path after a recipient has confirmed absence and the
original request owns the V2 queue in `unknown`. It keeps the existing request,
frozen text and attempt. The original must be a single `send_text` execution
with one exact native failure row, zero server ID and sequence, and an exited
window process that owned no parked draft, search or popout.

Run as the WeChat OS user with the existing source, native account and display
environment. Pass one JSON object on stdin for each step.

```sh
python3 -B -m operations.cli admin-request --execute --root "$OPERATIONS_ROOT" --config "$OPERATIONS_ROOT/config.json"
```

1. `open_failed_text_retry` takes `client`, `request_id`, `recipient_absence_sha256`,
   `scene_sha256` and `select`. The absence digest binds the private operator
   confirmation to the original. Use the current official main window capture
   and a point on the visible recipient row. Scene SHA-256 is the digest of
   the window-cropped RGB pixels (`Image.convert('RGB').tobytes()`). Points are
   integer [x, y] offsets from the window's upper-left corner.
2. `click_failed_text_retry` takes the same `client` and `request_id`, plus the
   current popout `scene_sha256`, `copy_point` and `retry_point`. Choose a point on
   the outgoing bubble's green background on the same row as the adjacent
   red failure icon. Official Copy must return the frozen original exactly.
   Wait for reconciliation after `retry_scheduled` or an interrupted command.
   The one-shot record is synced before the official retry click.
3. `finish_failed_text_retry` takes the same `client` and `request_id`. Poll this
   operation. It requires a unique server receipt and exact body. It checks
   that the recovery popout editor is empty before closing that owned popout.
   After verifying the current process and restored window set, it binds
   the unchanged old artifacts to the retirement proof. Unproved receipts
   or cleanup keep the original on hold.

The result records the original send click and recovery click separately.
Continue dependent sends only after this original has a verified receipt.
