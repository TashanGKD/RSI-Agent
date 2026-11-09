# 日程API 4.3

实际持久字段与真源分工见[SCHEDULE-DATA](SCHEDULE-DATA.md)。

entries与entry响应增加summary；旧安排缺失时仅在响应补当前事项摘要，读取不写历史。

notebook模块拥有数据，服务端日期Asia/Shanghai。HTTP在既有登录／设备身份后读写，POST仍需固定Origin及CSRF；作者由在线身份设置。原有tasks/messages接口保留。

- GET `/api/schedule?start=2026-10-23&end=2026-10-23&assignee=我&domain=`：闭区间最多42天，返回entries、groups、overdue、unscheduled、range、timezone、coverage。无日期400，重复／未知条件400。assignee空代表全部。
- GET `/api/schedule/{id}`：entry＋history，版本、事项当前版本、作者、事件前后值。
- POST `/api/schedule`：`{objectId,date,startTime?,endTime?,expectedObjectRevision,requestId?,note?}`。明确给既有action安排；同事项同日已有则409，请编辑原次。新建action可用tasks接口携带state=待办、confirm=true、planDate、eventWindow原子建立。
- POST `/api/schedule/{id}/record`：`{expectedRevision,expectedObjectRevision,requestId?,state?,startTime?,endTime?,note?,postponeTo?,followup?}`。postponeTo为`{date,startTime?,endTime?}`，必须同时state=暂缓，目标晚于原次且不早于今天。原次、下一次、事项和备注一个事务。

HH:mm24小时制，时段可全空或仅开始，结束须同日且晚于开始。无时间不能虚构全天持续时长。跨日分日安排。date和time是北京本地值；eventWindow是明确带+08:00的ISO区间。旧接口planDate改期会留下旧暂缓记录；纯备注不改安排状态。

记录失败400/409不部分保存；同requestId不同内容400，相同内容重试不重复写。多个安排与事项共享expectedObjectRevision，旧事项版本不能覆盖秘书或另一设备更新。历史数据不移除；首次迁移覆盖起点明确，导入前每天状态未知。循环规则recurrence已支持显式定义与实例引用，完成实例不关闭定义；没有自动重复展开器。


普通暂缓/等对方复看：followup={date?,at?,condition?,remindEvenUnchanged?}|null。只修改复看，不改原计划/截止、不创建未来安排；暂缓允许没有日期。到期通过公开followups/批阅读取反映，不运行秘书。

postponeTo只用于明确改期；不自动设置reviewDate。已有更晚安排时，对旧次改期409，请改最新次。存在循环定义时POST schedule显式建立该日实例，检查规则与唯一性；历史与定义分离。
