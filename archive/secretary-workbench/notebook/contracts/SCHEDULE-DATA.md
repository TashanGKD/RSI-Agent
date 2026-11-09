# 日程4.2实际数据结构

本文件对应modules/notebook/service.py与schedule.py的实际实现；不是更广V4的未来schema。迁移不重写原事项和批注。唯一可写主库仍为线上notebook.sqlite3。

## 真源分工

| 内容 | 持久位置 | 读取方式 |
|---|---|---|
| 一件事情现在是什么 | local_objects.payload基线＋local_changes按seq追加变化 | NotebookService.get_task；不以页面草稿为准 |
| 该事项某天的安排和当天状态 | schedule_entries当前行＋schedule_events追加历史 | get_schedule / query_schedule |
| 本人／秘书备注 | local_changes.payload.note，或local_records.text关联同一事项 | detail合并时间线；不会无痕覆盖旧备注 |
| 全局留言及附件 | local_records、local_assets | 原有公开端口；与日程状态分开 |
| 请求幂等 | local_requests | 正式操作同事务保存；同键异内容拒绝 |

事项和安排是两个身份。一件事可以有不同日期的安排，同事项同日只能一条。改期保留旧次并关联下一次，不能靠改标题或复制事项表达。事项是一次性交付时，当前安排完成也同步事项闭环；更晚安排存在时，修改旧次不会覆盖事项当前状态。

## schedule_entries

| SQL列 | 类型 | 含义 |
|---|---|---|
| id | TEXT PRIMARY KEY | SCH-加事项ID／日期哈希的稳定安排ID |
| object_id | TEXT NOT NULL | 原事项稳定ID，由服务验证存在 |
| date | TEXT NOT NULL | 北京日期YYYY-MM-DD |
| start_time | TEXT nullable | HH:mm；可空 |
| end_time | TEXT nullable | HH:mm；可空，若有必须晚于开始 |
| state | TEXT NOT NULL | 其他／待办／等对方／暂缓／已完成／不用管了 |
| revision | INTEGER NOT NULL | 每次正式安排事件递增，重试不增加 |
| assignee | TEXT NOT NULL | 负责人显示值，与记录作者独立 |
| domain | TEXT NOT NULL | 科研／他山／示例项目项目／个人生活，未知空串 |
| payload | TEXT NOT NULL | 下列完整安排JSON，与查询列同事务一致保存 |

约束UNIQUE(object_id,date)；索引(date,assignee,domain,state)。payload包括上述字段对应的camelCase名字，以及title、summary、previousEntryId、nextEntryId、createdAt、updatedAt，导入安排可有importedAt。definitionId与occurrenceKey目前为空扩展位置，不是已实现的循环定义。

API读取时附加objectRevision，是此刻关联事项版本，不是安排行内过时缓存。安排revision和事项revision都要提交，避免另一设备或秘书新增信息后被旧界面覆盖。

## schedule_events

| SQL列 | 类型 | 含义 |
|---|---|---|
| seq | INTEGER PRIMARY KEY AUTOINCREMENT | 本表正式提交顺序 |
| event_id | TEXT UNIQUE NOT NULL | SEV-稳定事件ID |
| entry_id | TEXT NOT NULL | 所属安排 |
| at | TEXT NOT NULL | 服务端真实记录时刻，ISO带偏移，展示转北京 |
| actor | TEXT NOT NULL | 已验证作者JSON：name、kind |
| before_value | TEXT NOT NULL | 变更前安排JSON，首次为null |
| after_value | TEXT NOT NULL | 变更后安排JSON |
| note | TEXT NOT NULL | 当次备注，可为空 |

事件不更新、不删除；状态更正也追加。备注同时进入共同记事本时间线，其他入口可以看，不建立第二套“补进度”日志。日程历史按seq读取，不冒称迁移之前每日状态已知。

## schedule_meta

key TEXT PRIMARY KEY，value TEXT NOT NULL。import_v1保存版本、实际导入时刻、导入条数及历史覆盖说明。重启不重复导入，旧事项业务表摘要不变。

## 事务与兼容

修改安排在同一BEGIN IMMEDIATE事务中验证身份／字段、安排版本、事项版本和requestId。暂缓时创建或复用目标日安排、修改旧次、追加事件、追加事项变更／备注、写幂等回执；任一步失败全部回滚。纯备注不改状态或批阅。

旧tasks record/confirm仍可用：只同步当前planDate对应安排，改期留下旧次，清除计划留下撤销记录；更早日期不被后来状态覆盖。无日期旧待办只通过兼容查询呈现，不凭空生成最初日期。完整备份应保留整个记事本数据库和受管附件；旧一次性cloud_projection迁移格式不等于4.1日程全量备份。

4.2兼容：旧安排payload没有summary时，接口用当前事项摘要补全展示，不迁移或重写旧事件。其他说明属于同次note正文，不另建表或字段；行内日期仍走既有postponeTo事务。
