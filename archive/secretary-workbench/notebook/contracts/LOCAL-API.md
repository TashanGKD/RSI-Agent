# 本地闭环接口（实现共享契约）

本机独立模块运行，默认不向AUP或外部发布数据。UI以PRD3.2／UI3.1为参照，本地授权原文可见。模块只通过公开入口调用。

## 记事本公开Python入口（由root实现）

`modules.notebook.NotebookService(db_file, source_file, workspace)`：显式路径，不隐式选择正式库。调用可选actor={name:'我',kind:'human'}或{name:'AI秘书',kind:'ai'}；state六项其他/待办/等对方/暂缓/已完成/不用管了。unknown/旧待判断兼容为其他。支持旧ID和记录。

- `list_tasks()` -> 全部标准任务数组。
- `get_task(id)` -> 标准任务，找不到抛KeyError。
- `detail(id)` -> {task,timeline,evidence,relatedTasks,sourceLinks}。
- `create_task(body)` -> task。body允许title必填、kind(action/project/goal/memo)、domain(科研/他山/示例项目项目/个人生活/空)、state、assignee、counterparty、summary、proposedAt、timeRequirement、planDate、reviewDate、condition、relatedRecordIds、completionCriterion、recommendation、sources、requestId、actor、note、confirm。
- `record(id,body)` -> task。必须expectedRevision；其他同create的显式变更字段（无title必填）。note仅追加，不暗改状态；confirm:true才人工批阅。null清空安排。requestId幂等。
- `append_record(body)` -> record。body=text、objectIds(可空)、attachments(资产ID数组)、actor、requestId、可选sourceRefs(实际来源metadata)。先存原输入。
- `list_records()` -> records；`record_detail(id)` -> record。
- `set_record_processing(id,status,receipt='',object_ids=None)` -> record；status=pending/running/completed/failed；回执追加，原text不改。
- `query(view='today',domain='',assignee='我',date=None)` -> tasks；view today/review/all；北京日期。secretary可用list_tasks再判断。
- `attach_asset(name,data,mime=None)` -> {id,name,mime,size,url,path}（path仅Python内部，不出HTTP）；`asset(id)` -> 安全资产对象。

标准任务字段：id,title,kind,domain,assignee,counterparty,proposedAt,timeRequirement,deadlineDate,summary,state,selectedState(兼容同值),planDate,reviewDate,condition,needsReview,revision,active,recommendation:{state,reason}|null,relatedRecordIds,completionCriterion,evidence:[{label,quote,at?,sender?,url?}],sourceContacts。状态与confirm独立；未确认首次候选state其他、recommendation可不同；人可以直接决定。未安排历史待办不全部塞今天，today包括已到planDate的待办。来源JSON只作旧导入，不覆盖新操作。

record字段：id,text,attachments:[资产元信息],objectIds,actor,at,processing,receipts:[{at,status,text,objectIds}]。

## HTTP接口（由root实现，local_server.py）

GET /api/bootstrap -> {csrfToken,version,states,domains,tasks,records,sources,meta,today}。
GET /api/tasks/{id} -> detail。
POST /api/tasks -> {task}；POST /api/tasks/{id}/record -> {task}；POST /api/tasks/{id}/confirm -> {task}（显式confirm）。
POST /api/messages -> {record}；GET /api/messages -> {records}。
POST /api/uploads -> {asset}，JSON{name,data(base64),mime}，文件上限8MiB；GET /api/assets/{id} -> 二进制，安全MIME。
POST /api/secretary/run -> {job}，body{messageId?,requestId?}，不阻塞等待模型。GET /api/jobs/{id} -> {job}；GET /api/jobs -> {jobs}。job{id,status,stage,error?,result?,createdAt,updatedAt}，status queued/running/completed/failed。
GET /api/sources -> {sources}；POST /api/refresh -> 仅重载既有保存结果，不查新信源。
写请求同源Origin+X-CSRF-Token，JSON。400校验，409冲突，404不存在；失败不移除草稿。默认仅回环；如提供经授权局域网入口需身份校验，不把服务裸露。

## 秘书模块公开入口（由secretary agent实现）

`SecretaryService(notebook_port, workspace, model_runner=None, source_port=None)`；`submit(message_id=None, request_id=None)` -> job；`get_job(id)`、`list_jobs()`。model_runner可注入测试夹具；默认应能调用当前已安装codex exec只读、有限时、结构化JSON，不能把关键词规则当完整理解。输出操作经过严格白名单、版本、引用校验，再调用notebook_port。无执行器不自动宣称完成工作。CLI应可独立prepare/run/status，不接HTTP也能用。

## 信源模块公开入口（由source agent实现）

`SourceRegistry(workspace)`；`list_sources()` -> [{id,type,displayName,status,capabilities,coverage,gaps}]；`query(source_id,start=None,end=None,keyword=None,conversation=None,sender=None,content_type=None,limit=100,cursor=None)` -> {records,nextCursor,receipt,gaps}；`read(source_id,record_id)` -> 原记录；`import_records(source_type,account_id,records,...)` -> 收据。原记录含稳定id/sourceId/nativeId、at、sender、conversation、text、type、附件引用。各源独立目录。当前读取只使用已保存资料／显式导入，真实工具刷新需独立入口与真实收据，缺口明确，不启动旧常驻采集器。

sourceRefs为无原文定位，支持sourceId/recordId/nativeId/sender/conversation/at/type及版本/哈希/精度/页码/偏移，白名单见source_refs.py，原发言人与记录作者分开。来源由实际读取器附上，模型不能伪造引文元信息。已有已确认事项有实质新建议时可显式needsReview:true；普通备注不重入，模型不可needsReview:false冒充本人确认。

记事本公开 `validate_fields(body, creating=False)->True` 供整份模型计划预校验，失败在写入前报ValidationError；`modules.notebook`导出ValidationError/ConflictError。共享错误类型位于contracts/errors.py，旧store重导出保持兼容。


4.3工具能力的实际运行合同见[NOTEBOOK-TOOLS](NOTEBOOK-TOOLS.md)；来源版本、附件、收据与检查点见[SOURCE-TOOLS](SOURCE-TOOLS.md)。秘书和定时能力没有随工具升级开启。
