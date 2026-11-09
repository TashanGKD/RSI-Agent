# 本机已有对话的原生投递

适用于用户明确要求向已有Codex对话同步消息，并要求队列接续的情况。先核当前部署；工具是否暴露不替代queue-only语义核对。正常队列入口不是桌面点击、手改数据库或新起模型恢复分支。

## 先核已有对话的部署位置

已有对话可能已迁到AUP。先检查现成部署路由 `/var/lib/secretary-workspace/tools/thread-routes.json`；命中远端的对话使用 `/var/lib/secretary-workspace/tools/conversations.mjs` 的原有 inspect/read/assign/status，或已登记的 `wechat_sender.py` 客户端。不要对已归档的Mac副本裸用下面的本机CLI或socket重新唤醒。未命中路由的对话继续用下述本机入口。

2026-11-02原微信发送对话 `00000000-0000-4000-8000-006912130405` 已正式切到AUP，仍保留原ID、原工具队列和业务请求。这里只说明部署位置，不新增权限或定时任务。

## 现行官方CLI队列路径

当前Mac已用`/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex queue --thread 原对话ID --message 不可变定稿`验证排队并由原桌面对话自然消费，不加`--resume`，不启动第二个app-server。用实际本机`--help`核版本契约，目标ID来自本人指定的真实对话，不复制案例。

调用者先持久保存稳定业务请求ID、目标、定稿及其哈希、提交前回合定位，再用结构化subprocess参数调用一次。命令返回queueId后保存原回执，原队列和历史只读核验；当前应用的对人ID与历史存储ID可能不同，须按已核真实映射定位，不猜或改写。超时、未知、队列消失均先查同一定稿及原请求，不能换ID重交。技术实现参考[统一系统现行运行器](/var/lib/secretary-workspace/projects/digital-employee-method-20261030/unified-mention-runtime/README.md)，普通调用者不编辑系统服务。

2026-10-31会务接入的官方队列准备核验消息，在原业务回合工作时保存，并在该回合自然结束后进入原对话；该准备消息不是群@。后续真实群@有精确原生用户项证据。此路径可供正常交办，不意味着任意通用发送工具也只排队。

旧assign客户端及下方受管socket路径可能因桌面会话变化而不可用，必须先核连接；不可用不改信任/签名、不恢复旧全账号tick、不把交办升级为直接打断。曾用通用工具提交的原单先核账，不能另走CLI再发同一内容。

## 当前可执行入口

- 已有适配器：`/opt/secretary-workbench/clawbot/bridge/native_rpc.mjs`，导出`RPC`。
- 已有受管连接：`/var/lib/secretary-clawbot/desktop/control.sock`。
- 适配器会通过既有`validateManagedSocket`核对私有目录、socket所有权及已登记指纹，再连接正在运行的桌面原生服务并初始化协议。不要复制、改写或删除这些pin来让验证通过，不自行启动第二套app-server。
- 适配器所在项目名称不限定投递目标。不要调用它的微信业务`native_logic.reconcile`或`tick.mjs`来发送普通交接；直接使用`RPC.call`，消息中明确真实来源，不伪装为微信消息。不要恢复旧轮询、修改其绑定/定时器或动共享窗口。
- 当前文件路径是本机已验证安装位置；不存在或原生服务不可达时，核实际部署/报告阻塞，不临时下载程序或更换认证。

先阅读适配器及调用者确认当前契约。现有调用实例：`/var/lib/secretary-workspace/projects/wechat-science-collab/tick.mjs`（只读作协议参考，不能运行它来交接）。其队列语义还可参照同bridge目录`native_logic.mjs`。

### 只读接入检查

下例需要显式提供目标threadId，打印有限元数据，不输出完整对话、私有路由、环境或凭据。无参数不会连接。每次实际投递前以此核真实目标；标题只作线索，threadId必须来自用户选定对话/已核绑定。

```sh
node --input-type=module - 00000000-0000-4000-8000-00af1651cef6 <<'JS'
const target = process.argv[2];
if (!target) { console.log('Pass the explicitly selected thread UUID'); process.exit(0); }
if (!/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(target)) throw Error('Invalid thread ID');
const {RPC} = await import('/opt/secretary-workbench/clawbot/bridge/native_rpc.mjs');
const rpc = new RPC('/var/lib/secretary-clawbot/desktop/control.sock');
try {
  await rpc.connect();
  const {thread:t} = await rpc.call('thread/read', {threadId:target, includeTurns:false});
  if (t.id !== target) throw Error('Target mismatch');
  const q = await rpc.call('thread/queue/list', {threadId:target, limit:100});
  console.log(JSON.stringify({id:t.id, cwd:t.cwd, status:t.status, queueCount:q.data.length}));
} finally { rpc.close(); }
JS
```

上面的UUID仅是已验证科研对话示例；另一任务必须使用其明确选定的真实ID。接入检查只读，不表示已经投递。用户要求同步的授权已经足够完成相应消息投递，不因正式工具缺项再次请示同一动作。

## 投递与核验契约

1. **准备唯一请求。** 将定稿保存在本次工作的非公开交接目录；记录`target`、预期cwd、稳定`clientUserMessageId`、全文SHA256、授权来源和状态。请求ID要绑定目标与这次工作，重试沿用原ID，不每次随机换ID。已有回执先恢复原请求，不覆盖记录。不要把文件内容用shell字符串拼接成命令；使用文件读取和结构化JSON。
2. **核目标/队列。** 用上述`thread/read`核ID/cwd及实际状态。`thread/queue/list`返回`data`和可能的`nextCursor`，按需翻页查原clientId。已在队列或历史中找到同一请求就继续核验，不再add。若线程确为`notLoaded`，可对这条已有线程用`thread/resume {threadId, excludeTurns:true}`接入，再核ID/cwd；不覆盖模型、权限或工作区，不执行`thread/start`创建替身。
3. **只提交一次。** 先持久记录`submitting`，再调用：

   ```js
   const added = await rpc.call('thread/queue/add', {
     threadId: target,
     clientUserMessageId: requestId,
     input: [{type:'text', text:messageText, text_elements:[]}]
   });
   // Save added.queuedSubmission.id immediately; absent/timeout => unknown, reconcile first.
   ```

   `queuedSubmission.id`是原生排队回执，只表示已被接收排队。RPC错误、连接断开、超时不证明未投递；不要自动再add。保留已发生的回执及错误。
4. **优先观察自动消费。** 用新的RPC连接独立回读队列与目标线程。桌面可能在`queue/add`之后立即把队列变为空并启动原对话；**“queue/list查不到”不是失败**。先到最近回合查精确消息。若仍在队列，仅在最新线程状态`idle`、且你的消息确为队首时，才可用`thread/queue/start {threadId, queuedSubmissionId}`启动。忙、已有别的队首或自动启动时等待，不`turn/interrupt`、不插队、不用`turn/start`额外注入一份。
5. **独立查原生用户消息。** 用`thread/turns/list {threadId, limit:..., sortDirection:'desc', itemsView:'notLoaded'}`找提交后的候选回合。对候选调用`thread/items/list {threadId, turnId, limit:..., sortDirection:'asc'}`；数据项可能由`entry.item ?? entry`解包。查`type==='userMessage'`且`clientId===clientUserMessageId`，并把`content`内文本按顺序连接后核SHA256与定稿相同。保存真实`turnId`、用户消息ID与匹配证据。不得只凭消息标题、片段或队列消失宣称投递成功。
6. **未知先核账。** 每页按`nextCursor`继续，范围以发送前保存的回合锚点/时间和已知turnId为界。命中且全文一致即已投递；若分页未读完、结果截断、身份冲突或网络失败，保留`unknown`/待核验，不能把有限页没找到当作“肯定未发”。不改ID重复提交。
7. **核实际接手或完成。** 用返回turnId及原任务资料核对应阶段：准确材料读取证明读取，原责任记录及实际后续动作可证明接回，产物/原生交付才证明所要求的结果；不能把一条读取命令称为理解或最终完成。原委托要求最终完成或明确确认时，再核相应`completed`回合和`agentMessage`的`final_answer`或`final`是否覆盖要求，保存必要ID和摘要/哈希。`failed`/`interrupted`或仅commentary不能冒充最终完成。普通结果不另要收到/核收消息；每次等待不超过60秒，不紧密轮询或为拿确认打断工作，两方均可继续独立可做事项。

## 权限与交接范围

### 原生队列合并与收口

在岗位接续职责内处理自己收件，或按本人明确交办整理关联队列。先读当前`thread/queue/list`的完整页并对照原工作本、当前结果和必要连续输入，人工判断同一事项中哪些已处理、哪些仍未完。不按“普通只入队/无需确认”标签、队列年龄或文本相似度自动丢消息。

收口前将原条目全文、thread/queue/client ID及正文SHA、归并理由、实际证据和保留的未完去向存入本轮私有归档。对实际还在队列且内容未变的准确ID，可执行：

```js
// 合并：仍保原queue ID/client归属；先保全未完输入，再移除被覆盖的其它项。
await rpc.call('thread/queue/update', {
  threadId, queuedSubmissionId,
  input: [{type:'text', text:mergedCurrentContext, text_elements:[]}]
});
// 只移出待处理队列；原文、业务记录和已经进入回合的历史保留。
await rpc.call('thread/queue/delete', {threadId, queuedSubmissionId});
```

每次变更后独立`list`核同一ID和正文；合并项正向存在后才移除其它被覆盖项。原条目已不在队列时，可能已自然消费，不重加、不重复执行其业务；需要判断接收事实再查原clientId的用户项。内容或当前归属已变就留给实际负责人理解。变更返回未知时先只读核同一ID，不循环update/delete/add补偿。不得直接改queue数据库、删除回合历史、暂停活跃员工或取消微信unknown作业来压低数量。

归档完成不另向作者或本人投一条确认。混有新的未完请求时原样保留，或合成一条有来源/责任/下一步的原事项输入；旧结果只留原件，不重新生成业务任务。这个方式复用原队列，不另启监听器、服务或模型。

本机可复用一次性`scripts/queue_closeout.mjs`执行已人工核定的计划：`--plan 计划JSON --archive 本轮私有目录`只预览，显式加`--execute`才连接现有受管socket。计划逐项列threadId/id/原input的SHA256、reason/evidence；`merge`附replacementInput，`retire`仅列已处理或被覆盖项，没列的全部保留。工具先归档、核原内容未变、先正向保留合并项再移除其余项，结果未知只核同一ID，不启动对话或新建队列。它不判断业务完成，也不代员工决定未读材料是否可以丢弃。

移植包中的[同一脚本](../scripts/queue_closeout.mjs)复用本仓`clawbot/bridge/native_rpc.mjs`及宿主已有的`SECRETARY_NATIVE_SOCKET`配置；未设置时沿现有适配器的`var/clawbot/desktop/control.sock`占位路径，不含作者真实安装位置、认证或pin。只有显式`--execute`分支才加载RPC并连接；实际执行前仍须操作者核自己的已授权目标与人工计划。合成测试在`host/tests/test_queue_closeout.mjs`，只使用fake-RPC，不代表真实队列清理或全员采用已经验收。

正式工具和现有原生入口都先核实际语义；普通交办优先已验证的queue-only路径，不能只因宿主通用发送工具可用就跳过忙闲保护。UI工具禁止控制Codex自身时不使用AppleScript、键盘注入或其他UI技术替代。原生API若明确拒绝授权、安全校验失败或沙箱禁止，不改策略绕过。不要直接写聊天/queue/automation数据库、伪造rollout消息、复制登录令牌，或启动另一个生产线程写入者。这个技能不新增任何持久后台任务。

交接文字说明“来源于哪个已授权工作、哪些是真实完成结果、哪些仍未实现”，链接必要的工作文件，写清接收方实际需要承担的动作。普通结果不要求另发收到或核收确认；确需采用/交付时核原回合的实际行为与产物，不用确认回环代替。不要顺带重做已完成部署、触发付费任务或向微信群/邮件发消息。用户没有指定同步内容的私密资料不加入消息。

## 已验证证据与本次故障的处理

科研网页交接的真实回执：`/home/operator/aiwork/Tashan-Org/outputs/runturn-public-deploy-20261030/handoff-delivery/`，包含定稿、`receipt.json`、独立用户消息回读及最终确认。

该次`queue/add`成功后队列被自动消费，紧随的队列检查未找到请求。没有重发；随后在原对话发现相同clientId及全文SHA256，原回合完成并明确确认接手。回执最终`acknowledged`，中间检查错误仍保留。复用的是此语义和入口，不是固定科研对话ID。
