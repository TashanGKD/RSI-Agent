# 记事本工具 API 4.4

实际入口：`NotebookService` / `HTTPNotebookPort` / `local_server.py`。这份是已实现合同；秘书推理、上游增量扫描、定时器、通知和执行不属于本合同。所有在线读取均鉴权，写入另需固定 Origin 与 CSRF。在线 actor 由服务端设置。

## 基本读写与版本

沿用 tasks / messages / schedule。对象保持 local_objects 初始值 + local_changes 顺序重放，不把最新值写回基线再重复应用 delta。ID、已有批注、关闭状态和旧历史不重置。

`POST /api/tasks` 创建；`POST /api/tasks/{id}/record` 修改；`/confirm` 为相同写入链并设置 confirm=true。已有对象必须 expectedRevision；安排写入同时需要 expectedRevision 与 expectedObjectRevision。requestId 同内容重试不重复写，不同内容同键400；当前返回最新已保存投影，不承诺冻结成首次响应快照。

可写对象字段：title、kind、domain、state、assignee、counterparty、summary、proposedAt、timeRequirement、deadlineDate、planDate、eventWindow、reviewDate、followup、condition、relatedRecordIds、completionCriterion、recommendation、sourceContacts、needsReview、recurrence。其他控制字段：actor、requestId、note、confirm、sourceTime、presentationId、presentationVersion、attachments。缺省不改；允许日期/复看的null明确清空；文本仍按原边界验证。

- deadlineDate 为显式 YYYY-MM-DD 或 null；timeRequirement 是保留原意的文字，绝不从其开头日期生成/清空截止。
- `followup={date?,at?,condition?,remindEvenUnchanged?}|null`：date为北京日期；at为带偏移时刻，规范为北京时间；日期与时刻不能矛盾；条件未证实为unknown。reviewDate为兼容映射。仅复看不改计划/截止或创建安排。
- `attachments=[ASSET-ID]` 可与note/状态/安排/确认同事务提交；文件先走受管上传接口，正文操作失败时不冒称附件已关联。
- `sourceContacts` 与 messages.sourceRefs 均支持无原文定位。白名单见 contracts/source_refs.py；必有平台:账号与 recordId/nativeId之一。支持真实群名、昵称、发生时间与精度、版本/64位哈希、页码/段落/媒体偏移。线上禁止 quote/XML/path/key/token 等原始或认证字段。元数据为调用者提供的定位，不等于服务已在线验证上游。
- 本机旧 sources 原文写入保持兼容；线上拒绝原文 sources，原始微信与完整转写保留Mac。
- 纯备注不确认呈报、不改业务状态。关联独立留言会使相关对象版本递增，防止另一设备忽略新信息强写。

## 已实现的发现与查询

| HTTP | 参数 / 返回 |
|---|---|
| GET /api/notebook/capabilities | 运行合同版本4.4、实际能力、无定时/秘书执行声明 |
| GET /api/notebook/objects | kind/state/domain/assignee/counterparty/start/end/keyword/cursor/limit；日期按planDate闭区间；返回objects、total、nextCursor、snapshot、highWatermark |
| GET /api/notebook/changes | cursor非负提交序号、limit1..500、object_id/author/start/end；提交时间区间[start,end)，返回operations、cursor、hasMore、highWatermark、coverage |
| GET /api/notebook/as-of | sequence或带时区at二选一；返回objects/schedules/records/presentations/followupReceipts及真实覆盖 |
| GET /api/notebook/followups | date或at可选；默认当前真实时刻；显式date查询该北京日结束前。返回items、conditionsUnknown、checkedAt、executed=false |
| GET /api/tasks/{id} | 当前对象、最近记录、来源、安排、双向关联和统一正式操作 |

对象分页游标绑定筛选、页大小、提交水位和对象版本；中途变化409要求重新取第一页，不静默混用两个快照。变更流用提交序号安全续读，包括独立无绑定留言和处理回执，不只看updatedAt。详情的operations第一页最多500，继续取changes可完整遍历；没有截断冒充全量。

## 一次操作与历史

notebook_operations：不可变OP-ID、SQLite提交顺序seq、真实服务记录时间at、actor、requestId。notebook_effects：同操作的对象/安排/输入/呈报/回执前后值；notebook_operation_links将原有事件和输入连回此操作。事务任一部分失败整体回滚。业务原时间sourceTime另存，不冒充提交时间。

迁移新增notebook_baseline与覆盖收据，只建立迁移时已知状态。此前原事件仍能查看，但不能重建不存在的旧全量快照；早于覆盖的as-of明确拒绝。不复制微信原库或完整归档，不覆盖原任务表。

恢复：POST `/api/tasks/{id}/restore-preview` `{sequence,fields}` 返回字段差异、patch与expectedRevision；POST `/api/tasks/{id}/restore` `{sequence,fields,expectedRevision,requestId?,note?}` 按当前版本追加普通操作。可选显式业务字段；禁止恢复needsReview/sources、认证、幂等或原输入表。不能拿旧版本直接覆盖现在，不删除后来记录。同requestId恢复重试安全。

## 呈报与复看

POST `/api/tasks/{id}/present`：expectedRevision、note、recommendation?、requestId；每轮稳定PRES-ID与递增version。新候选需要批阅时也有呈报身份。confirm可携带presentationId/presentationVersion；不匹配409；旧客户端省略时仍受对象版本保护。仅human能确认；AI关闭有确证的业务项不伪造human ack。迁移旧布尔标志保留兼容，不伪造过去本人已阅。

POST `/api/tasks/{id}/followup-ack`：expectedRevision、followupKey、note、requestId；只记录本次核查已处理，不改业务状态。真实本人确认到期复看可在同事务留下回执。条件没有证据仍unknown，不由关键词判定或自动执行。到期查询/批阅显示是派生读取，不运行秘书、不做主动通知。

## 安排与循环定义

见 SCHEDULE-API.md。明确改期使用postponeTo；普通暂缓使用followup，可不设假日期。存在后续安排时，不允许对旧次重新改期覆盖后续计划；编辑最新次即可。

recurrence为可空定义：frequency=daily/weekly，weekdays为0..6（周一0，仅weekly），startDate、endDate?、startTime/endTime?、enabled、timezone=Asia/Shanghai。POST schedule显式为定义建立某日实例，检查有效日期和同日唯一；definitionId/occurrenceKey记录来源。完成/等待/暂停实例不关闭定义；把已有事项转为定义时，为今天及未来已有安排补关联，过去事实保留。未启用自动展开器，也不在前端增加循环设置入口。循环实例复看暂不复用对象级复看，拒绝该混写，避免修改整个定义。

## 信源目录和本地工具

GET /api/sources：本地为实际缓存目录，线上为最小信源目录/已有定位，缺口不隐藏。POST /api/source-catalog仅授权设备同步白名单名称、缓存数、快照、三阶段最近时间、状态与缺口，expectedRevision+requestId；不能上传原记录。目录声明不证明上游全量。

本地 `/api/sources/{platform:account}/records` 继续分页查询；新增 snapshots、versions?recordId、read-version?recordId&snapshot、receipts、checkpoints?consumerId、assets。写入 imports、receipts、checkpoints、assets；所有新原件接口线上404。方法、证据、额度及独立CLI见 SOURCE-TOOLS.md。来源和记事本没有私有表互写或循环依赖。


## 4.4 统一事项与实际进展（2026-10-31）

待办和已发生工作使用同一事项对象，不新增工作事实主表。`work`是备注/记录的可选业务元数据，不是状态或另一个事项类型：

```json
{"start":"2026-10-14","end":"2026-10-14","participants":["服务对象甲"],"organizations":["他山协会"]}
```

日期为北京时间闭区间，单日end省略等于start，未知时两者null。保留原记录更精确的时间描述；不编秒数。participants为实际执行/参与者，organizations为实际组织（可空），均最多50个不重复名称；未知留空，查询用“待定”。记录actor和at仍是实际保存作者和时间，不回填。

- `create_task`/`record`可以携带`work`，必须同时有非空`note`，其元数据保存在同一操作的进展中。
- `append_record`增加可选`work`；有work时必须objectIds关联已存在事项。独立已完成结果可直接`create_task(state='已完成', proposedAt=null, assignee='待定'或确知负责人, note=结果摘要, work=...)`，无虚构待办前序，也不要求本人再批阅完成事实。纯材料/进展仍不自动关闭已有事项。
- `query_work(start?,end?,person?,organization?,keyword?,cursor=0,limit=100,snapshot='')`：GET `/api/notebook/work`。返回objects（同一事项ID，每项附期间内workEntries、workParticipants、workOrganizations）、total、cursor、hasMore、snapshot、可筛选people/organizations、timezone。按业务区间重叠筛选，不按保存日；带日期范围时未知发生日不混入。人员查实际参与者，不查记录作者或负责人。日期不同时限定为只查今天。每页1—500，后页带返回snapshot；数据变化返回409，须从首批重读，勿混拼。
- 原始sourceRefs继续使用现有白名单，原件留Mac。记录详情/事项时间线附work与真实sourceRefs，已存旧文本与证据不改写。普通状态确认不会自动生成一份工作成果。

### 既有工作记录并入

授权设备可 POST `/api/messages/{id}/integrate-work`，SDK同名`integrate_work_record(id, body)`。显式传`expectedRecordHash=HTTPNotebookPort.work_record_hash(record_detail(id))`、`work`、稳定`requestId`，并且仅选一种：

1. 原事项：`objectId`及其当前`expectedRevision`。已有objectIds必须包含此ID；原为空可明确关联已有事项。原有关联全部保留。
2. 原来没有事项的独立结果：`task={title,state:'已完成',assignee?,domain?,counterparty?,completionCriterion?,relatedRecordIds?}`。不接受新建待办或替换已有事项关联。

事务原子地创建必要事项、补充原记录元数据/关联和操作审计。原记录ID、正文、actor、at、附件、sourceRefs、receipts、processing不改；已有事项的业务字段和关闭状态不改，仅增加真实关联修订。相同请求号/内容可重试，语义变化拒绝；原记录hash或对象版本变化返回409，不换版本盲推。已并入的记录不允许另号再建一份。仅用于显式列明的已有事实，不能批量猜测普通留言都是工作事实。
