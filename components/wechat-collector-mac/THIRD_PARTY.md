# 第三方依赖与权利边界

本仓未提交第三方可执行文件、字体、Windows 发布包、模型、NuGet/Python/npm 缓存或用户数据。`docs/third-party-notices/Components.txt` 是原 Windows 参照包附带的组件通知，仅用于识别来源；不构成该整包或其 UI 资源的再分发授权。

| 依赖 | 来源与获取 | 许可/状态 |
|---|---|---|
| Windows 参照工程 `gqy20/wechat-ui-collector` | 私有 GitHub 仓，由权利人另行授权 | 仓库元数据未给出 LICENSE；本仓未复制其主体源码或发行资源 |
| 本机早期阅读器的 Python 模块 | 由此前本机阅读器移植到 `src/MacWorker/foundation` | `attachment_names.py`、`security.py`、`decode-voice.cjs` 与早期版本逐字相同；其余相关模块经过本项目修改。这里只收入源码，不含该阅读器的聊天数据、模型、密钥或构建产物 |
| `r266-tech/wxkey` | [GitHub 源码](https://github.com/r266-tech/wxkey) 与 [MIT 许可](https://github.com/r266-tech/wxkey/blob/main/LICENSE) | 早期阅读器的辅助程序参考此项目；本仓不含 wxkey Go 源码、补丁或二进制，后续若补入须保留 MIT 通知并核对具体版本 |
| .NET 8 SDK / Apple Swift SDK | Microsoft 与 Apple 官方工具链 | 本仓仅保留项目源码，不再分发 SDK |
| `Whisper.net.Runtime` 1.9.1 | [NuGet](https://www.nuget.org/packages/Whisper.net.Runtime/1.9.1) | 包页标 MIT；运行库和模型未带入 |
| `System.Drawing.Common` 8.0.12 | [NuGet](https://www.nuget.org/packages/System.Drawing.Common/8.0.12) | 依赖声明保留；包及许可文件由 NuGet 获取 |
| `pycryptodome` | [PyPI](https://pypi.org/project/pycryptodome/) | 包页列 BSD-2-Clause/Unlicense/MIT 组合；实际安装版本须复核 |
| `defusedxml` | [PyPI](https://pypi.org/project/defusedxml/) | 包页列 PSF License |
| `zstandard` | [PyPI](https://pypi.org/project/zstandard/) | 包页列 BSD-3-Clause |
| `PyInstaller` | [PyPI](https://pypi.org/project/pyinstaller/) | 构建工具，不在仓内；使用时核其所选版本及 bootloader 例外条款 |
| `silk-wasm` | [npm](https://www.npmjs.com/package/silk-wasm) | 包页列 MIT；仅依赖路径占位，未带入代码或 wasm |
| FlaUI / UI Automation DLL、`wxkey-once`、Node、ffmpeg | 原工程引用的本地/第三方文件 | 未核许可与精确版本，不随本仓分发；详见缺口清单 |

以上是依赖定位与来源记录，不替代各版本的许可文件。若未来分发二进制，需按实际构建输入重新核对完整组件、许可证与通知。

2026-11-06 静态刷新核对到选入源码及项目依赖声明均未改变，本次没有新增第三方代码或二进制。Windows 主体与资源的再分发权、未随包提供的 DLL/helper/模型许可仍按上文保留为缺口；本次没有借刷新重新引入它们。
