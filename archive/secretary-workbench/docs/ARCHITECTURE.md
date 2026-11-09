# 系统边界

交互入口（指定桌面对话/绑定ClawBot/网页）→持久角色→独立工具。共同业务只经记事本正式接口；原始来源留来源侧/私有本机；角色工作区保留方法和未完；操作收据证明真实动作。

- NotebookPort：对象、记录、版本、安排、关联、批阅和历史。来源发生时间与提交时间不混用。
- Sources：已保存来源的身份、版本、资产、coverage和取得/阅读/应用检查点；实时连接器独立。
- OperationJob：只收业务参数，串行共享窗口、最终预览、显式确认和原生结果；读消息可并行。
- ClawBot：绑定本人原文/媒体进指定持久对话；不是普通微信好友发送接口，不自动跟随新分支。
- Conversation/host：真实持久对话交办、结果读取和回报，不是临时子智能体；共用工作区和业务真源不等于共享全部模型上下文。
- Secretary：合并连续信息，核旧交付/新独立结果/纠正、保留历史和证据；更新、汇报、派工和对外执行分别遵守授权。

本包是已有代码的脱敏移交，主程序架构未重建。Linux微信操作复用官方GUI和离线OCR，并非无GUI网络发送协议。目标名称、真实peer、实际标题/上下文必须独立核；相似字形、同人数、第一候选都不是身份依据。特定布局/动作/媒体范围未覆盖时明确失败。

代码和配置原先的个人路径、身份、thread、业务范围已抽为环境变量/通用占位或合成样例；不能据演示账号或示例群开工。已在用环境的真实运行验收不迁移到全新安装，本次打包测试另列。

## 分层图（仅技术示意）

- [01-layers](diagrams/01-layers.svg)
- [02-deployment](diagrams/02-deployment.svg)
- [03-entry-context](diagrams/03-entry-context.svg)
- [04-data](diagrams/04-data.svg)
- [05-dependencies](diagrams/05-dependencies.svg)
- [06-packaging](diagrams/06-packaging.svg)


## Current source cutoff: 2026-11-06

The original six boundaries remain. The common digital-employee Skill supplies reusable responsibility, collaboration, workbook, delivery and continuity methods; only empty templates are packaged. Notebook4.4 stores optional actual-work metadata on the same task/progress history, with the canonical HTTP port and source provenance.

The outbound path is still SDK/SSH -> original Store/dispatch -> current Policyv2 and original shared guards -> official WeChat preparation/preview -> one terminal action -> native receipt and owned cleanup. Client is attribution, not an independent security tenant. Manual is default; verified_fast is explicit for supported ordinary actions. Current card/merged-record readers retain parse/media/coverage distinctions. Unknown reconciles only the original request.

ClawBot remains a separate, explicitly configured fixed-conversation entry. Host collaboration adapters queue to existing real conversations; they do not create a second business brain. Unified inbound/delivery-health source is exported in host/continuity; the read-only observer backend and web are exported in monitor; the ordinary MCP adapter and scoped cross-host thin clients are exported in host. Actual routes, worker identities, role files, shared guards, official host authentication, schedules and the Mac-side gateway/collector still require the operator's own installation. No service is implicitly installed. Source and test availability does not constitute new-machine live acceptance. See REFRESH-20261106.md and SOURCE-CUTOFF.json.
