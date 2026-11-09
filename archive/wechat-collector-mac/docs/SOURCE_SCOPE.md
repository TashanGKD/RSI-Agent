# 本次源码范围

初包从现有 Mac 工程逐文件读取并复制 147 个静态源码/通知文件；补核后另加 13 个经来源核对的 Mac 独立源码，现为 160 个、约 1.39 MB。`PACKAGE_MANIFEST.json` 记录每个来源相对路径、原 SHA-256、包内 SHA-256及仅在包内发生的替换。新仓从干净初始提交开始，不携带旧工程或上游的 Git 历史；保留根提交及来源补充提交，补核另作后续提交。

选入 `src/MacData`、`src/MacHost` 顶层及其 `Web`、`src/MacCLI`、`src/MacNative`、`src/MacShared`、`src/MacScreenReader`、`src/MacWorker` 的源码文件；构建脚本、生成数据的 WorkerProtocol 测试，以及 23 个逐项核对的 PortableCore 独立扩展文件。没有遍历后直接复制目录，也没有复制 `bin`、`obj`、`.runtime` 或 `build`。三份 Safety 文件与参照源码相同或在其上修改，保持排除；逐文件依据见 `PORTABLE_CORE_PROVENANCE.md`。

`src/MacWorker/foundation` 中若干文件来自此前本机阅读器的自有实现：`attachment_names.py`、`security.py` 与 `decode-voice.cjs` 保持一致；`crypto.py`、`capture.py`、`media.py`、`library.py` 等已在本项目修改。该早期阅读器曾使用 `r266-tech/wxkey` 作为外部辅助程序，参见第三方说明；本仓不复制辅助程序本身。

在隔离副本里把开发者绝对路径改成环境变量或 `vendor` 占位；删除了含真实进程标识的两个编译期验收片段。上游原件没有修改。运行包、微信容器、记录库、归档、模型、钥匙串、凭据、日志和历史会话均未读取或复制。

本包没有把 `gqy20/wechat-ui-collector` 私有仓及用户提供的 Windows 发行资源视为本仓自有代码。它们的源码/资源和许可须由权利人另行确认；本仓的“缺口”不是对取得这些内容的授权。

## 2026-11-06 原源码静态刷新

截至 `2026-11-06T20:09:46+08:00`，逐个重新读取上述 160 个原工程相对路径并比较 SHA-256，变动 0、缺失 0；原包范围内新增可选 Mac 源码 0，23 个已识别的独立 PortableCore 扩展仍全部在包内。原工程不是 Git 仓库，因此没有可引用的原工程 commit；`SOURCE_REFRESH_20261106.json` 保存 160 个实际来源哈希及确定性选入源码摘要。更新前私仓 HEAD=`f5cbc8a40b15f28777e3af51a7d487ba776a3f03`、tree=`286ac8b382cf45c4c059dbce4694d296d30e6c36`。此次只更新交付说明与核对记录，不修改或清理原工程。
