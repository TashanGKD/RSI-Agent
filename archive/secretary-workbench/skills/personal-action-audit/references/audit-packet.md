# 覆盖审计包

用于「全部」盘点的轻量账本，不是新消息数据库。复用原文文件和读到的位置；下列JSON为结构示意，示意值不能当真实证据。

```json
{
  "scope": {
    "mode": "as_of", "timezone": "America/New_York",
    "as_of": "2026-10-20T12:00:00-04:00",
    "source_start": "2026-08-01T00:00:00-04:00",
    "source_end_exclusive": "2026-10-21T00:00:00-04:00",
    "required_channels": ["wechat"], "user_excluded_source_ids": []
  },
  "channels": [{
    "id": "wechat", "enumeration": "complete", "pagination_exhausted": true,
    "identity_verified": true, "range_verified": true,
    "enumeration_receipt": {"source_file": "inventory-wechat.json", "source_sha256": "该目录回执文件SHA256"},
    "inventory_ids": ["wechat:account:group:part1"]
  }],
  "sources": [{
    "id": "wechat:account:group:part1", "channel": "wechat", "kind": "chat_text",
    "status": "read", "units_total": 93, "read_ranges": [[1,93]],
    "unit_basis": "固定顺序的可见正文片段", "semantic_read": true,
    "scope_verified": true, "date_basis": "native_timestamp", "body_sha256": "完整正文SHA256"
  }],
  "evidence": [{
    "id": "wechat:account:message123:body", "source_id": "wechat:account:group:part1",
    "kind": "original_text", "actor": "通知人", "occurred_at": "原时间",
    "normalized_at": "2026-10-16T08:00:00Z", "date_basis": "native_timestamp",
    "locator": "message123及正确行号", "source_file": "sources/notice.txt",
    "source_sha256": "所引用文字文件SHA256", "line_start": 3, "line_end": 3,
    "quote": "10月23日前邮件反馈题目", "quote_kind": "verbatim"
  }],
  "followups": [{
    "id": "notice-mail", "parent_source_id": "wechat:account:group:part1",
    "kind": "email", "required": true, "status": "pending", "resolved_source_ids": []
  }],
  "actions": [{
    "id": "action:topic", "counterparty": "通知人", "action": "邮件反馈题目",
    "proposed_at": "2026-10-16", "kind": "notice", "attribution": "self",
    "applicability": "possible", "applicability_evidence_ids": [],
    "deadline_text": "10月23日前，未给时刻", "deadline_role": "personal",
    "deadline_evidence_ids": ["wechat:account:message123:body"],
    "status": "unknown", "evidence_ids": ["wechat:account:message123:body"]
  }]
}
```

## 独立目录回执

每个渠道先保存完整原生目录/逐页响应到来源映射的回执，再选阅读顺序。不能从已选阅读队列反向生成这个目录。保留原查询与原生目录定位；回执不包含登录令牌。

```json
{
  "channel": "wechat",
  "inventory_ids": ["wechat:account:group:part1"],
  "pagination_exhausted": true,
  "identity_verified": true,
  "range_verified": true,
  "capture_basis": "完整原生目录、查询窗口、分页终点及映射依据"
}
```

校验器会读取并核对回执哈希、完整ID集合和分页状态，不能通过同时删掉sources及inventory_ids中的未读群来通过检查。回执自身是否真实代表服务端完整目录仍需根据原查询/原响应核实；脚本不伪造这个事实。

## 约定

- `mode`：`source_window/as_of/due_day`；到期日另给`due_on: YYYY-MM-DD`，不替代历史来源搜索。
- 截至时点和窗口边界带UTC偏移；边界偏移与`timezone`一致，结束日次日零点考虑夏令时。日级原日期不强行归秒级，证据有可靠时刻才给`normalized_at`。
- `required_channels`据用户范围和已知实际信源填写，不为过检查删掉不可访问渠道。`inventory_ids`来自完整目录，记录未读群和附件，不只是关键词命中集合。
- 来源状态：`read/partial/unavailable/deferred/excluded`。单位从1编号，可为消息片段/页/段落，需说明固定口径；已读范围无遗漏、无重叠覆盖`units_total`且确为语义阅读。零内容不是全文读完。
- 日期依据：`native_timestamp/document_date/verified_mapping/unknown`。文件名日期属unknown，保留范围缺口。
- 排除原因：`outside_requested_dates`须有实际日期依据及`exclusion_proof`；`exact_duplicate`须`duplicate_of`指向已全文读且`body_sha256`相同的来源，并设`metadata_reviewed: true`确认各条发送人/时间/版本已核（只复用正文阅读，不合并事件）；`confirmed_not_applicable`须全文已读且有核实依据；`user_excluded`须ID在用户明确排除清单。没有本人发言/点名不合法。
- 必要追查：`resolved`须指向已处理的`resolved_source_ids`；`not_applicable`须`resolution_basis`。pending/unavailable/deferred是缺口。官网、邮件、名单、图片/内件不能只凭标题写resolved。
- 每项须有主视图字段以及kind、attribution、evidence_ids。kind为`explicit/notice/reply/self_intent/waiting/candidate/information`；状态为`open/waiting/conditional/unknown/done/cancelled/superseded`。不确定归属或通知适用性不写open。
- 通知适用已确认须有`applicability_evidence_ids`，可来自名单/真实身份/直接请求。不是单独一条@所有人。
- `deadline_role`：personal/unknown/none。秘书/对方日期放related_dates标角色，不能作为个人截止。个人截止有deadline_evidence_ids。
- 完成/取消/替代须completion_evidence_ids、completion_scope。done另给required_stage和completion_stage：`sent/received/accepted/published/signed/approved/paid/performed`。收到可以证明发送，其余阶段不自动替代；superseded另给现存superseded_by。
- 证据ID全局唯一，必须有来源、类型、发言人、原时间、原生定位。逐字引语必须有source_file、SHA256、精确line_start/end和quote；仅可在声明行范围匹配。排版空白需忽略时设normalize_whitespace=true。
- `quote_kind: paraphrase`标非原话，仍保留来源定位。ASR/OCR/可见邮件抄录在kind区分。引用核对通过不证明说话归属或执行状态。

## 运行与解释

```bash
python3 scripts/verify_audit.py /absolute/path/to/audit.json
python3 scripts/verify_audit.py /absolute/path/to/audit.json --source-root /specific/existing/text/directory
```

默认只允许包目录内文字；其他原文根须显式指定，不允许整个根目录或用户主目录。脚本不联网、不抓取、不读凭据、不执行文件、不写文件；只向stdout打印不含原文/秘密值的结果。

退出0：账本/引用检查通过且无覆盖缺口；1：有错误或缺口；2：输入/调用错误。错误表示账本或引用不一致，缺口表示未完成读取/追查/范围判断。两者都阻止coverage_complete。

检查不证明语义绝无遗漏。仍须执行通知追查、要求逐条映射和反向补漏。输入和引用文件有大小上限，超出时分批或引用小型提取，不复制大库绕过限制。
