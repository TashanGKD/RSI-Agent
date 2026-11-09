# 正式记事本接口

阅读仓库notebook/contracts/NOTEBOOK-TOOLS.md、SCHEDULE-API.md、SOURCE-TOOLS.md及modules/notebook/http_port.py。先核实际capabilities，不猜路径或字段。

在线使用HTTPNotebookPort(base_url, device_token, private_cache_workspace)；URL和凭据来自自己仓库外600配置，不使用本包示例地址登录。认证/Origin/CSRF/禁止重定向由适配器负责；不直写线上SQLite或回退旧主库。requestId遵循实际validate_id合同。

备注、对象状态、安排、呈报分别操作，也可用实际原子组合；纯备注不暗改状态/确认。实际工作事实复用append_record、sourceRefs与可选objectIds，写后record_detail读回；set_record_processing completed仅表示记录已整理，不是业务完成。没有独立eventAt字段就不臆造，text/来源保留业务发生时间，record.at是提交时间。

来源检查点区分取得/阅读/应用；已写成功但响应丢失先同请求读回，不能新建重复记录。409基于最新内容重判；历史恢复先preview并显式更正，不删除后续历史。
