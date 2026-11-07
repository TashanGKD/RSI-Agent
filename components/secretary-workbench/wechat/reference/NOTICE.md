# Source reference

`capture.py` adapts the own-account WCDB key-capture argument-layout approach published by CloudDreamAI / TANGandXUE under MIT. The original source reviewed on AUP was:

- https://github.com/TANGandXUE/wcdb-key-tool/blob/main/wcdb_key_tool.py
- SHA256 of the inspected file: `f50e9d9ec33f9dd8a808d17ee214a1a62809ed78a7ee40252798351dc90e8ac9`
- License: `LICENSE.wcdb-key-tool` in this directory.

The original project's global sudo, process attachment, killall and bulk export entrypoints are not used. This adapter only starts the already-authorized own child process for initial capture, validates the derived material against the actual native database, and does not change Yama/ptrace policy. Secret values remain in the private AUP workspace and must not be copied into this source tree.
