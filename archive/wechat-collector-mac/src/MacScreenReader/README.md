# 微信窗口读取助手

独立、无网络的屏幕读取进程，最低 macOS 14.2。只支持安装在 `/Applications/WeChat.app`、bundle ID 为 `com.tencent.xinWeChat` 的一个可见窗口。它不从 OCR 导入消息，也不提供点击、输入、搜索、滚动或发送消息。正文同步继续使用数据库。

## 打包与启动

主程序的资源路径固定为 `helpers/微信窗口读取.app`，助手 bundle ID 固定为 `local.wechat.collector.screen-reader`，`CFBundleExecutable` 为 `WechatScreenReader`，`LSUIElement` 为 `true`。建议固定签名身份；未改变助手源码时复用已经构建和签名的助手。仅有稳定 bundle ID 不保证系统授权持久性，必须实际验证系统将权限归属给谁。

编译源码（按目标机器选择 arm64/x86_64）：

```sh
swiftc -parse-as-library -target arm64-apple-macosx14.2 src/MacScreenReader/*.swift src/MacShared/PipeIO.swift \
  -framework AppKit -framework CoreGraphics -framework CoreVideo \
  -framework ApplicationServices -framework ScreenCaptureKit -framework Vision \
  -framework CryptoKit -framework Security -framework ImageIO -o WechatScreenReader
```

原生主程序直接创建 `Process` 子进程，参数仅 `--serve`，用私有环境变量 `WECHAT_SCREEN_READER_AUTH` 传入随机的 64 位小写十六进制 nonce，stdin/stdout 使用私有管道，stderr 丢弃。nonce 不得进参数、页面、日志或磁盘。每个实例串行请求；退出、超时或 fatal 回包后销毁子进程和管道，重新启动并重新 probe。

助手核验直属父进程的 PID、启动时间、bundle ID `local.wechat.collector.mac`、主可执行文件 `WechatCollectorMac` 和有效代码签名。正式发行可在助手 Info.plist 用 `ScreenReaderHostTeamIdentifier` 固定主程序签名团队；本地 ad-hoc 签名不能证明发行者身份。不要通过 shell、其他 launcher 或 `open` 启动服务模式。

两端使用共享的单次POSIX管道读取组装JSONL。合成短行/长连接测试已复现Foundation `read(upToCount:4096)`等待满缓冲导致超时，并验证修复；保留原来的每行大小和请求超时限制。

无参数启动只输出静态 usage；不读取权限、窗口或屏幕。

## 私有 JSONL 协议

每条请求最多 8192 字节。严格拒绝重复键、未知键、嵌套值和未知版本。以下请求中的 auth 省略值只是文档占位符，实际必须为 64 位小写十六进制：

```json
{"schemaVersion":1,"requestId":"unique-id","action":"probe","auth":"..."}
{"schemaVersion":1,"requestId":"another-id","action":"capture","auth":"...","targetToken":"probe-returned-token"}
```

原生“诊断微信窗口”面板另可请求 `listWindows`，回包 `status=windows_ready`，包含至多 64 个 `windowCandidates[{id,pid,pointBounds,layer,onScreen,mainTitleMatches,sharingState?,alpha?}]`。只列出严格原微信安装路径、bundle ID 与可靠进程身份的窗口，小窗口也可列出元数据；不含标题、应用名、路径或截图。可选 `sharingState` 和 `alpha` 仅来自对该窗口 ID 的 `CGWindowListCopyWindowInfo(.optionIncludingWindow, id)` 中 ID/PID 都匹配的唯一记录，缺失或歧义则保持未知。它们仅为原始测量值，不证明内容保护，也不控制捕获方式。超过 64 个候选时返回 `window_limit`，不截断结果。该动作不产生 token，并使旧 token 失效。

用户在原生面板选择候选后，`probe` 可额外带 `windowId`（JSON 正整数，最大 UInt32）。只接受当前原微信枚举中的唯一指定 ID，再检验 layer-0、有限尺寸、至少 200×120、图像上限及完整身份。显式选择可覆盖自动主窗口选择；它仍只允许读取，后台遮挡固定 unknown。其他 action 禁止携带 `windowId`。

诊断面板可用该 probe 的一次性 token 请求 `capturePreview`。它复用普通 capture 全部捕获、OCR、前后身份及权限验证，再额外返回 `previewPngBase64`：同一 CGImage 本地编码的 PNG，不缩放、不落盘。压缩 PNG 最多 4 MiB，超限返回 `preview_limit` 且无部分结果；完整 JSON 回包最多 6 MiB。成功状态仍为 `ocr_ready`/`ocr_empty`。普通 `capture` 永远不包含 PNG。预览应仅在原生面板内存显示，不发送到 Web/Host、日志或网络。

仅 `capturePreview` 可另带 `previewVisualStats{sampledAlphaNonzeroFraction,nearWhiteFraction}`。它从同一 CGImage 以最多 64×64 点、nearest-neighbor 的透明 RGBA 缓冲测量，不再次捕屏。两个比例的分母均为全部采样点：前者计 alpha>0，后者计 alpha>0 且去预乘后 RGB 三通道均至少 250/255。完全透明像素不计近白；全透明得到 0/0，全不透明白得到 1/1。无法取得统计时省略该对象，不据此猜测保护状态。普通 capture 不返回该对象。

`probe` 只执行三项不弹窗的权限检查和窗口元数据验证，返回 `ready`、`targetToken`、`targetExpiresAt` 和窗口身份。没有屏幕权限时直接返回 `permission_required`，不枚举窗口。token 十秒内一次有效；任意失败、再次 probe、权限请求及 capture 尝试都会使旧 token 失效。

仅在用户点击原生“授权屏幕读取”菜单之后，原生客户端可以发送：

```json
{"schemaVersion":1,"requestId":"explicit-menu-click","action":"requestScreenPermission","auth":"...","authorizationIntent":"user_clicked_native_menu"}
```

此分支只在尚无屏幕权限时调用 `CGRequestScreenCaptureAccess`，不会枚举窗口或捕屏。`permission_granted`/`permission_requested` 仅表示当前权限状态或已发起系统请求。用户自行处理系统开关，随后重新 probe；不自动请求辅助功能、事件发布或输入监控权限。Web/Host 不应暴露这一 action。

原生主菜单另可显式发送 `chooseWindow`，同样必须有 `authorizationIntent=user_clicked_native_menu`，禁止携带 windowId 或 token。它要求既有屏幕权限，绝不调用权限请求；macOS 15.2 以下返回 `unsupported_picker_os`。选择器仅允许 `.singleWindow`、禁止随后更换内容，并以运行应用的 bundle ID 排除所有非原微信（无名字/标题输出）。最终仍严格校验 OS filter 的 style 为 window、includedWindows 恰好一个、includedDisplays/includedApplications 都为空，再核验原微信路径/bundle/PID/内核启动时间/frame/layer/尺寸/显示器交集。

成功返回 `ready`、标准 window 身份和十秒一次性 token。后续 capture/capturePreview 仅使用 OS 返回的原 filter，不重新构造或换成显示器 filter；每次重新核验选中窗口。默认 probe 复用时固定该窗口重验，不自动换窗；显式选择另一 windowId 会清除系统选择绑定。任意身份变化、失败或显式权限请求均清除 filter。成功后 observer 与事件泵立即清理，picker active 保留至绑定清除时显式关闭；SDK 头文件未保证 active 对授权的具体影响，须实际系统验收。

仅 chooseWindow 的标准回包可带 `pickerDiagnostics{stage,osErrorDomain?,osErrorCode?}`。stage 固定为 `picker_start`、`filter_shape`、`filter_identity`、`post_selection` 或 `ready`。只有实际 `contentSharingPickerStartDidFailWithError` 回调才填写 OS code/domain；domain 限 1～128 个 ASCII 字母、数字、下划线、点或连字符，不合法则省略。`picker_start` 且没有 osErrorCode 不证明系统失败回调已发生或选择器已展示。未取得标准回包的 transport 错误由原生客户端自身报告。所有路径不读取 localizedDescription/userInfo，不输出私有错误描述、标题或路径，也不写全量日志。

用户取消返回 `blocked/picker_cancelled`（非 fatal）；整个 choose 请求（含选择与随后身份/显示器枚举重验）共用 120 秒绝对预算，超时返回 `blocked/picker_timeout`（fatal，助手退出）。取消和超时均清理 observer、事件泵与 picker active。超时不等待 SDK 迟到回调；operation 取消、generation 与取消检查共同阻止迟到回调重新写入 filter 或 token。私有 stdin 读取在独立 actor 上，避免阻塞 MainActor；NSApplication 初始化与每次最多 32 事件、随后异步让出十毫秒的事件泵，仅在显式选择期间启用，不进入 NSApplication.run。合成测试不创建或展示真实系统选择器。

助手仅监控已验证直属父 PID 的 `.exit` 事件：父异常退出时立即结束助手，由系统回收其 picker/授权上下文；注册后再次核验父身份。父仍存活但只关闭 stdin 的情形没有竞争读取器，当前 choose 最多等待上述 120 秒预算，然后在下一次读取发现 EOF；正常主程序关闭仍直接 terminate 子进程。

回包固定 `schemaVersion=1`，包含 `helperInstance`、`requestId`、`status`、`fatal`。启动前身份拒绝可能没有 `requestId`。正常结果包括：

- `permission`：`screenCapture`、`accessibility`、`eventPosting`，分别来自三个只读 preflight/trust API。
- `occlusionStatus`：`clear`、`obscured` 或 `unknown`，不授予输入能力。capture 合并捕获前后与 OCR 后三次观察，任一次 unknown 则 unknown，否则任一次 obscured 则 obscured。
- `diagnostics`：`candidateCount`、`onScreenCount`、`layer0Count`、`mainWindowCount` 仅统计 bundle ID 与规范安装路径都匹配原微信的窗口；`layer0Count` 包含当前不在屏幕上的普通窗口。`mainWindowCount` 统计 layer-0、尺寸有限且至少 200×120、标题精确为“微信”或“WeChat”的主窗口候选。仅在原微信内部检查标题并保留布尔结果，不返回或记录标题。`displayCount` 仅为 SCK 枚举的显示器数量。无目标或多目标回包也保留已取得的计数；不返回其他应用名、窗口标题或屏幕内容。
- `window`：`id`、`pid`、`ownerBundleId`、`processLaunchTime`（Unix Double）、`appVersion`（缺失时省略）、`pointBounds{x,y,width,height}`。窗口坐标为全局左上原点屏幕点，`windowCoordinateSpace=screen_points_top_left`。
  目标窗口的 `processLaunchTime` 来自 `proc_pidinfo(PROC_PIDTBSDINFO)` 的内核启动秒与微秒，严格检查 SDK 结构布局、回包长度及 PID，不回退到 `NSRunningApplication.launchDate`。父助手自身现有 NSRunningApplication 身份前后核验不受影响。
- `image`：`width`、`height`、`sha256`；`capturedAt` 为带小数秒的 ISO8601。指纹只用于此图像身份，不证明滚动、连续性或读取完成。
- `words`：`text`、`confidence`、`bounds{x,y,width,height}`。`coordinateSpace=window_pixels_top_left`；confidence 来自 Vision 行候选，`confidenceScope=line_candidate`，不是单字独立概率。
- `uncertainRegions`：低于 .75 或无候选的区域，仅含 `bounds`、`confidence`、`reason`，不返回不可靠正文。`rectangles` 是原始 `VNDetectRectangles` 证据，含 `bounds`、`confidence`、`source`；不代表输入框已验证。
- `minimumConfidence=.75`、`ocrCoverage=observed_candidates_only`、`messageImport=not_performed`、`inputActions=unavailable`、`screenshotsPersisted=false`。

OCR 可能漏检整块内容，空结果不是没有消息的证据。下游必须保留不确定区域，并由独立可信布局校准验证输入框、标题和侧边栏；原始 OCR 或通用矩形不能自行授予操作许可。

## 读取边界

SCK 枚举使用 `onScreenWindowsOnly:false`，便于取得扩展屏与离屏窗口的诊断计数。所有有正尺寸的可见 layer-0 微信窗口优先按原唯一性规则选择，尺寸很小的模态窗口也会阻断。只有零个可见候选时，才允许唯一的合格精确主标题后台窗口；多个候选拒绝，不猜最大窗。后台目标的 `occlusionStatus` 固定为 `unknown`，仅用于只读。其他应用重叠、未知 layer 或遮挡信息缺失只反映在 `occlusionStatus`，不阻断单窗口只读捕获；不猜测 tooltip/overlay 角色，也不截图其他应用。这里只读取窗口服务器的 z-order、PID、几何和透明度，不读取或返回其他应用标题。未来任何输入必须取得 `clear` 并在执行前重新验证，当前助手无输入功能。

默认编程式 capture 使用 `SCContentFilter(desktopIndependentWindow:)`；显式系统选择成功后使用系统 picker 返回且已验证的原单窗口 filter。两条路径均通过 `SCScreenshotManager.captureImage`，明确排除 child windows、阴影、鼠标与音频，从不回退整屏或显示器 filter。捕获前后及 OCR 后重验目标 PID、启动时间、frame、版本、唯一性和屏幕权限，并观察遮挡状态。窗口元数据中的身份或 frame 不符仍拒绝。系统 API 为离散快照；该检查不能证明快照之间没有瞬时窗口变化，更不构成未来输入操作授权。

probe 与 capture 的每次目标重验均要求窗口 frame 与同次 SCK 枚举得到的至少一个 `SCDisplay.frame` 有严格正面积交集；仅接触显示器边缘不算相交。构造 `SCContentFilter` 前再次执行同一检查。完全离屏返回非 fatal 的 `blocked/off_display`；显示器范围缺失、为空或包含非有限/无效几何时返回 `blocked/display_context_unavailable`，不会通过重启或整屏回退继续捕获。扩展屏负原点和跨屏窗口只要有正面积交集仍可读取。窗口列表可显示离屏窗口元数据，但不能据此跳过捕获前检查。

图像上限 8192 单边、16777216 像素；OCR 上限 4096 words、单词 512 UTF-8 字节、总文本 65536 字节、64 个矩形。超限不返回部分 OCR。系统异步调用八秒超时后 fatal，主程序必须销毁实例。OCR 图像、预览 PNG 和正文只驻留内存，不保存截图、诊断正文或网络上传；stderr 和崩溃 core dump 关闭。

## 验证边界

`python3 -B tests/ScreenReader/test_synthetic.py` 仅生成 CGImage、运行本机 Vision 和假窗口 provider，验证拒绝输入、唯一目标、遮挡、坐标、低置信区域、限制、指纹及显式权限 action 的分支。它不实例化真实窗口 provider，不调用真实屏幕权限或 capture API。真实系统授权归属、真实微信窗口兼容性和原生菜单接线须由主流程另行验收。
