> Portable API source snapshot: identities, installation evidence and paths are anonymized. Earlier per-peer/client ACL and forced-prefix sections are historical; use current Policy v2 source/capabilities. No source text grants access to an account or host.

# 当前授权与执行约定 · 本人2026-11-06更新

本源码记录原安装当时的微信能力；其授权不随代码包转移。新安装须由自己的操作者按实际职责与合法工具权限使用。员工按来源、负责会话和实际职责完成读写、消息、文件与必要原生操作。client仅归属记账，不是权限租户，不逐群/动作再申请。SDK用于提效；误拒/缺配方可用原官方微信、已有原生输入或CUA接续，不以先加白名单、完善全部工具或再获本人许可为前置。旧“只能SDK/不得原生备用或compose/CUA/每peer动作登记才有权/前缀强制拒绝”等限制已退役。

保原业务意图、真实收件人/文件与原ID去重。SDK ID未建不等于现场无人，已有操作者先直接协调，不能另代第二份。accepted/unknown只核原单；手工留实际原生ID及操作/文件证据，不改canonical或伪写SDK成功。未返回Send/系统调用不抢占，只收自己的正证现场。后台恢复不误套READY_BUSINESS为权限拒绝，逻辑状态不能代替实际现场检查。

已实装Policy v2：全client的peer/action/source名单拒绝、resolve客户名单过滤、client注册拒绝与强制前缀已解除。大小、格式、资产复用、默认确认和逐联系人校准等残余实现门槛仍在同项解除；真实差量见 `/var/lib/secretary-workspace/work/20261105-mac-sender-stall-recovery/owner-authorized-access-release-20261106/`。不宣称所有门槛已清；实际微信/系统条件继续如实报告。

以下保留旧协议及验收史，其中上述旧硬限制不再指导当前权限/工作方式。API尚有manual状态时，已有授权AI自行核预览/确认，不另请本人批准；包装层未支持不禁止原界面。共享代码/配置由原维护统一处理，业务稿和唯一交付归原caller。

2026-11-06 19:36现行补正：普通desktop stop停止本session的精确PID birth传输并记真实场景差异，不再要求重现消失菜单；不会关闭微信窗口或把native cleanup债务写成settled。原worker已接入三类send_text/image/file accepted收尾重试，先核鲜独立原生audit，再沿原composer/navigation/CAS收尾，绝不再次prepare/Send；unknown与不支持动作债务仍保留。原unit既有Restart=always/5s保持、启动限流间隔改0。实际版本/边界见 /var/lib/secretary-workspace/work/20261105-mac-sender-stall-recovery/owner-authorized-access-release-20261106/self-cycle/RESULT.json。

---

# 微信写工具接口 · V2

适用版本：apiVersion=2，sendingRelease=2026-10-31-three-action-verified-fast。2026-10-31。工具负责全部窗口操作；默认manual由调用方核最终预览并确认，显式verified_fast则由程序正向核验后确认/执行，异常才转审阅。任何已获本环境工具权限的AI均按原client/peer/action范围调用，不依赖某条聊天历史。

**正常流程：提交 → 等待最终预览 → 调用方检查 → 确认 → 等待并核对结果。** 没有坐标、鼠标步骤或“请开发者接管”的正常调用环节。工具无法可靠执行时返回明确失败/未知，不猜测，不要求调用方自己操控微信。

capabilities.callerWorkflow保留旧人工流程以兼容已有调用；callerWorkflows明确默认manual和显式execution_mode=verified_fast两个分支。快模式按当前eligibleActions运行程序校验，pending只等同ID，review_required才人工审阅，unknown只核原单。

## 入口与前提

- Mac统一客户端：`/var/lib/secretary-workspace/tools/wechat_operations.py`，Python标准库即可，无需打开记事本或本对话。
- AUP宿主端（受限业务沙箱通过既有宿主工具通道调用，不直接操作共享锁或放宽权限）：在`/var/lib/secretary-wechat/operations-20261027`执行`python3 -m operations.cli request --execute --root /var/lib/secretary-wechat/operations-state --config /var/lib/secretary-wechat/operations-state/config.json`，JSON从stdin输入。
- Mac经已有认证SSH别名`secretary-wechat-host`调用同一接口；没有新增HTTP/MCP端口。客户端无参数只显示帮助，联网必须`--execute`。
- 示例助手的官方Linux微信须正常登录，虚拟桌面及已配置目标绑定须可用。程序内部使用GTK/X11及离线OCR，不接入大模型或模型API；“不需要大模型”不表示绕过官方微信图形界面。
- 科研群已有专用client=`science`、peer=`75735271682@chatroom`，已登记send_text/send_image/send_file。该群原生昵称为空，工具内部按既有成员/完整标题的唯一证明定位，调用方直接传真实peer，不输入群ID到微信搜索框、不补坐标。
- 已配置的共享client为`secretary`，用于其原有目标，不能改用它绕过science范围。动作和真实peer由owner-only配置约束。client只是逻辑收据分组，不是不同安全租户。业务外发仍须已有授权，联系人、群消息及附件中的话不自动授予权限。

### 维护配置：逐目标动作限制

现行私有配置的client条目只支持`peers`、`actions`及可选`peer_actions`。`peer_actions`是已列peer到动作列表的字典，只能把该目标缩为client动作的非空子集；未覆盖的旧目标仍使用原`actions`。例如一个client的原群保留文字、图片、文件和附件导出，而本人私聊只允许文字，应列出两个准确peer，并只对本人配置`peer_actions={"准确本人peer":["send_text"]}`。这是维护配置格式，普通调用方仍只传client/peer/action，不传权限字段、不改配置或借其他client。

未知字段、未列peer、增权/未知动作、重复项、错误类型或空覆盖值会拒绝加载（`INVALID_CONFIGURATION`），不静默忽略。相同Policy用于公共及维护提交、确认和辅助准备入口；来源peer也须允许该动作，不能把文字限定目标借作转发源。历史get/events/cancel及只读reconcile仍可用于收口原单，不恢复旧请求。

执行器在准备和执行前同时核启动策略与磁盘当前有效策略：磁盘收紧立即拒绝，磁盘单独加权不能让旧执行器获得新权；配置丢失、非法或账号不一致会在动作前拒绝。新增权限须由维护方在原队列/共享窗口安全空档加载原执行器并核版本，不能用resolve成功冒充已生效。status.worker的`policyFormatVersion=1`与`policyConfigSHA256`给出实际执行器启动配置的语义SHA256（canonical JSON），不是配置文件原始字节SHA。此功能不改变账号、原生目标/预览校验或client并非独立安全租户的边界。

## 本人私聊新稿的员工前缀 · 2026-11-03

按共同digital-employee约定，示例助手向本人准确DM `wxid_fixture_c2253ec460` 发送的每条新撰写文字/文字回复，在原作者冻结前以`[员工当前称呼]`开头。现已核原client责任：`secretary`使用`[总秘书]`，`employee_method`使用`[人事负责人]`，`organoid_bp`使用`[示例项目BP]`，`aup_support`使用`[AUP运行支持]`（该client仅本人DM/send_text）。代理发送沿业务原client及原作者称呼，不署发送员或微信物理账号。其他作者没有可靠当前对应时交原作者核稿，再由原维护依据已有ROLE事实更新同一表达规则；不能从正文标签猜身份、借client或扩大权限。原入站旧称兼容不变。

检查在原Store的submit/admit新行INSERT之前，并在旧同ID查回之后；普通SDK和默认/verified_fast流程都经过该入口，不增加AI回合或修改冻结正文。同ID/同正文已有请求、旧queued/confirmed/executing/unknown/成功等原行按原方式核账，不因新规则重新验证前缀或重放。原有ID换正文仍REQUEST_CONFLICT。

新稿遗漏返回`OWNER_DM_PREFIX_REQUIRED`，当前作者不符（含已更名旧称）返回`OWNER_DM_PREFIX_MISMATCH`，可靠作者对应缺失返回`OWNER_DM_AUTHOR_UNRESOLVED`；表达规则自身无效返回`OWNER_DM_PREFIX_POLICY_INVALID`。这些是稿件表达检查，不是新权限拒绝；details给`jobCreated=false`、`textRewritten=false`及已知时的expectedPrefix/authorThreadId。不产生job、事件、UI或Send，原作者可先改尚未准入的稿，再用原未建ID正常提交。SDK保留该明确错误，不把它转成unknown发送或自动加前缀；已存在/unknown原单仍只核原ID。

群消息、其他收件人、读取/取件、图片/文件及原生转发原件不加此前缀、不改字节；需要的随附说明由原作者另按约定定稿。前缀不授予任何账号/client/peer/action权限。当前实际启用状态由`capabilities.ownerDMPrefix`给出；新准入生效时间与原队列序号边界保存在本次加载收据，旧jobs/events保持。资料主源仍为共同协作约定和各原ROLE，有限运行投影由现有机制维护岗维护，不新增员工登记或监听。验收见 `/var/lib/secretary-workspace/work/20261103-owner-dm-prefix-existing-guard/RESULT.md`；隔离入口通过不等于新增真人私聊/手机验收。

## 原队列批量调度 · dispatch v1

以下接口必须先在当前工具 `capabilities.dispatch.version=1`、实际执行器health的 `dispatchVersion=1` 独立核回后使用。源代码或待发布文档存在不表示已上线。仍是原SSH、原Store、原串行执行器，不增加服务、模型、定时或业务授权。旧submit/get/confirm及旧请求canonical body/hash不迁移；未传execution_mode继续manual，只有调用方明确传verified_fast且原程序校验通过才自动执行。

### 正常SDK入口

正常入口只接已定稿文字和已经上传核定的asset ID，不在准入后上传。先完成本批必要资产准备，再按原业务条件补读最新来源／撤回／改稿；无冲突后一次准入。SDK明确拒绝local_file及expected_asset，避免上传结束即自动激活旧业务。无需附件且可独立发送的短回复，应单独先准入，不等待后续大文件准备。

```python
from wechat_operations import dispatch_batch, upload_file

# 只是格式示例。先用原upload_file准备本次原件；上传不发送。
asset = upload_file("configured-client", "/absolute/approved-original.pdf")
# 此处按原业务要求核最新来源、撤回和同稿；有冲突就不准入。
result = dispatch_batch("configured-client", "stable-batch-id", [
    {"job": {"client": "configured-client", "request_id": "source-reply-v1",
             "peer": "exact-native-peer", "action": "send_text",
             "execution_mode": "verified_fast",
             "payload": {"text": "已审的实际回复"}},
     "dispatch": {"kind": "reply"}},
    {"job": {"client": "configured-client", "request_id": "source-file-v1",
             "peer": "exact-native-peer", "action": "send_file",
             "execution_mode": "verified_fast", "payload": {"asset": asset["id"]}},
     "dispatch": {"kind": "delivery", "after": ["source-reply-v1"]}}
], wait_seconds=20, audit=True)
```

普通新文字、内置表情、图片、文件明确选verified_fast，原目标／草稿／资产／单次发送／原生回执校验保持。省略模式仍是旧manual，不能修改旧ID的模式来提速。正常SDK一次SSH准入，内部有界等待和批量核回，不保证全批在一次等待内完成；pending只批量等原请求，review_required／unknown才转异常处理。

SDK没有同步批量上传循环，正常至多一次45秒传输。准入响应丢失时只对原ID做一次只读get_many恢复，不重新admit；恢复也失败则逐ID保留unknown及原ID，最多两次45秒传输，不会乘以文件件数。structured transport字段不代表原消息未发。上传仍用同一流式接口，普通文件没有配置128MiB单件或1GiB缓存总额门槛；持续传输与空闲中断按下文资源检查处理；上传结果不明先核原内容地址，不自动重传、改名、扩额或换消息ID。

同批已accepted、在途或unknown项只返回原状态，即使缓存回收也不由SDK重上传。多件资料准备应分为短准备回合，不持UI窗口；实际已授权、可独立回复的文字先行，附件必须对应的文字／图用ordered、after或unit保留顺序。程序不代替原业务方判断新讨论含义。

### 精确JSON合同

| op | 必需字段 | 可选字段与边界 |
|---|---|---|
| admit | client,batch_id,items | ordered默认false；wait_seconds默认0、范围0..20；audit默认false。items为1..20项，每项只含job及可选dispatch；一批同client，request_id不得重复 |
| get_many | client,request_ids | 1..50个不重复稳定ID；wait_seconds为0..20，audit默认false。不存在的原ID逐项返回REQUEST_NOT_FOUND，不把整批误称未提交；出现可处理的review_required/unknown会提前返回，不为等待队尾而拖住预览审阅 |
| dispatch_summary | client | limit为1..20、默认20。只给该client最近项的ID/peer/action/state/kind/waitingReason/outcome，计数明确为returned_items，并带truncated；不含正文、UI指令或任意路径 |
| audit_many | client,request_ids | 1..20个不重复原ID，仅只读核验，不改变任务状态或补点Send |
| maintenance_eligibility | client | 只读全局保护/就绪业务判断，返回eligible、有限reason及isLease=false；此回应不是窗口租约 |

job与原公共submit相同：client、request_id、peer或to、action、payload、可选execution_mode。批量to解析在同一准入内复用一份已核committed通讯录快照，不跨请求缓存群身份。每项均先走原Policy；任一越权、非法字段、冲突或错误资产声明使全批新插入回滚。不存在逐项半成功准入。

`dispatch`只支持以下字段：

| 字段 | 实际语义 |
|---|---|
| kind | reply / delivery / maintenance，默认delivery。是固定上限的调度提示，不是权限；不接受任意数值priority或最高权限标签 |
| after | 最多20个同client、本次items中已在前面的request_id。拒绝前向引用、环、跨client对象或路径。只有前项实际accepted且无恢复债才能执行后项 |
| expected_asset | 仅图片/文件，精确{name,bytes,sha256}，无路径/client覆盖字段。服务器用原client及原内容地址规则核payload.asset；不存在时等待，不占UI。上传发布、所有权/元数据/完整内容校验成立才就绪。图片和文件限额保持 |
| supersedes | 最多20个明确的同client旧ID。仅旧项仍queued且从未准备、无预览/attempt/step/composer，或事务内确实未提交的旧ID可用。拒绝active/unknown/accepted及任何已动现场；不做语义猜重 |
| unit | 可选稳定ID。一个单元至多4个连续、同class的本批条目，自动加内部顺序依赖，并把单元内声明的外部先决项汇总到首项。所有单元资产就绪才开始；开始后在可继续的安全边界优先完成该单元，再轮到新回复。它不是微信多消息事务，不能撤销已经发出的前项；失败/缺条件时保护原结果，其他独立工作可继续 |

同batch_id绑定相同成员、顺序及元数据；改变则REQUEST_CONFLICT。单个request_id始终绑定原canonical内容/模式；完全相同的普通非unit任务可在另一批被引用，只返回原行/调度/结果，不重新排位或增加发件。修改kind、依赖、原件期望或替代关系拒绝；不能用新batch_id篡改旧请求。旧legacy任务可直接查回，不能事后套新调度。unit不能跨批重新编组。

显式替代保留旧canonical行和事件，并记录replacement关系；被替代的“尚未提交”旧ID保留禁止迟到准入的记录，旧submit也会拒绝，不能在回退代码时丢掉它。不存在的旧ID仍无伪造正文，原get可能保持REQUEST_NOT_FOUND；在新请求dispatch.supersedes及原关系记录核原因，不因not-found就重发。

### 就绪、保护与让路

回复先于普通交付，维护最后。已有等待超过120秒的就绪交付时，冷启动先给老交付一个份额，此后与就绪回复在安全单元边界交替，老化不能让一类独占。没有老交付时，沿用连续3次回复后给已有普通交付份额的上限；老回复也不能绕过这个上限。同class同client的既有轮转继续保留。已开始的至多4项单元在安全边界完成，故突发上限按单元边界计算；不是单条绝对时限保证。缺资产或依赖不成立只阻塞自身及其依赖项。已授权但未登记目标会在UI输入前明确TARGET_NOT_CALIBRATED/noSend，不反复prepare；实际未知窗口/草稿恢复未证仍按原保护保留，不能为了吞吐跳过。

ACTIVE、executing、unknown以及未恢复草稿仍是保护边界，不抢占业务。只有明确kind=maintenance的自有、未attempt项，且未修改现场或原cleanup正向证明已恢复，才可取消让路并保存noSend历史；不能用同样方法取消业务或推断unknown未发送。无就绪项时执行器不获取UI锁。

实际维护领取保留原session.lock、native-ui/shared guard及ownership约定，并在同一原Store事务下核就绪业务后才发布窗口；准入与等待资产的原子发布也经此事务线性化。新业务在维护已合法开始后到达，不代表可以关闭别人的会话。原队列中的受控维护会在可证明干净边界让路；外部维护操作者须沿原约定在安全小步结束时释放，程序不会杀其他AI或清陌生草稿。Mac的owner notice未被删除，eligibility只读快照也不代替真实锁。

2026-11-04同一科研导航事故修正：无名群旧搜索分支在粘贴前记原查询摘要，官方父子身份核实后立即记原弹窗，再运行OCR/候选判断；失败沿原记录收尾。执行器在未解决的`unknown/needs_attention`及`idle/waiting`循环间交还既有executor/native物理锁，重新取锁先运行原中断恢复；不是取消、重放或把保护态变成普通空闲。`uiBusy`同时反映原ACTIVE记录的逻辑保护。旧sender/image/target-picker原生入口共同遵守原active与accepted清理欠账/未结journal屏障，历史delivery只读及原空备份兼容保留。原事故维护者仍须先取原executor锁、核准确原单、再取原native guards并正向收尾；普通调用方继续同SDK和原ID，不能抢窗、force-noSend、改ID或自行清稿。原ready-business优先及账号/client/peer/action不变，未增加API、锁、服务、timer或正常逐项AI审批。

优先级不授予client/peer/action，也不免除业务原有的发前增量阅读、撤稿判断或特定源条件。引用/转发等原生源冻结和重核继续原程序；普通讨论不会由调度器推断成撤稿，新语义或来源条件不明仍交原业务方裁定，不能让程序冒充已理解最新聊天。

### 一次有界独立核验与标准结果

SDK的audit默认true；JSON控制接口默认false，可明确开启。对已accepted的普通文字/图片/文件，从最多20个原请求/20个peer，在一次新的committed原生消息快照中按精确serverId读取，候选总预算40条。须同时匹配原attempt、唯一confirmed/executing事件、peer/本账号sender/status/type/时间/语义及冻结资产；重复回执、来源缺口或证据缺失只报未核清，不再Send。文字沿用原精确比较/单个末LF例外，文件核完整名/大小/MD5；图片核新原生图片身份与原已验证准备，不宣称微信重编码后的原片字节已重新导出验证。不是手机人工实收。

批量返回的lifecycle从原事件表一次有界查询给出createdAt、queuedAt、firstPrepareAt、confirmationAt、executionClaimAt及terminalAt。executionClaimAt是原执行器领取执行的时间，不冒充实际按钮点击；独立audit通过项另给原attemptStartedAt与原生记录nativeCreateTime。SDK给sdkTiming及同机monotonic耗时，用于区分本机准备、控制回应及总耗时；admissionResponseAt可能包含调用方明确选择的有界等待，不能当成实际落库时刻。Mac与AUP的wall clock不可未经校准直接相减，原生时间也不等同手机实收。群入站、业务定稿和回原责任对话的时间仍由原工作流采集。

`sendClicks`是可选字段：其缺失不判失败，实际attempt/event/native证明齐全仍可verified。存在却与事实冲突则保留待核。audit结果allVerified=false表示本次独立核验未全通过，不等于已accepted消息未发送，更不能补发。待执行项、非这三类动作或超出audit预算明确标未核，不扩大原引用/转发等支持范围。get_many超过20项时可正常返回状态，但附audit预算未覆盖说明。

准入/等待/资产上传都不是发送成功。继续按原outcome与真实结果区分pending、review_required、sent/completed、not_sent及unknown；正向从未准备的取消补有noSend依据。流式上传早拒绝现在会排干同一SSH子进程的有限结构化错误，不把BrokenPipe当新的发送机会。ASSET_QUOTA / ASSET_DISK_RESERVE的details给requiredBytes、availableBytes、limitBytes；仍不自动删除缓存或抬配额。旧失败/未知/成功和全部历史保持。

## 最短可用示例

### 2026-11-01：成熟发送的原生定位与收尾闭环

当前 `capabilities.navigation.version=1`，覆盖普通文字/Unicode emoji/微信内置表情（原生type1）、图片与普通文件，仍走同一个SDK、队列和执行器。正常已授权新业务可直接显式选择`verified_fast`；默认manual不变，不新增逐条AI审批。

已登记的准确peer是收件人依据。程序优先使用官方聊天窗的精确系统标题，并结合原生唯一名称、账号/在群关系与原窗口进程身份；动态人数、标题渲染像素和姓名OCR标点不再是这条路径的身份单点。搜索中的首次结果点击仅是导航，未核完新窗的真实系统标题/原生身份前不触及正文。固定的Contacts/Group Chats控件可用已验校准图形识别，必要时保留分区OCR辅助；不选择Internet结果，不按模糊名称猜人。

每个原请求的私有导航记录与原草稿记录共同管理收尾：保留既有窗口及原草稿，只关闭本单确证拥有且为空的临时聊天窗/搜索面板，恢复原主窗几何与焦点。已拥有搜索面板的关闭依赖窗口/父窗/查询归属证明，不要求搜索结果必须被OCR读到。遇原有复合草稿则原样保护；“归位”不等于清空其他人的内容或关闭未知窗口。

`cancel`请求发出但尚未收尾时，`outcome`为`pending/wait_same_request`，可带`cancellationRequested=true`，不再暴露可确认token；继续有界get同一ID直到实际终态。没生成新窗且未触及正文的导航失败，只在原场景恢复可证后按`failed/noSend`收口；不因一个准备错误长期占死后续业务。

成功结果可带`navigationRestored/navigationRecoveryPending/postActionPending`。已原生accepted但收尾异常，仍是已发送，只处理原单收尾，不得补发。程序用私有执行阶段记录区分真正Send边界：正向记录的预发送验证失败可收尾为noSend；已到终端边界的异常仍保留unknown。**普通调用者不得仅凭缺少attempt/回执推断未发送。**历史记录没有新字段不等于故障，不触发重发。

异常结果可带`mechanismReview`：给出原client/request_id/peer、类别和原机制负责人线程。普通成熟业务照常直接SDK；只有当前异常交原负责人查真错/误判并处置，同单/同根已有维护合并。这个字段不是新的维修单或自动后台唤醒，工具不会自行另起模型、服务或队列；也不表示要向本人重新索取已有群授权。unknown只核原单，`accepted-cleanup-only`只修收尾，`preserved-draft`不清草稿。真正影响目标/内容的歧义再带具体事实回原业务方。

明显笔误口误由业务AI在定稿前结合上下文纠正；接口不偷偷改冻结正文、目标或同ID的模式。原生大表情type47仍只有前述已验人工官方路径，未开放公共`send_sticker`；引用、转发、入群等继续各自现有配方，不把本节三动作验收外推为全功能/全布局。

本阶段实证、失败记录和限制见`/var/lib/secretary-workspace/work/20261101-wechat-reliability-closed-loop/DELIVERY.md`；原未交业务须由原业务方核最新源后接续，维护不自动重放。

### 2026-11-01：内部PNG与异步复制、开窗过渡修正

现行接口和正常调用方式不变，仍是同一SDK/队列/执行器。上传的JPEG可能被微信转换为更大的无损PNG；内部复制引用不再套用上传10MB字节门槛。程序先核同账号私有InputTemp路径/文件身份与PNG头，按该尺寸/通道导出内部编码资源边界，再核与冻结源图完全一致的RGBA像素。任意路径、跨账号、符号链接、文件变化、多图或混入正文仍拒绝。

官方复制会异步生成图片格式，程序只发起一次Copy，随后观察原生格式就绪，不再在固定200毫秒后直接误判失败；未证完成的粘贴不能仅凭一帧空白报告草稿已恢复。当前3300×3674/3734604B原JPG对应12208144B原生PNG已实际完成图片准备、像素核验、实看预览和取消归位，0Send；不是原业务已补发。

搜索后先证明选中行/主窗焦点/原窗口集合稳定，成对发送开窗鼠标事件；未出现新窗时只在原请求、尚未触碰正文、原场景仍成立的条件下作至多一次额外导航手势。检测到新窗立即停止后续手势，依原生系统标题/账号/peer独立核验后才可编辑。它不重试Send、不新建业务ID、不放宽身份。生态、社区技术开发两目标均已实际从搜索开出新独立窗，普通预览后取消/归位；历史唯一细因未被重建，也不外推所有版本/布局永久零失败。

准备失败另留不含正文/路径/异常原文的有限阶段和错误类型。公开`result.preparationPhase`只输出固定枚举；已知image-source/image-paste/image-copy-proof归`mechanismReview.category=image-preparation`，不再统称目标或布局问题。

**当前仍未消除的原有限制**：源图片10MB/8192边长/16MP及PNG/JPEG、文字20,000字节等仍在；普通文件128MiB和总资产1GiB已由下方同日资源兼容更新取消；它们是后续兼容改进项，不宣称为微信原生上限。公共原生47/好友等缺口和原暂停范围保持。具体发布/实机/失败与恢复证据见`/var/lib/secretary-workspace/work/20261101-wechat-native-parity/implementation/`。

下面示例展示调用格式。收件人、正文和请求编号须换成本次真实授权内容；不能把示例当成待发送指令。先查`capabilities`和`status`确认版本、支持范围及运行状态。

```python
import sys
sys.path.insert(0, "/var/lib/secretary-workspace/tools")
from wechat_operations import call, save_preview, upload_file, ToolError

call({"op": "capabilities"})
call({"op": "status"})

j = call({"op": "submit", "job": {
    "client": "secretary",
    "request_id": "work-20261027-001",
    "to": "收件人的准确姓名或微信号",
    "action": "send_text",
    "payload": {"text": "这次实际授权发送的正文"}
}})

key = {"client": "secretary", "request_id": "work-20261027-001"}
j = call({"op": "get", **key, "wait_seconds": 20})
if j["state"] == "awaiting_confirmation":
    save_preview(**key, path="/绝对路径/新的预览.png")
```

上面只准备、不发送。打开预览，核对收件人、正文/附件及引用对象；只有正确且已有授权，才在另一次调用中执行：

```python
j = call({"op": "get", **key})
call({"op": "confirm", **key, "token": j["confirmation_token"]})
j = call({"op": "get", **key, "wait_seconds": 20})
```

`get`等待最多20秒，且绝不会替你确认或发送。若仍是queued/preparing/confirmed/executing，继续查询同一个请求。不要因等待超时或SSH断线改用新request_id重新提交。

`to`可用准确名称、微信号或真实peer。也可改传`peer`直接指定真实wxid/群ID；二者只能选一个。独立解析接口为`{"op":"resolve","client":"secretary","query":"准确名称或ID"}`。同名时返回AMBIGUOUS_RECIPIENT及候选，必须先弄清是谁，不选择“第一个”。

### 图片与文件

```python
asset = upload_file("secretary", "/绝对路径/本次要发的文件.pdf")
j = call({"op": "submit", "job": {
    "client": "secretary", "request_id": "work-20261027-002",
    "to": "准确收件人", "action": "send_file",
    "payload": {"asset": asset["id"]}
}})
```

图片同样先上传，action改为`send_image`。`upload_file(client,path)`对超过10,000,000字节的文件自动走原认证SSH字节流；此值只是选择传输路径的阈值，不是文件许可上限。已发布的phase2取消固定单件/总缓存/256MiB额外预留及图像字节/格式/尺寸的人工门槛，按真实磁盘、解码器、OS和官方客户端结果处理。上传接受操作者指定的可读普通文件及相对/~/软链路径，不读业务请求传入的任意服务端路径。原字节和小型描述经同一认证SSH传输，块大小1MiB，临时文件原子入库；SHA256/MD5/原名/字节及原上传client归属保留。现有资产可由其他员工client按准确assetID复用，不重标上传者；原资产身份与真实内容仍逐项核对。大件download/JSON传输不再被旧15MB门槛截断。流式输入仍保留无进展等待检查和原结果响应等待，截断/坏哈希/身份变化不当作成功。上传不发送；默认manual与显式verified_fast保持，未知只核原请求，不盲重传或再发。可解码图像并不等于原生47大表情或所有媒体官方发送已验收。

## 按真实来源读取图片／文件

仍用同一公共入口，不向业务AI开放native-ui.lock，不传坐标、不调用旧维护步骤：

```python
j = call({"op": "submit", "job": {
    "client": "secretary", "request_id": "image-read-stable-001",
    "peer": "真实wxid或群ID", "action": "save_attachment",
    "payload": {"source_id": "真实非零serverId"}
}})
```

`resource_id`可选；给出时必须与此peer/source_id唯一绑定，错误资源不会退回“任选一个”。工具自行辨别普通文件或图片。之后仍是get、取最终preview、核来源与目标、confirm、get；图片导出只有宿主执行器持锁操作官方窗口。下载与图像阅读另行进行：

```python
from wechat_operations import save_output
# 仅在j["state"] == "succeeded"并检查result后：
asset = j["result"]["asset"]
save_output(call({"op": "download", "client": "secretary", "asset": asset["id"]}),
            "/本次调用环境内/新的绝对路径/原图.png")
```

`save_attachment`的完成依据是asset、sourcePeer/sourceId和原件校验，不是新消息serverId；不能用只校验消息发送回执的函数判定读取成功。

### 2026-11-02：已核官方可见文件与连续图读取

`science`在原科研群`75735271682@chatroom`现仅追加了`save_attachment`，原有三个发送动作及其他client/目标/绑定保持。原首次`OUTSIDE_SCOPE`发生在准入前，原请求没有建单，不是unknown发送或调用者用错源ID。

仍是原动作、SDK和串行队列。新可选字段`payload.representation`为`original`或`visible`；省略维持原件模式及旧canonical内容。`visible`只接受维护方已在原私有状态中登记、经官方来源证明的文件；调用者不能传路径或上传一张图自行声明来源。没有该准确源证明时返回`IMAGE_VISIBLE_SOURCE_NOT_VERIFIED`，不猜选连续图。

```python
# 本次真实新读取才使用新的稳定ID；旧不存在/失败历史不改。
j = call({"op":"submit", "job":{
    "client":"science", "request_id":"new-exact-visible-read-id",
    "peer":"75735271682@chatroom", "action":"save_attachment",
    "payload":{"source_id":"exact-source-id", "resource_id":exact_resource_id,
               "representation":"visible"}}})
# 原manual流程：get -> save_preview/检查实际图及源元数据 -> confirm一次 -> get。
# accepted后用同science client下载result.asset，实际打开后再称业务已读。
```

已核文件复用分支逐次重核当前原生账号、peer/sourceId、sender、时间、本地消息号、原生MD5/图片长度和资源绑定，以及原上传者归属保留的资产完整SHA256/MD5/大小和解码尺寸；仅client归属不同不阻挡同源复用，其余来源元组必须一致。来源证明同时包含准确官方群与Save默认文件名的时间戳、本地消息号；不靠外观/排序认源。准备预览仅呈现这份已验图与来源标签，不截取无关聊天。确认时再次核源、证明和资产未变；没有新UI输入或重复导出。

结果明确给`representation`、`nativeSourceMD5`、`nativeMessageMD5Matched`、`originalFileVerified`、`sourceContextVerified`、`cacheReused=true`、`exportPerformedThisRequest=false`及`messagesSent=0`。`official-visible-variant`不是MD5匹配原件；默认原件模式不会因已有可见文件而放宽。完整文件、截图、拍摄端原片和画外资料是不同范围；科研方仍需逐张打开并保留手写模糊处。

本次四个连续源已有准确可读文件，前三源完成正常公共SDK真实prepare/预览/confirm/download验收，第4复用此前已交文件未重取测试。该分支支持这些已有来源证明的连续图，**不是任意新连续图片的通用图库自动定位**；未验新源的官方首次取材仍需准确来源证明。旧的单图双文字锚点＋MD5原件导出路径保持。证据：`/var/lib/secretary-workspace/work/20261102-science-note-images-readable/continuation-main/`。

文件后缀以result.format/name为准。保存成功后由业务AI实际打开原图，再记录语义已读；预览截图、导出回执或可下载字节均不等于业务AI已经看图。

图片当前支持边界：

- 仅当前校准的905×667官方主窗口。原生目标在最近200条记录内，紧邻前后两条均为与图片同发送人的文字；去开头明确@称呼后的正文各自唯一，长度4..160字符。重复锚点、连续多图、无明确发送人拒绝。
- 双锚点与其中唯一完整图片卡必须在当前聊天画面可见。不自动滚动猜历史图；不在当前可见范围、裁切、多候选、未知背景/布局均明确失败。正文逐字匹配（仅折叠排版空白），不做语义近似或取第一图。
- 准备阶段只定位/冻结原生上下文与画面；确认后重新核标题、窗口和冻结画面，再走现有官方Save As。必须与源消息MD5一致并真实解码成功；不再套用旧字节/格式/边长/像素配额。密文、损坏文件和缩略图替代品不能通过这些核验。
- 结果包含sourceId/sourcePeer、sender、resourceId、format、width/height、bytes、MD5/SHA、nativeMessageMD5Matched、sourceContextVerified、contentReady、origin、exportPerformedThisRequest、cacheReused和messagesSent=0；businessAIReadClaimed=false。原始XML鉴权字段不返回。
- `origin=official-client-save-as-programmatic`表示该请求实际重新走了程序化官方导出。本版不建立跨请求图片缓存；同一稳定请求的get/download复用原有已核收据/资产，不能把再次查询说成又导出了一次。新请求不会直接读取先前维护导出的PNG来冒充新图自动读取。
- 场景变化或无法证明导出/清理时不返回图片字节；unknown只查询/reconcile，不新建ID重复尝试。原文件导出流程及旧历史保持。

## 请求结构

```json
{
  "op": "submit",
  "job": {
    "client": "secretary",
    "request_id": "stable-operation-001",
    "to": "准确收件人",
    "action": "send_text",
    "payload": {"text": "精确正文，保留空格和换行"}
  }
}
```

| 字段 | 约束与含义 |
|---|---|
| client | 已配置逻辑调用方，不携带凭据；已有共同使用标签是secretary |
| request_id | 同一次业务尝试的稳定英文ID，字母/数字开头，后续可有点、下划线、短横线，最长96字符 |
| to或peer | 准确收件人；二选一。peer必须是已有授权范围中的真实wxid或群ID |
| action | 下表所列业务动作；没有method、point、step等操作字段 |
| payload | 动作专属载荷；text精确保留UTF-8内容，最长20000字节 |
| execution_mode（可选） | manual或verified_fast；省略保留旧人工确认及原哈希，显式快模式范围见下节 |

相同client/request_id及完全相同规范化内容返回原请求，不再次执行；同ID更换收件人或内容返回REQUEST_CONFLICT。失败且noSend=true时，调用方可在明确需要重新尝试且原因已处理后创建新的业务请求；unknown绝不能这样处理。

## 动作范围

| action | payload | 当前程序行为与边界 |
|---|---|---|
| send_text | text | 自动定位、输入、实际草稿读回、最终预览；确认后发送并核原生正文 |
| send_image | asset | 核编辑器中唯一原生图片及解码像素与上传资产一致，再给最终预览；确认后发送、核新图片记录；微信可能重新编码，不宣称原片字节保真 |
| send_file | asset | 官方文件选择器准备；最终预览后发送；核文件名、大小和MD5 |
| open_chat | {} | 工具定位已配置目标，预览后确认；不发送消息 |
| open_message | source_id | 内部定位明确原消息；限定已支持的消息类型与有界范围；找不到或有歧义则明确失败 |
| reply | source_id,text | 内部定位、选引用、填正文；最终预览包含引用；确认后核被引用serverId |
| forward | source_peer,source_id | 内部定位原消息、选择单一收件人；最终预览后提交；核正文/文件等身份 |
| join_group | inviter,source_id | 内部解析邀请、核群名与最终按钮；已在群则只核关系；新加入还需可识别的支持布局 |
| save_attachment | source_id,resource_id可选 | 普通文件走原精确缓存路径；图片走当前可见唯一双锚点＋官方Save As＋原生MD5，返回可下载资产；不能证明时明确失败 |
| get_group_qr | {} | 对本client明确允许的准确现有群，核原生成员关系，打开官方群码并给最终预览；确认后复制原生PNG、逐像素核码图、返回私有asset；不发群、不代表有人已加入 |
| mention / request_friend / accept_friend | — | 当前V2普通入口明确UNSUPPORTED_ACTION。旧版维护入口有辅助能力，但尚未完成本版程序化/实机验收，不把它们伪装成调用方UI任务 |

source_id是服务器消息ID字符串，不是localId。读取原消息仍使用独立微信读取工具，不能用猜测的ID。source_peer和inviter也受client可访问peer范围限制。短文字和普通文件卡仍沿近期标签唯一性定位。公众号文章卡还支持下述原生来源日与官方聊天记录定位；重复标题、超出近期200条本身不再直接排除这条路径。无法建立准确来源映射时保留具体缺口，不按近似内容发送。

### 2026-11-01：公众号原卡的普通 forward 路径

仍使用 `forward` 和 `payload={"source_peer":"来源peer","source_id":"准确serverId"}`，省略执行模式即 `manual`。不新建分享动作，也不把URL文字当原卡。

- 来源先从原生精确ID读取完整标题、URL、发送者与日期。唯一标题可沿原定位；重复标题可用该来源日内原生唯一的准确标题前缀，结合官方“聊天记录→Links”中的日期定位原卡。完整标题和URL仍冻结，并在原生出站回执中严格比较。不能偷偷换成同标题的新来源ID。
- 收件人保留原生唯一目标、账号、当前群关系、既有登记及来源范围校验。选择器输入完整原生群名并复制读回。中文绿色匹配文字的OCR不再单独决定目标身份；必要时联合官方本地“Group Chats”分区、唯一结果勾选控件及唯一已选收件人验证，给出最终中文预览。该分支必须由调用方实际审阅并通过原 `confirm` 确认，不能自动快发或任选首个相似结果。
- 来源预核、历史窗、选择器和原有窗口均记在同一原单的准备阶段记录中；失败、取消按正向归属证据收尾。成功与收尾异常分开，未知只核原请求。维护不为恢复界面重发卡片。

本轮准确原卡已完成程序准备、实际最终中文预览检查及取消归位；维护为就绪业务让路，原单终态 `cancelled/noSend`，无 `confirmed/executing/attempt`。这证明该受控布局的准备与收尾，不是公众号卡已实发、全目标转发覆盖或手机验收。真实业务仍逐群查重、看最终目标与卡片后确认一次，并核原生type49/appmsg5的标题及URL。`verified_fast`继续只覆盖原三个基本发送动作。

后续正常业务已有一条原生app5卡片accepted回执，并已按原单核回收尾；它不是维护测试。当前接口支持来源当天在历史列表显示的原生`HH:MM`标签，并纳入历史列表首行，仍联合来源日唯一记录定位，不按同标题或首行任取。更换业务来源须由调用方在新业务请求中明确给出source_id，工具不会改写旧请求的来源。

2026-11-02收件人筛选补充：过滤结果中出现完整原生名称的精确匹配时，先保留所有精确行，再判断是否唯一；不把另一个带数字括号的名称也去尾数并入。重复精确行仍拒绝，不按行序取第一项。未出现完整名时，原有受控人数显示兼容与唯一当地结果规则保持。本次A15准确目标已在官方选择器中实证：完整名与带`(2)`的两行同时可见，程序仅勾选完整名，唯一已选收件人及空附言均核完，随后取消归位；未准入新业务、未confirm/Send。这是当前准确目标的准备条件，不是剩余文章已经送达或全布局长期验收。证据见`/var/lib/secretary-workspace/work/20261102-forum-A15-recipient-filter-review/continuation-1322/RESULT.json`。

原生成功后仅对同一原单的已证自有收尾作最多四次检查/收尾，间隔0/100/200/400ms；不再执行发送，也不对unknown调用成功收尾。搜索框焦点外观变化时，可在非编辑焦点归位后核原字段的完整像素一致，或核已验证的完整空字段；不清未知查询、不跳过窗口/草稿归属验证。仍不能正向证明的收尾保持pending，成功回执不因收尾异常重发。

2026-11-02同项补充：共享基准支持官方空搜索的“Search Results／Articles, Official Accounts, and Channels／Recent Searches”布局。仅识别公共标签区域，不读取下方私人近期搜索词；仍须原生父窗/PID/class/leader、精确几何及操作前画面冻结全部通过，才作非编辑失焦收尾。此识别不能用于从近期记录或互联网结果选择收件人。普通导航的两种已实看完整空字段外观在原快照和当前均可核为空时直接视为归位，避免为比较空框而再打开搜索面板；非空或未知字段不放行、不清除。

本补充已差量加载，保存的真实界面公共标签经原OCR和候选识别器回放通过；空字段恢复也已用于现有真实成功单的同单收尾，未新增消息。没有为验收重新造一个空搜索现场，所以不把离线匹配、既有现场人工失焦和候选原单收尾混称为所有布局的自动化长期验收。普通文字/图片/文件的既有快模式与收件人原生分区校验保持，未知modal仍保护。

动作的程序实现、受支持布局和实机验收是不同维度；以`capabilities`与本次实际返回为准。

## 表情、引用、分享卡片与好友的实际边界（2026-10-31核查）

`capabilities.messageMethods`区分动作名与原生消息类型；它描述程序支持范围，不代表每种对象均有真实发送验收。

**已可用的内置表情无需新接口。** 将 Unicode emoji（如🙂、🤝）或微信内置表情代码（如`[微笑]`、`[握手]`、`[流泪]`、`[捂脸]`）保留在`send_text`的`payload.text`中，按原有预览、确认和原生回执流程发送。例如`{"text":"这句感谢先收下[流泪][流泪]"}`只是载荷示例，不是待发送任务。上述已测样本不代表全部表情代码均已验收。自定义大表情、收藏贴纸的原生type47目前仍`programmatic=false`；不要对外宣布该接口已补齐。

| 需求 | 正常调用方法 | 当前可证明的范围 |
|---|---|---|
| Unicode emoji、微信内置方括号表情 | `send_text`，正文保留原文字 | 原生type1；受控样本已有原生回执及本人手机确认。它不是自定义大表情。 |
| 已有／收藏的原生大表情 | 当前无公开程序化动作；已有官方搜索＋人工最终预览路径，见下节 | 11月1日受控本人样本已真实发送原生47，源MD5与唯一新回执精确匹配。收藏自动选择及无人审阅程序配方仍未验，`programmatic=false`；不得用图片/GIF冒充。 |
| 引用回复 | `reply`，payload为`source_id,text` | 原消息限可唯一定位的短文字或标题；结果必须是type49/appmsg57且引用的serverId准确。不是把原文复制到正文。 |
| 单条文字转发 | `forward`，payload为`source_peer,source_id` | 已有受控单条文字实机回执；完整正文匹配。来源与收件人均受同一client范围约束。 |
| 链接／公众号文章卡片转发 | 同一个`forward`，不另造“分享”入口 | type49/appmsg5核完整标题＋URL；来源可用唯一标签或上节的精确来源日/官方历史定位。已有受控准备取消及一条正常业务原生accepted记录；无额外维护试发，不等于所有来源/布局已验，不能将URL文字或准备成功记成原生卡送达。 |
| 普通文件卡片转发 | 同一个`forward` | type49/appmsg6核文件名、大小、MD5；源定位及目标仍须通过。本轮未新增文件转发实发验收。新上传原文件仍用`send_file`。 |
| 图片、视频、小程序、合并聊天等转发 | 不从`forward`动作名推断可用 | 图片核验器有部分底层代码，不等于现有定位配方支持图片；其他卡片/媒体/多条合并未作通用承诺。 |
| 发好友申请／接受新好友 | 普通入口仍`UNSUPPORTED_ACTION`，不排队 | 旧辅助代码不等于无坐标公共配方。新请求准备、申请待通过与当前好友关系要分开；目录存在或零聊天不证明好友关系。11月1日已依本人授权向准确群成员提交一次申请，官方显示Request sent／Pending Verification；尚未证明互为好友，接受申请无新样本。 |

调用格式仍是同一队列：

```python
# 只是格式示例，不是发送指令；替换为这次真实授权的目标与来源。
job = {"client": "本次client", "request_id": "稳定且唯一的本次编号",
       "peer": "真实收件人peer", "action": "forward",
       "payload": {"source_peer": "真实来源peer", "source_id": "真实serverId"}}
# submit后只等待并打开最终预览；确认前不会替调用方选择发送。
# 结果unknown时只查同一个请求或reconcile，不能第二次点击、换ID或换媒体重发。
```

原生大表情当前的现场缺口已经做过受控核查：官方收藏页为空；可读的真实收到表情不等于已存在可调用的收藏选择入口。不能为了验收偷偷安装表情包、修改收藏，或把截图/GIF当type47。即便后来有收藏，也还须证明收藏身份、官方选择映射、准备不误发送、取消及原生回执，不能仅有一个MD5就宣称接通。需要调用方判断的是最终业务预览，不是坐标或内部控件步骤。现有短Skill继续只指向本手册。

### 2026-11-01：官方窗口路径的实际新验收

原生大表情已有一条真实端到端实发：本人已提供的“吃瓜”样本，原source_id=1542412405058203822、原生47。官方表情面板的收藏仍为空，但**Search Stickers可用**；输入已核的“吃瓜”，在搜索结果实际看同一粉色兔子和放大预览。只在正确本人私聊、空编辑器、明确本次授权、原生发送前基线和稳定本地操作ID保存后，最终单击这个结果一次。新消息serverId=1710475801474306247，原生47、示例助手/本人peer/status2，MD5=359a4c1b70213530442f3699d7f1be70与原source精确相同。没有用PNG/GIF文件替代，也没有安装表情包、改收藏库或重发旧业务。手机人工实收尚未确认。

这条路径已经证明“官方搜索中已有原生表情可以发送”，不能继续说收藏为空便完全不能发。它仍需操作者实看并选准素材，不是无坐标公共`send_sticker`动作；capabilities.nativeSticker.programmatic继续false，manualOfficialSearch.verified单独记真实范围。普通调用方需给准确授权目标、已有源ID／表情描述及必要身份，交既有发送／机制协作处理；不得向公共接口编造send_sticker、借send_image冒充、直接点击相似的第一个结果或把这一次样本推广到任意包／动画／布局。程序化收藏/结果身份映射尚欠验，不能假称接口全部补齐。

好友申请已有官方路径实测：fresh核本人明确允许的群中唯一非好友成员，从群设置的准确成员打开资料，Add to Contacts进入**可取消的**Send Friend Request，核对象、原问候语和最终预览，选择Chats Only减少资料分享，OK一次。官方New Friends→该对象显示Request sent和Pending Verification，来源Group chat；独立committed联系人好友flag仍false，准确报告申请已发、等待对方通过。不是互为好友已完成。当前公共request_friend/accept_friend仍UNSUPPORTED_ACTION，实际收到授权对象的申请前不宣称接受功能已实测；不重复申请、不批量加人、不把目录存在当关系。

群二维码：既有官方Group QR Code→Save取得的完整PNG，已用本机Vision实际解出唯一https://weixin.qq.com地址并保留私有哈希。这个步骤证明读取／保存／解码链，未证明服务器当前有效或已经扫码加入；二维码令牌不放进日志或其他群。本人允许加入的两个指定群，目前未取得可证明属于它们的有效邀请/二维码，名称授权不等于已有可点击对象；取得准确材料后再核群身份／邀请人／有效期与实际成员关系，不能猜群或绕过审批。邀请其他人进入某群另需明确被邀请者和目标，不因本轮读码而泛邀。

本轮证据：`/var/lib/secretary-workspace/work/20261031-wechat-complete-methods/night-20261101/`。分清官方手动路径、公共程序接口、申请待批准与完整关系验收；无新服务、队列或常驻监听。旧请求和所有业务暂停保持。

### 2026-11-02：现有群二维码的原SDK动作

`get_group_qr`已接入同一公共API、Store和原串行执行器。它是读取／导出操作，使用默认manual最终预览；调用AI核正确中文群及二维码后确认，无需让业务方提供坐标或让本人再确认。secretary原人才筹备与2026社长团已有私有导出验收；现另将准确既有“他山科学智能社区2群”（88982197529@chatroom）登记为仅`get_group_qr`，供原业务方正常manual准备、看码、确认及私有下载。该群已独立核原生成员、群主和实际官方完整标题，本次登记未导出或刷新二维码，也未给它文字、文件、转发等其他动作。其他旧目标的有效动作范围未扩大；任何新目标仍需自己的准确关系／标题证明，不能借其他群的登记。内部人才／社长团码不作为官网入口，社区2取码后的公开采用由原业务另行核定。

```python
# 格式示例；使用真实授权的准确现有group_peer和新的稳定request_id。
j = call({"op":"submit", "job":{
    "client":"secretary", "request_id":"new-authorised-group-qr-id",
    "peer":group_peer, "action":"get_group_qr", "payload":{}}})
# get同一请求，save_preview后核群名/码图，再confirm一次。
# succeeded后：
asset = j["result"]["asset"]
save_output(call({"op":"download", "client":"secretary", "asset":asset["id"]}),
            "/absolute/new-private-qr.png")
```

目标由准确原生peer、当前在群及示例助手实际成员关系、原窗口身份和本请求新开官方QR窗的对应关系证明；中文OCR和人数不是新的身份门槛。程序只用公共控件标签定位，复制后的PNG中码图区必须与官方显示逐像素一致。返回asset含SHA256/MD5/bytes，不返回邀请令牌。当前校准导出为375×568原生PNG；未知布局保留现场，不以相似图或别群二维码代替。

`messagesSent=0`、`joinVerified=false`；`decoded=false`指服务器未装解码器，不能误读为图片无效。独立Mac Vision解码须另存私有证明；官方显示的有效期保留在原PNG中，服务器`expiresAt=null`不猜时间，更不证明微信服务器接受扫码。导出成功与自有QR窗／侧栏／导航收尾分别记录；accepted后的收尾待核只处理原单，不重新复制或另发消息。

本次实际公共导出与独立解码证据在`/var/lib/secretary-workspace/work/20261102-group-operations-sdk/`。建群、按名单邀请、接受好友仍未因这个动作而自动变为已实现；现行capabilities及各自实机结果分别核，不将“有建群菜单”写成群已创建。

## 2026-11-02：已有邀请的真实入群维护实证

新增受控实证：在本人明确允许的原十二个论坛目标中，按原准确peer/群名及入群用途，找到此前本人私聊发来的13张原生49/app5邀请（一个目标重复）。通过官方群邀请页每群点击Join一次，十二个原peer全部有`contact.is_in_chat_room=1`及示例助手真实`chatroom_member`记录，本人也在群。没有群发测试文字。

多个邀请都叫“邀请你加入群聊”时，官方聊天记录支持按**完整群名搜索卡片描述**。本次维护者复用已部署原生UTF-8搜索输入/精确窗口focus方法，核本人来源、日期时间、唯一描述及官方最终群名，再原生核回准确peer与自己的成员身份。新朋友入口没有待处理申请，不等于没有待接受群邀请；resolve未命中时应区分client范围、当前关系及既有邀请来源，不重复索同一份授权或让本人再拉。

这是官方窗口的真实关系验收，**不是公共`join_group`对所有历史卡定位的程序化端到端验收**。普通调用方继续只交准确目标、inviter/source_id及已有授权；程序未覆盖的来源定位及官方收尾交原机制负责人，不让业务AI补坐标。当前这十二群已在群，无需再做Join“测试”。它们只按原论坛通知获`send_text/forward`目标登记，不自动成为POLL、晨报或@服务群。正常发件仍用原SDK，实际业务结果单独核原生发送回执。

私有逐群最终页、邀请源身份及Native关系：`/var/lib/secretary-workspace/work/20261102-group-operations-sdk/approved12-invitation-source-review/RESULT.json`。邀请票据、XML、群成员原文不随说明公开。建群、名单邀请、客服岗位及其他暂停专项没有因本次入群自动完成或开放。

## 普通发送的窗口与草稿处理

### 2026-11-02：建群与按名单邀请的实际补齐

以下为新增现态，前文二维码初次交付中“建群／邀请尚未实现”是历史阶段，不再代表当前程序合同。仍使用同一`call`、Store、串行执行器与manual预览确认；没有新服务或队列。原文字、图片、文件快路径不因此多一层AI审批。

```python
# 新群尚无peer；用本次已授权的现有本人DM作为操作锚点，不编造群ID。
j = call({"op":"submit", "job":{
    "client":"secretary", "request_id":"new-authorized-create-id",
    "peer":owner_peer, "action":"create_group",
    "payload":{"group_name":approved_name,"members":approved_other_person_peers}}})
# 获取同一请求，核目标名、人选、暂未核关系者后confirm一次。
# 成功结果中的groupPeer才是真实新群ID；groupCreated不等于所有人已进群。

# 必要的准确群目标准备后，正常按实际群peer邀请；不能借其他client或群绑定。
j = call({"op":"submit", "job":{
    "client":"secretary", "request_id":"new-authorized-invite-id",
    "peer":actual_group_peer, "action":"invite_members",
    "payload":{"members":approved_person_peers}}})
```

当前`create_group`仅开放给secretary的本人DM操作锚点；`invite_members`仅开放给已实际创建的“他山科学智能学习中心”准确peer `13838492562@chatroom`。它没有普通文字、图片、文件、转发的新增动作，也没有POLL、晨报、@或timer接入。其他新对象按其真实业务授权准备，不能从这些能力推导任意群／成员权限。

程序先查同名与原动作，creator隐含在成员中，不额外邀请自身；当前创建配方按已核关系先做部分群，其余明确列出。邀请会跳过实际成员和已证的现有待确认邀请；不能把原生联系人未证好友的标志说成权限不足，也不能由此宣称申请已发。`deferredMembers`是该群操作当时的计划，里面的`requestSent=false`不证明其他原好友请求从未发出，应结合各自原请求收据和最新关系核验。

最终预览核准确群名／peer、实际选择名单及空的历史分享值。接口不选择Share messages；控件正常启用变色不算分享内容改变。`joinedMembers`、`pendingMembers`和`actualMembers`分别代表实际入群、已证邀请待同意和当前成员；accepted不是“名单已经全齐”。关系状态与原生回执必须看具体字段，不能为待同意或收尾异常重复创建／邀请。群动作可能正常产生系统通知、验证介绍和邀请卡；`ordinaryChatSendClicks=0`不等于“微信里没有任何自动消息”。

本次真实业务已完成十二人原生精确成员集合，创建一次；首批四人经普通SDK邀请一次并自动归位，最后一人经已授权官方加人路径一次完成。初次创建／命名曾做原单受控恢复；修正后没有另建测试群。11人布局中的Add文字识别仍有一次真实未发反例，最后一人没有伪称该失败SDK单成功，当前不宣称所有人数／布局都已验收。公开好友申请／接受动作仍未因本次五个官方申请而自动开放。

私有完整事实、逐人状态、所有旧失败与单次边界：`/var/lib/secretary-workspace/work/20261102-group-operations-sdk/learning-center/RESULT.json`。本群及名单不作为官网入口，二维码和服务岗位另按原业务指定范围处理。

- 已知搜索弹窗按其所属主窗位置/尺寸/窗口身份识别，安全非编辑关闭；原生WM_CLASS、正PID、client leader及WM_TRANSIENT_FOR必须精确证明属于唯一校准主窗，画面还须有唯一互联网与原生联系人/群聊分区，窗口/像素/属性复核未漂移。独立聊天窗是当前操作目标，不被误当搜索面板的父窗；仅点击已证父主窗的原有非编辑区域，其他聊天窗保留。未知类型、父关系不符、无明确搜索场景或变化仍拒绝；有限元数据留在私有modal-check.json，不含聊天/草稿/真实私人标题。弹窗高度随结果数量变化。已知其他独立聊天窗保留，目标窗口置前。原生昵称为空的已登记群，只在绑定的完整成员集合全局唯一、每个实际显示人名均精确解析为其余全部成员、系统标题精确等于原绑定完整标题时，作为已知独立窗保留；不以同人数或近似标题接受，不更换/放宽冻结签名。未知模态和未知布局明确拒绝，不盲按Esc/OK，不清除他人任务。
- 独立窗的会话坐标与标题冻结仅覆盖已验证绑定的几何字段，保留原成员集合、账号和完整标题；同一执行器连续请求或取消/过期清理后仍逐次核原生身份，不依赖重启或切到别群恢复。
- 同一目标编辑窗里，可证明的普通文字草稿会先0600私有暂存，再准备本次内容；发送、取消或超时清理后精确恢复。调用方不需要传replaceDraft或草稿正文。备份不通过公共接口返回；恢复成功后正文从操作备份中清理，仅保留哈希/长度和恢复状态。
- 含@、引用、内嵌对象、未知附件或不能无损证明的内容保留并返回DRAFT_PROTECTED/noSend=true，不占死整个队列。普通AI不得因此自己去清草稿或改工具。后台已创建、归属可证明的Select File等准备现场由工具回滚，只关闭自己的窗口。读取/清理草稿的焦点固定在已校准编辑框右侧空白区，避开可点击的附件卡；取消图片或文件先去除选择态再核对冻结内容。
- 图片不再依赖固定裁剪中的连通色块。工具先保存上传资产的解码RGBA像素身份，再粘贴；从实际编辑器复制时先用随机标记清空剪贴板，核原生WeChatRichEditFormat恰有一张图片、URI与正文一致且无额外元素，再逐像素核对尺寸/哈希。留白、长图不会因内容连通度而失败；混入文字、多图、未知原生格式或不匹配仍拒绝。复制得到的内部路径先作一致性比较，不外传或作为业务参数；仅下述受限原生缓存引用可在宿主内部读取。
- 官方复制若仅返回图片文件引用而不提供剪贴板像素，仍先核上述唯一原生图片与URI/正文一致；仅允许当前绑定账号私有`InputTemp/UUID.png`，逐级openat/NOFOLLOW打开、拒绝跨账号/目录穿越/符号链接/宽权限/非普通文件；已观察的官方缓存PNG有两个链接，只读接受链接数1或2且前后不变，更多链接仍拒绝，读取前后核文件身份。原缓存PNG不套用上传编码10MB门槛：先核PNG头，按其尺寸/通道导出编码资源边界；已发布phase2已取消旧8192边长和1600万像素门槛，RGBA仍必须与冻结上传资产逐像素哈希一致。其他内部路径不打开，不向API返回路径；准备、发前重核和自有清理共用此验证，无法证明仍保留现场停止。
- 粘贴前即保存私有恢复记录；即使最终预览生成失败，也仅在上述图片身份可证明或编辑器确为空时清理并恢复旧草稿。无法证明的内容保留为needs_attention；已有attempt则不执行取消清理。
- 发前重核真实目标、窗口集合、完整正文或冻结附件、已启用的实际Send控件；只点击一次，随后有界查原生回执。慢或结果未知仍只读核账，不因没有立刻看到成功再点一次。
- 普通新发送预览只裁目标聊天区域，不展示旁边会话侧栏；历史预览和旧维护截图保持原样。长正文同时在preview.summary.text与payload.text可核，不能仅凭可见截断图判断全文。
- 成功回执可含sendClicks、priorTextDraftPreserved、draftRestored、draftRecoveryPending。消息已获原生接受，即使后续草稿恢复待核，也仍是已发送；绝不能因draftRecoveryPending或postActionPending重发。恢复失败保留私有备份，按请求号交维护，工具不覆盖新出现的其他内容。

## 调用效率

在取得窗口前先定稿本批正文、核文件哈希并完成上传；相同会话中接口文档与版本未变时复用已读知识和已核登记事实。最终预览出现后集中核目标、完整正文或资产身份，及时确认或取消，较长的分析与回报在本批回执收齐后整理。共享窗口继续逐项串行，逐项读取实际结果；已有稳定请求只查询原单，迟到的历史状态通知须与最新收据对照，不能触发重复发送。

## 显式程序校验快路径

普通模式仍是默认。只有本次已获授权的新发送明确选择`execution_mode="verified_fast"`，且当前`capabilities.verifiedFast.eligibleActions`包含该动作时，才进入快路径；它不是扩大业务授权或收件人范围。当前动作是`send_text`（普通文字、Unicode emoji、已测微信内置表情，原生type1）、`send_image`及`send_file`；不含引用、转发、入群、好友、附件导出或原生type47。

```python
# 格式示例，不是待发送任务；使用本次真实授权的全新稳定request_id。
j = call({"op": "submit", "job": {
    "client": "本次已有client", "request_id": "new-authorized-fast-text-001",
    "peer": "本次准确peer", "action": "send_text",
    "execution_mode": "verified_fast", "payload": {"text": "本次精确正文[微笑]"}
}})
# 继续get同一请求。outcome.status=pending时等待，不下载预览后盲目confirm。
# 若程序不能正向核完而返回review_required，再按普通流程查看最终预览、确认或取消。
```

程序仍准备并保存真实最终预览，正向核原生唯一目标/在群关系、绑定与client范围版本、持有的guard、原本无外来草稿、精确实际文字/标题/窗口和启用的Send控件，再持久记录`confirmation_source="programmatic"`；之后复用原发送前重核、attempt、单次Send、唯一原生回执及草稿收尾。没有另一个发送器、队列、模型、服务或调用方自动确认循环。

图片仍核当前上传资产SHA及拥有的staged journal，并实际复制编辑器中的**唯一原生图片**、核RGBA像素身份；原同账号私有InputTemp UUID PNG、格式、硬链接、字节/尺寸/像素等限制全部保留。不能拿ROI截图、缩略图、多图或图文混合冒充当前图片，普通文件的大限额不扩大图片预算。

文件同时要求：官方chooser精确路径复制读回、chooser完成、当前资产id/client/完整名/bytes/SHA256/MD5全部绑定、以及**实际复制的唯一原生文件片段和URI**准确对应这个冻结资产。只识别已观测的`WeChatRichEditFormat`单个`EditElement type="3" filepath="..."`，路径与唯一file URI必须严格等于当前受限资产路径，额外文字/对象/URI、未知字段或同前缀错名均拒绝；只比较引用，不打开任意剪贴板路径。这里的剪贴板type3不是发出的图片消息type3，文件成功仍须原生type49/appmsg6的准确文件名、大小、MD5回执。

画面文件名有省略号时，`filenameOCRProgramVerified`如实保留false；**只有独立的完整单文件原生引用和chooser/资产关系均被正向证明**，才能以明确`filenameVerificationMethod="native-single-file-reference"`获得`filenameProgramVerified=true`。不能仅靠OCR不完整、源文件名、一个标志或猜测放行。当前复制格式/完整名/资产关系不证明则review_required，不缩短业务文件名、不放宽OCR正则、不要求调用方补坐标。真实发送前再次核当前单图片／文件及冻结卡片，随后只点一次；所有原有限额、流式上传及native收据保留。

已有普通文字草稿可按原人工模式暂存恢复，但不直接获得自动发送资格。不能核验的对象/场景转`review_required`最终预览或安全失败，不当成功。`preview.fast_verification.eligible=false`及有限reason说明需人工审阅；`FAST_REVIEW_REQUIRED`不是已发送。程序核验尚在进行时，`outcome=pending`、不暴露可人工确认token，强行confirm返回`FAST_VERIFICATION_PENDING`；get继续等待同一请求。若在保存预览与证书之间重启，降为`RESTART_REVIEW_REQUIRED`，不盲目自动确认或永远pending。

可选mode只有严格字符串`manual`或`verified_fast`。**省略字段**维持旧canonical JSON与幂等哈希，旧请求不迁移；显式模式字段属于请求身份，即使从省略改为显式manual，也不能改写旧ID。模式、收件人或正文变化均用本次新的真实业务尝试编号；unknown仍绝不能换ID补发。默认CLI无动作仍只帮助，未指定快模式不会自动发送。

新增`outcome`保留所有旧state/result/code：`pending/wait_same_request`等待；`sent/done`需真实accepted原生发送依据；`review_required/review_preview`由调用方核最终预览；`not_sent/review_failure`只在已保存正向noSend=true时出现；`unknown/reconcile_same_request`只读核原单，不再点击。非发件动作accepted可显示completed，不能把导出说成发送。没有attempt或没有回执不意味着未发送。取消、过期和并发执行申领均由原事务/队列处理，不能重开终态请求。

本轮已有12件合成本人私聊的真实原生验收：文字/内置表情、图片、文件各2条程序快发与2条普通对照，6条快样例均无调用方confirm、每条Send1；同ID复提只回原serverId，无新事件/额外发件，文件保留冻结完整名/大小/MD5。软件、原生与手机实收分别记录在本次delivery/DELIVERY和benchmark收据；本人已确认本批12件全部收到且显示/打开正常，原rawcase手机字段不回写；不把这批小样本外推为所有群/格式/布局成功率或最优速度。普通人工模式保留；此历史快模式批次未验收原生47，11月1日官方手动路径的新验收见上方专节。

## 返回与确认

`submit/get/confirm/cancel/reconcile`返回同一请求的业务视图：id、client、request_id、peer、action、payload、state、created/updated、preview、confirmation_token、result。普通返回不含内部窗口坐标、鼠标计划或服务器文件路径。`reconcile`还返回`readOnlyReconciliation`，提供本次只读核账的证据；不改变结果时仍保留unknown。

- preview.available为true时，表示工具已准备好最终业务预览；通过`preview`取PNG，或用`save_preview`直接保存并校验SHA256。
- confirmation_token只在可确认的最终预览状态返回。令牌与此次请求/预览绑定，默认180秒有效；旧token或现场变化会拒绝，不自动继续发送。
- 预览用于检查“是不是这个人、这段内容、这份文件/这个引用”。调用方不需要判断按钮、坐标或下一步怎么操作。预览截图仍可能包含同一桌面上可见的其他信息，只在已授权环境内核对，不转发到无关服务。
- 同一请求等待确认时由内核guard持有共享窗口，后面的操作排队；数据读取仍可并行。不再需要该操作时及时cancel，随后查询实际取消结果。
- 只有`state=succeeded`且result给出所需核验依据，才可报告成功；queued、confirmed、工具启动、截图看上去有内容都不算发送成功。
- 普通send_text收据允许完全相等，或客户端仅去掉末尾恰一个LF：期待正文必须只有一个末尾LF，前一字符不能是LF/CR，去掉后正文非空且其余逐字相同。前导空格、内部换行、CRLF、多尾行和其他差异不被归一化。仍须同peer、示例助手、status=2、发送声明/前置基线及唯一候选；精确候选和单LF候选并存也拒绝。回执textComparison保存mode、expectedText、actualText、双方SHA256及长度；差异模式为single_terminal_lf_removed，冻结payload不变。对于已点击且unknown的原请求只reconcile，不新建ID补发。

| state | 应怎样处理 |
|---|---|
| queued / preparing | 等待同请求，不重复提交 |
| awaiting_confirmation | 取最终预览，核对后confirm，或cancel |
| confirmed / executing | 继续查同请求，切勿再点击或换ID |
| succeeded | 读取实际结果和证据层次；原生已提交不自动等于手机人工实收 |
| failed | 读取code、reason和noSend；不把它当成功。程序失败不会要求调用方提供坐标 |
| cancelled / expired | 操作已停止；读结果确认是否为未发送以及自有草稿是否清理 |
| unknown | 用同client/request_id查询或reconcile；结果不明不重发 |
| needs_attention | 无法证明现场或清理，返回OPERATOR_REQUIRED；保留请求供工具维护，不要求使用者代替程序操控微信 |

## 其余接口

| op | 必需字段 | 行为 |
|---|---|---|
| capabilities / status | 无 | API版本、动作边界、进程身份/心跳与队列情况；status不泄露其他请求正文 |
| resolve | client,query | 在client范围内精确解析收件人，歧义返回候选，不操作窗口 |
| upload | client,name,sha256,data | 原始JSON上传接口；data为base64，通常使用upload_file助手避免模型处理二进制 |
| preview | client,request_id | 返回mime、SHA256、有效期及PNG字节；CLI保存必须指定输出路径，禁止打印base64 |
| confirm | client,request_id,token | 确认这次最终预览；不接受旧版单步UI预览 |
| get | client,request_id；wait_seconds可选 | 有界等待0..20秒；只查询，不推动发送 |
| list / events | client；events还需request_id | 请求列表/生命周期历史，保留旧收据；list当前最多100条 |
| cancel | client,request_id | 请求停止未执行动作；程序只清理确属该请求的草稿，不丢掉他人内容 |
| reconcile | client,request_id | 只读核账；即使结果未知也不再次点击 |
| download | client,asset | 取得该client的已校验导出资产；可用save_output保存 |

## 错误与恢复

Python调用抛出`ToolError`，保留`code`和`details`；CLI返回退出码2与`{"state":"error","error":{"code":"...","message":"...","details":{}}}`。传输异常须先查稳定请求，因为可能已提交而回执丢失。

- AMBIGUOUS_RECIPIENT：查看候选并明确真实对象，不按排序选人。
- RECIPIENT_NOT_FOUND / OUTSIDE_SCOPE / CLIENT_NOT_CONFIGURED：核真实身份与配置，不能换client绕过既有范围。
- REQUEST_CONFLICT：同一个ID的内容或目标发生变化，先核原请求。
- INVALID_REQUEST：字段、载荷、确认token、状态或wait_seconds不合约；不改用内部UI指令试错。
- UNSUPPORTED_ACTION：本版本无公共确定性流程，尚未排队，不会发送。
- TARGET_NOT_CALIBRATED / UNSUPPORTED_LAYOUT / RECIPIENT_NOT_VERIFIED：当前目标或布局不在可核范围，失败退出；没有“由AI补坐标”分支。
- SOURCE_NOT_VISIBLE / SOURCE_AMBIGUOUS：原消息在支持范围内没有唯一定位，未发送；不要用近似消息替代。
- DRAFT_PROTECTED：已有内容无法按普通文字无损暂存，完整保留，未准备/发送新内容；普通AI上报维护而不自行操控。
- DRAFT_RECOVERY_PENDING：原文已私有保存，清理/恢复尚不能证明，保留请求与现场。
- SEND_PREPARATION_FAILED / FOREIGN_DRAFT / INPUT_MISMATCH：程序未完成已知准备或实际输入不同，读取noSend和当前状态；不改走旧UI步骤。
- IMAGE_SOURCE_NOT_FOUND / NOT_AN_IMAGE / IMAGE_RESOURCE_MISMATCH / IMAGE_IDENTITY_MISSING：目标、类型、资源或来源身份不成立，未导出。
- IMAGE_CONTEXT_AMBIGUOUS / IMAGE_ANCHORS_NOT_VISIBLE / IMAGE_CANDIDATE_AMBIGUOUS / IMAGE_CANDIDATE_CLIPPED / UNSUPPORTED_IMAGE_LAYOUT：当前窗口不能唯一证明图片，失败而不猜测。
- IMAGE_CONTEXT_CHANGED：原生来源、窗口或画面与预览不符，不开图继续。
- IMAGE_MD5_MISMATCH / IMAGE_NOT_DECODABLE / IMAGE_OVER_BUDGET / IMAGE_FORMAT_UNSUPPORTED / IMAGE_SOURCE_MISMATCH / IMAGE_EXPORT_NOT_PROVEN：原件核验不通过，不返回资产；官方底层未证明MD5时也可能统一返回IMAGE_EXPORT_NOT_PROVEN。
- IMAGE_CLEANUP_UNPROVEN / OPERATOR_REQUIRED：现场无法证明已恢复，保留待维护记录，不让调用方补坐标。

## CLI与环境

```sh
python3 /var/lib/secretary-workspace/tools/wechat_operations.py
python3 /var/lib/secretary-workspace/tools/wechat_operations.py --execute --upload-file /absolute/file.pdf --client secretary
python3 /var/lib/secretary-workspace/tools/wechat_operations.py --execute --request-file /absolute/request.json
python3 /var/lib/secretary-workspace/tools/wechat_operations.py --execute --request-file /absolute/preview-request.json --preview-output /absolute/new-preview.png
```

请求文件也可用`-`从stdin读；输出路径须为新的绝对路径，拒绝覆盖与符号链接。所有确认和查询仍走同一client/request_id。AUP本机直接调用同一JSON协议；不需要Mac客户端、秘书模型或本对话。

## 限额、维护与V1兼容

### 2026-11-01早前阶段：正常协作素材的有界缓存预算（历史，已被下方资源兼容更新替代）

原共享缓存512MiB被267个正常历史资产及metadata占用至仅余24773B，一张1.27MB合辑图因ASSET_QUOTA在发布前拒绝；这不是发图权限或微信发件失败。按真实用量和约306GB可用磁盘，该阶段将原总额有界调整为1GiB（1073741824B）；同日后续资源兼容更新取消了这项固定总额。单件128MiB、图片10MB/8192边长/16MP、256MiB磁盘预留及原上传锁/流式散列/原子发布不变。capabilities.constraints.totalAssetBytes直接读取实际资产guard常量，避免说明额度与执行额度分离。

没有自动删除、移动、压缩历史资产，也不以终态引用就推定原件可丢。ASSET_QUOTA/ASSET_DISK_RESERVE是资源阶段错误：未发表资产不等于微信消息failed/unknown；未创建的消息不能假造requestId核账。恢复后原业务方按同client/原文件名/SHA走原upload_file和SDK；结果不明先查原内容地址，不换client/改名盲传。资产存在不等于微信已发。

此调整可回滚为原上限；回滚不会删除已入库数据，若届时使用量超过旧上限，只会阻止新的上传直至用量满足条件。当时1GiB仍有硬上限，现已取消该固定总额，不宣称永久免磁盘维护；磁盘保护没有关闭。具体实证见20261101-wechat-reliability-closed-loop/asset-budget-20261101/。

当前普通文件单件与缓存总额不设配置的业务尺寸门槛，能力字段singleAssetBytes/totalAssetBytes为null；磁盘仍预留256MiB，并逐块检查真实余量；小件JSON上传/下载仍限10,000,000字节，图片仍限10,000,000字节及原解码预算、队列收据10000条；超过限额明确拒绝，不自动删除历史。消息原件、原库及凭据留原处，不复制整套微信或媒体。

### 2026-11-01：普通文件与缓存资源兼容更新

已取消原128MiB单文件、1GiB缓存总额和持续活跃上传的180/240秒总时长门槛。`constraints.singleAssetBytes`、`totalAssetBytes`、`streamUploadSeconds`为null，表示没有配置的该类业务上限，不表示机器资源无限或所有文件已经微信实发验收。保留256MiB真实磁盘预留、客户端/服务端空闲超时、逐块散列、完整大小/前后stat/同内容地址、临时文件清理、账号与调用scope、单Send/原生核回。控制JSON/小件inline预算与原件流式传输范围分开；不要为大原件改成base64大JSON。

SDK仍`upload_file(client,path)`；先上传核原件，再查最新业务来源/撤稿与重复后准入。来源是目录、FIFO、符号链接、变更文件或坏哈希均拒绝，非普通文件不能阻塞打开或发起网络。已存在缓存不会为了腾空间自动删除；磁盘不足返回真实ASSET_DISK_RESERVE，并给required/available/reserve，不说缺发件权限。大件上传结果未知仍只核同client/name/hash的原资产，不能盲重复传输或重发旧消息。

本阶段新129MiB合成文件（135266304B）已经原入口真实流式入库并核SHA/MD5，超出旧128MiB门槛；官方准备/取消和最终回执状态以本轮resource-compat/RESULT为准，不把入库当微信已发送。没有为了填满1GiB而造更多大文件，缓存总额取消由生产能力读回和资源负例验证；当前能否传入具体原件仍由真实磁盘/网络及官方客户端结果决定。证据`/var/lib/secretary-workspace/work/20261101-wechat-native-parity/resource-compat/`。

目前校准支持905×667主窗口，以及名称唯一映射回真实peer的623×667独立聊天窗口。其他缩放、版本或窗口布局会明确拒绝；这不是通用跨版本适配承诺。

不要先启动wechat_desktop的compose/navigate会话再调用本队列，那会占用窗口并阻塞自己的请求。普通发送不需要调用方打开远程桌面、切会话或清草稿。

普通AI不修改工具源码、私有配置，不重启/停止执行器、不用旧client.py或admin-request绕过失败；登记/版本/未知现场问题保留请求编号交维护者。

后台服务`wechat-operations.service`只处理显式请求，不扫描信源、不执行业务判断。程序内部负责所有控件和导航；原始X11/同一OS用户手动输入仍不受合作锁强制隔离。新请求串行；原桌面compose入口也检查同一内核guard。心跳过期不能当窗口空闲；status的uiBusy、active及window_busy是诊断依据。原始X11或不遵守协议的同OS用户输入不构成强隔离保证。旧旁路仅维护用途，普通调用方不自行使用。

V2复用V1队列和收据，不重建或清库。普通request入口已升级；原assist/plan_step等仅保留为维护用admin-request，不在本Skill范围，旧低层手册见OPERATIONS-API-V1-MAINTENANCE.md。不要让其他AI继续按旧文档生成坐标请求。

本版文字、图片、文件、引用回复和文字转发已有V2受控实机回执，不能据此声称所有联系人/微信版本/布局的成功率或手机实收。新好友与新入群的样本缺口见交付记录。

图片通用受限读取的实现/实测范围见`/var/lib/secretary-workspace/work/20261027-sample-person-aup/source-support-20261028/GENERIC-IMAGE-DELIVERY.md`，单图维护成功与新程序化请求分开验收。

Skill只负责触发读取本文，不保存第二份手册；此文件是唯一调用文档。本文和当前capabilities是调用契约。具体实机样本与缺口另记在OPERATIONS-V2-DELIVERY.md，不能用软件单测数量冒充真实发送次数或最优性实验。

发送收口的科研群三类实机、弹窗/草稿/并发证据：`/var/lib/secretary-workspace/work/20261028-wechat-send-release/DELIVERY.md`。原八条旧科研消息未重发。

2026-10-28图片准备修复的六图准备/取消、预览前失败恢复与真实公共调用边界见 `/var/lib/secretary-workspace/work/20261028-independent-secretary/tool-repair/IMAGE-FIX-DELIVERY.md`。实际业务图片发送仍由原调用方核最终预览并验收。

2026-10-28单个末LF的原请求核账修复与反例验证见 `/var/lib/secretary-workspace/work/20261028-independent-secretary/tool-repair/TERMINAL-LF-DELIVERY.md`。文件末LF若不是本次要发送的正文，应在构造新请求时明确处理；工具不修改旧冻结内容，也不用strip/rstrip吞掉正文空白。

2026-10-29原文件流式上传与已登记无名群窗口共存维护：`/var/lib/secretary-workspace/work/20261029-send-operations-improvement/tool-delivery/DELIVERY.md`。本轮原PPTX/PDF只完成上传/原件身份/官方准备及取消，不等于业务实际已发送；最终业务确认由发送对话验收。

2026-11-04普通预览过期收尾补齐：原worker对`send_text/send_image/send_file`的明确预确认到期、`owned_draft_cleanup_not_proven`原单，在有正规原composer journal、无confirmed/executing/attempt/checkpoint/step痕迹时，可受限重试原cleanup，不再要求preview带navigationBounds。每worker/原ID最多一次；仅正向恢复才终态expired/noSend，失败仍保护，不自动确认、重新准备或发送。unknown/accepted沿原核账/收尾，不重放。调用方仍须及时消费需要人工审阅的预览，不能把回合active当已审。实际三文件、两端回归、独立加载与边界见 `/var/lib/secretary-workspace/work/20261104-bp-six-reader-own-guard-error/expired-preview-prevention/RESULT.md`；公共API签名与发件分工不变。
