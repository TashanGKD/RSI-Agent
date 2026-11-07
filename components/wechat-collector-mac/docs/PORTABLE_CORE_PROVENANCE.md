# PortableCore 补核：独立 Mac 文件与混合 Safety 文件

本轮只做静态来源与文件级范围核对。比较对象是本机 Windows 0.2.5 解出源码 `reference-source/core`、可见的私有上游 `gqy20/wechat-ui-collector/src` 当前树、原 Mac 工程源码及已有 Mac 计划/生成测试。原 Mac 工程自身无 Git 历史，因此“两个参照树都无同路径 + Mac 功能/测试证据”支持本项目独立新增的判断，但不是关于所有历史提交或第三方概念的绝对证明。已对下列新增源码查过开发机绝对路径、账号标识、密钥文本和明显凭据模式；只复制静态源码，不含实际数据/密钥/二进制。

以下 13 个原包漏选文件在两个参照树中均无同路径，且是可单独界定的 Mac 扩展，已补入 `overlays/PortableCore`（路径前缀均为 `src/PortableCore/`）：

| 文件 | 核到的用途/证据 | 状态 |
|---|---|---|
| `Safety/MacCredentialProtection.cs` | Mac vault/AES 保护；与已选 `MacVaultProcessLimits.cs` 成对，原 CoreSmoke 以生成值覆盖加解密 | 已补源码，不含钥匙串值 |
| `WechatUiCollector/Cli/MacCliStartup.cs` | Mac 包内配置/CLI 启动定位；原 `CliStartupPaths` 与 `progress.md` 记录移位验证 | 已补源码，运行配置未带入 |
| `WechatUiCollector/WechatDb/MacEmojiDescription.cs` | 有界 Mac 表情描述解析；原 `MacEmojiDescription` 生成测试入口存在 | 已补源码 |
| `WechatUiCollector/WechatDb/MacLinkCardXml.cs` | Mac 链接卡片 XML 回退；原 MacLinkCardXml 计划和生成测试有独立对照 | 已补源码 |
| `WechatUiCollector/WechatDb/MacForwardedCardXml.cs` | Mac 转发卡片文字投影；原转发计划/生成测试与消费者接线记录 | 已补源码 |
| `WechatUiCollector/WechatDb/MacForwardedLocationXml.cs` | 转发位置 XML 的 Mac 有界投影；原专门计划/测试目录存在 | 已补源码 |
| `WechatUiCollector/WechatDb/MacForwardedSurrogateXml.cs` | 代理字符/转发兼容处理；原专门计划/测试目录存在 | 已补源码 |
| `WechatUiCollector/Safety/LocalAssetFile.cs` | Mac 普通文件只读校验；原文件正文与资源读取计划明确引用该类 | 已补源码 |
| `WechatUiCollector/OfficialAccount/ArticleBodyHttpLimits.cs` | 文章 HTML/图片资源限额，原 T1 对照测试和源码修复记录 | 已补源码 |
| `WechatUiCollector/OfficialAccount/OfficialAccountHttpLimits.cs` | 公众号 HTTP 响应限额，原 T4a 对照测试和源码修复记录 | 已补源码 |
| `WechatUiCollector/Storage/SqliteReadCancellation.cs` | 每个只读 SQLite 连接独立注册取消；原代码为独立 17 行类，不在两参照树 | 已补源码，单独运行验收未作 |
| `WechatUiCollector/WechatDb/IWechatLocalImportProvider.cs` | Mac 导入适配接口；原 MacData 实现及生成连接测试使用它 | 已补源码，真实导入未因打包而验收 |
| `WechatUiCollector/WechatDb/IWechatLocalMediaProvider.cs` | Mac 本地媒体适配接口；原 MacData/Host 调用使用它 | 已补源码，真实媒体未因打包而验收 |

三份原包标“未选”的 Safety 文件仍排除，原因各不相同：

| 文件 | 本轮实证 | 最小补齐条件 |
|---|---|---|
| `WechatUiCollector/Safety/ProtectedSourcePathException.cs` | 与 Windows 0.2.5 解出文件 SHA-256 同为 `d2dfa7b98db27e44477d9355203fb98d3e98308ab02e74e533376e7b5936d542`，字节相同 | 有权使用原核心文件后本地恢复；或另写独立实现，不把原件归作 Mac 自研 |
| `WechatUiCollector/Safety/ProtectedFileSystem.cs` | 与参照文件共享主体；Mac 版对 Move/MoveDirectory、目录删除登记等做了局部修改。参照 SHA-256=`900472c73a1633759f969c05c4c0cd24084fbb1cd01e5e15d75043c11b802482`，Mac 版=`e4b57da0dc634d30152e194274eb2efda21ea06b5284bd9e89a10e4df32b605b`，整份并非纯新增 | 取得参照主体的分发许可后再带完整文件，或在获授权核心上应用经审查的 Mac 改动；当前只记录差异，不上传混合全文 |
| `WechatUiCollector/Safety/SourcePathProtection.cs` | 与参照文件共享主体；Mac 版增加路径别名正规化、lstat 身份校验等。参照 SHA-256=`7c4f597795f6d25c003bbd8559ca85ba7c9048c2c601a360f5762c3d42f65c38`，Mac 版=`91163842bd9a3bb4e9c13edbdd05ea9a64e8a439c91b14ea5f234187a22b8d2b`，整份仍含上游主体 | 同上；需配套原 Core API、平台行为和生成测试，不能把几段代码当可独立编译替代核心 |

`OMITTED_FILES.json` 的 550 项是**被检查的 PortableCore 文件全集**，并非 550 项全部排除。现在 23 项独立扩展已在 overlay 中逐一标 `overlaySourceIncluded=true`，527 项仍排除。其他 524 项的来源并未逐个裁定为“全是 Windows 派生”；在本次安全静态包中仍保守排除。`PortableCore.csproj`、默认配置、模型与大部分原 API 仍缺，三个 .NET 项目不能独立构建；worker 的 Python 依赖及连接/媒体辅助文件分别见 `BUILD_GAPS.md`。
