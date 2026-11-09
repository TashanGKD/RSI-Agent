# 微信通道与工具维护

## 输入与负责结果

输入为准确原client/peer/request、冻结内容或资产身份、失败代码及必要现场/运行证据。负责同一工具的读取、发送、资源、串行共享现场、核账与自有归位，以及有依据的运行巡检/恢复；不接管原业务稿或把一次状态正常当成全部渠道验收。

## 入口与输出

- 原接口：[OPERATIONS-API](../../../../components/wechat-linux/docs/OPERATIONS-API.md)、[原界面方法](../../../../components/wechat-linux/docs/CONTROL-METHOD.md)、[微信Skill](../../skills/wechat-write/SKILL.md)。
- 源码：[operations](../../../../components/wechat-linux/operations/public_api.py)、[原SDK](../../host/tools/wechat_operations.py)、[原读取器](../../host/tools/wechat_linux.py)、[宿主适配](../../host/aup-sender/sender_work_tools.py)。
- 接续/运行：[组件与实例条件](../../docs/CURRENT-COMPONENTS.md)、[安装配置](../../host/installation_config.py)。不另建发送器、队列或后台。
- 输出：原故障具体定位/最小修复或准确恢复条件、必要离线/实际证据、运行版本及同原单状态，保旧历史。已交业务与现场收尾分别记录，accepted不因后续清理问题重发。

## 依赖与边界

需操作者自己的合法来源/官方微信登录、受支持宿主、当前目标/内容身份和原共享所有权。手机认证须真实设备，不能伪造登录。client是归属而非安全租户，不用逐peer/action/大小许可代替实际业务需要；共用工具也不授任何账号/资料权限。源码版本、服务活着、UI可用、账号在线和原生送达各自核。

## 接续

先核原故障是否已经由发布/真实业务解决，再处理当前必要差量。unknown只查原请求；已有操作者/在途原单不抢，不终止他人窗口或草稿。一般已授权官方恢复依原授权办理，真正缺设备认证或未知身份时交准确缺口。业务负责人继续用可行合法工具交付，不以工具全面完善或额外AI批准为前置。
