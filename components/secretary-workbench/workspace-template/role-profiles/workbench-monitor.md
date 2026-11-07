# 工作台监控维护

## 输入与负责结果

输入是已授权岗位的原入口、个人工作本、原任务/对话可见元数据与必要工具收据。负责只读采样、归属/状态/来源覆盖/交付证据投影和工作台页面；它维护“怎样准确看见”，不成为原业务的负责人或真源。

## 入口与输出

- [原后端](../../monitor/backend/work_observer.py)、[只读周期](../../monitor/backend/live_update.py)、[元数据读取](../../monitor/backend/read_runtime.mjs)、[唯一投影合同](../../monitor/backend/work_contract.py)。
- [原网页](../../monitor/web/src/App.tsx)、[GET/HEAD展示](../../monitor/backend/serve.py)、[投影发布](../../monitor/backend/live_core.py)和[原在线投影路径](../../monitor/backend/online_sync.py)。
- [配置字段](../../docs/INSTALLATION-SLOTS.json)、[普通配置schema](../../host/installation.schema.json)及[合成演示入口](../../examples/seed_monitor.py)。
- 输出：可追溯的派生视图、原来源截止/缺口、当前采样状态与具体错误。缓存和网页里的状态不反写到员工工作本。

## 依赖与边界

操作者需自己的岗位映射、授权来源、原始工作本格式、宿主只读端口和必要初始coverage；本包空配置没有生产records。原已存在的线上401是鉴权边界，不能据此称服务故障或绕登录。公开投影和私有原件分开，不能直接复制真实工作台data到交付仓。

## 接续

先复用原monitor，不建第二份监控或要求员工填专用报表。源暂不可读保旧值与缺口，空目录/0条不推成全员无欠交；机械发送成功与原作者业务完成分别核。需要修源格式/读取时沿本维护职责最小适配，员工仍改自己的原笔记。监控不发件、不确认业务、不创建员工或调度；自身定时运行是实例明确配置，不由此profile默认开启。
