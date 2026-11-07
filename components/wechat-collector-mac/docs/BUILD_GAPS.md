# 构建与功能缺口

这是静态源码交接。`docs/OMITTED_FILES.json` 是逐文件清单；以下列出缺口如何影响构建及行为。

1. `src/PortableCore/PortableCore.csproj`、`WechatUiCollector` 主体与默认 JSON 配置未带入。所核 550 个核心文件中，23 个独立 Mac 扩展放在 `overlays/PortableCore`，其余 527 个仍排除；其中 Safety 三文件的具体来源见 `PORTABLE_CORE_PROVENANCE.md`。overlay 不代替主体。`src/MacData/MacData.csproj` 直接引用此缺失项目，因此首先无法编译；有授权的核心后仍须按 MacData 的导入/媒体接口逐项验证。
2. `src/MacHost/MacHost.csproj` 同时引用缺失的 PortableCore 与 MacData，并依赖 NuGet `Whisper.net.Runtime` 1.9.1。`src/MacHost/OriginalDesktop/*.cs` 的九个 Windows 派生控制器也未带入；现有 Host 仍用其中的公众号控制器等类型。即使恢复 Core，Host 仍不能独立编译，须重构这些调用或取得对应文件的分发许可；运行页面还受下一项资源缺口影响。
3. Windows 0.2.5 的 43 个 `reference-web` 资源未带入。`scripts/build-mac.py` 仍引用该目录，安装包的原版页面和对应交互无法由本仓重建。逐项文件名与原字节数在缺口 JSON 中。
4. `src/MacCLI/MacCLI.csproj` 依赖缺失的 PortableCore、MacData、NuGet `Whisper.net.Runtime` 1.9.1 / `System.Drawing.Common` 8.0.12，以及 `vendor/windows-interop/*.dll`（FlaUI / UI Automation 六件）。DLL 未带入、项目引用已指向占位目录；需合法取得这些文件或移除对应 Windows 调用才能编译。它与 Host 的 OriginalDesktop 缺口不同。
5. Python worker 本身不引用 .NET Core，但普通模式导入 `pycryptodome`、`defusedxml`、`zstandard`；这些可由获授权的开发者按第三方说明自行安装，当前仓没有打包 Python 环境。`--connect` 与完整 `.app` 另需经单独取得的 `wxkey-once`/`oneshot-helper.pack`；语音还需 Node `silk-wasm`，图片/视频路径可能需 ffmpeg，转写需 Whisper 模型。`PyInstaller` 只用于 worker 一体化打包。缺失辅助程序与模型不能概称“只差环境变量”；脚本的变量只是取得资源后的路径占位，不能自动回退原开发机私人路径。
6. 原 Mac 工程尚未完成首次连接、Host 提前退出/连接清理、完整公众号历史、全部媒体/语音和 24 小时稳定性验证。即使依赖齐备，仍不得宣称与 Windows 功能完全一致。

本轮可做的检查：`tools/verify_package.py` 检查包内哈希和路径；Python AST 与项目 XML 可静态解析。没有启动 App/Host/worker，没有读取原微信，也没有执行依赖真实库的测试。需要补齐许可、依赖和独立测试环境后，才进行实际构建与安装验收。

2026-11-06 刷新只确认静态来源文件与 10 月包相同，并未补入缺失的上游主体、第三方 DLL、Windows UI、helper 或模型。因此 MacData、MacHost、MacCLI 的独立编译条件及 worker 的按模式依赖仍如上；没有新的安装包、首次连接、检索覆盖或新机器端到端验收证据。
