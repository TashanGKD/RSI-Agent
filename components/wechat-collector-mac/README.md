# 微信记录 Mac 移植：源码协作包

这是 Mac 本地微信记录读取器的**脱敏源码快照**，供获授权的私有仓库协作。它不是可直接安装的完整发行版，也不代表已经达到 Windows 版的全部功能或稳定性。

本仓只放 Mac 适配源码、独立编写的核心扩展、少量生成数据测试和依赖说明。原微信、聊天库、附件、缓存、密钥、模型、构建产物和原工程历史均不在仓库中。仓库与秘书系统分开；秘书只接收最小的状态或检索接口，不复制原始聊天数据。

## 当前边界

- `src/MacData`、`src/MacHost`、`src/MacCLI`、`src/MacNative`、`src/MacScreenReader`、`src/MacWorker` 是 Mac 适配层的静态源码。
- `overlays/PortableCore` 现含 23 个逐项核过的 Mac 独立扩展文件，**不是**完整 PortableCore，也不能单独编译；三份混合/相同的 Safety 文件仍未收入，见[来源补核](docs/PORTABLE_CORE_PROVENANCE.md)。
- 参照 Windows 0.2.5 包的 `src/PortableCore` 主体、`src/MacHost/OriginalDesktop` 和 `reference-web` 没有可核实的再分发许可，未收入。逐文件清单见 [`docs/OMITTED_FILES.json`](docs/OMITTED_FILES.json)。
- 当前源码仍有首次连接、内存与提前退出清理、公众号完整历史、所有附件和长期运行的未验收项。已有本地试验或编译不等于安装版验收；本包未启动客户端、读取本机微信或进行端到端运行。
- **2026-11-06 静态刷新：**逐项重读原 Mac 工程中本包选入的 160 个来源文件，SHA-256 全部与现有清单一致；原包范围没有新增可选 Mac 源码。此次只更新截止证据和说明，不把同一源码伪装成新实现。原工程不是 Git 仓库，准确截止时间、逐文件哈希及所核私仓旧树见 [`docs/SOURCE_REFRESH_20261106.json`](docs/SOURCE_REFRESH_20261106.json)。

## 快速开始

1. 克隆这个**私有**仓库，在 Mac 上查看源码：`git clone https://github.com/TashanGKD/wechat-collector-mac.git`。
2. 运行纯静态核验：`python3 tools/verify_package.py`。它只读本仓文件，不访问微信、钥匙串、进程或网络。
3. 阅读 [`docs/BUILD_GAPS.md`](docs/BUILD_GAPS.md) 和 [`THIRD_PARTY.md`](THIRD_PARTY.md)。获得原 Windows 核心及资源的独立授权后，才能按文件清单在**本地**补齐缺口；不要把未核许可的包提交到本仓。
4. 如需本地构建，先复制 `.env.example` 的配置含义到你自己的环境变量。构建脚本有显式输入参数；当前包缺少上游核心和若干第三方文件，完整构建预计失败，不能当作已交付的应用运行。

## 常用命令

| 命令 | 用途 |
|---|---|
| `python3 tools/verify_package.py` | 逐文件哈希、文件类型和脱敏静态检查 |
| `python3 scripts/build-mac.py --help` | 查看本地打包参数；不启动微信 |
| `python3 scripts/build-worker.py --help` | 查看 worker 打包参数；不读取数据 |

## 目录

| 路径 | 内容 |
|---|---|
| `src/Mac*` | Mac 原生界面、宿主、数据适配和辅助进程源码 |
| `overlays/PortableCore` | 独立扩展，须与获授权的上游核心配合 |
| `scripts` | 构建脚本；开发机绝对路径已改为配置占位 |
| `tests/WorkerProtocol` | 生成数据协议测试源码；本轮只做静态检查 |
| `docs/PACKAGE_MANIFEST.json` | 160 个选入原文件的来源和双侧 SHA-256 |
| `docs/OMITTED_FILES.json` | 527 个未带入核心文件及其他资源的逐项清单 |

## 关键文档

| 文档 | 用途 |
|---|---|
| [`docs/SOURCE_SCOPE.md`](docs/SOURCE_SCOPE.md) | 选入、排除和脱敏方法 |
| [`docs/SOURCE_REFRESH_20261106.json`](docs/SOURCE_REFRESH_20261106.json) | 本次原工程源码截止与逐文件 SHA-256 核对 |
| [`docs/BUILD_GAPS.md`](docs/BUILD_GAPS.md) | 缺失文件对编译与功能的具体影响 |
| [`docs/PORTABLE_CORE_PROVENANCE.md`](docs/PORTABLE_CORE_PROVENANCE.md) | Mac 自研扩展与混合 Safety 文件的逐项补核 |
| [`THIRD_PARTY.md`](THIRD_PARTY.md) | 第三方依赖、许可来源和获取方式 |
| [`docs/INTEGRATION_BOUNDARY.md`](docs/INTEGRATION_BOUNDARY.md) | 与秘书系统的最小接口边界 |

## 环境变量

| 变量 | 用途 | 何时需要 |
|---|---|---|
| `WECHAT_COLLECTOR_DOTNET` | 本机 .NET SDK 可执行文件 | 本地构建 |
| `WECHAT_COLLECTOR_PYTHON` | 已安装 Python 依赖的解释器 | 未使用打包 worker 时 |
| `WECHAT_COLLECTOR_SILK_WASM_DIR` | 获许可的 `silk-wasm` 安装目录 | worker 打包 |
| `WECHAT_COLLECTOR_HELPER_BIN_DIR` | 经单独授权取得的 helper 目录 | worker 打包 |
| `WECHAT_COLLECTOR_SIGN_IDENTITY` | 本机已存在的签名身份或 `-` | 签名打包 |

## 发布与验收

这里只发布私有源码快照，不部署服务，也不启动旧后台。此仓目前缺少可再分发的 PortableCore 主体、原桌面控制器与 UI 资源，在新机器上不能据此安装完整应用。补齐依赖后的构建、签名、真实文件/语音/公众号读取、检索读回和 24 小时稳定性均需分别验收；本次静态刷新未进行这些操作，不把源码、测试或编译通过写成安装/运行验收。

## 协作分支

对于获准读取但不可直接推送或合并主干的协作者，见 [只读权限下提交分支补丁](CONTRIBUTING.md)。现有维护者的角色与发布分工保持。
