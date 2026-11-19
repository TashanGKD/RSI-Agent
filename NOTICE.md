# Source and distribution boundaries

The Linux WeChat module in `components/wechat-linux` was relocated from the private source snapshot listed in `SOURCES.lock.json`.

No open-source license is granted over the repository as a whole. Owned parts were delivered under the internal collaboration authorization and do not grant public redistribution or commercial use. Third-party files keep their original licenses: the WCDB key-capture adaptation is covered by [its notice](components/wechat-linux/reference/NOTICE.md) and MIT license. This integration does not supply or relicense proprietary clients, account credentials, source messages, models or auxiliary binaries.

The retired secretary workbench, Mac collector and trigger experiments, with their own notices and licenses, remain in Git history before the cleanup that removed `archive/`.
