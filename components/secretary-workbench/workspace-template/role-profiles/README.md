# 可选择的固定职责

这里是职责profile，**不是五个必须新建的员工**。先找已有真实主责和持续对话，再决定同岗多职责还是按需协作；不要根据文件数量创建员工、账号或timer。具体责任、授权、来源与交付关系采用[现有七模板](../../skills/digital-employee/templates/new-employee/AGENTS.template.md)，共同方法仍读[正式Skill](../../skills/digital-employee/SKILL.md)，不把这些profile抄成第二套状态规范。

| 职责profile | 负责结果 | 现有实现 |
|---|---|---|
| [人事与共同方法](people-method.md) | 职责关系、共同方法、接续协调及实际采用分层 | digital-employee、codex-thread-handoff |
| [微信通道工具维护](wechat-tool-maintenance.md) | 同一工具实现、运行巡检、故障恢复与自有归位 | wechat、host/tools、host/continuity |
| [工作台监控维护](workbench-monitor.md) | 只读来源采样、投影和工作台 | monitor/backend、monitor/web |
| [共同业务记事本维护](shared-notebook.md) | 组织共同行动与实际工作事实的增量维护 | notebook、notebook-secretary |
| [机械发送协作者（按需）](mechanical-sender.md) | 原作者委托的同一原单实际执行与核回 | 原共用SDK或已有官方界面 |

## 三种“本”分开

- **个人工作本**：每岗自己的责任、当前理解、下一步和过程；沿workbook八字段与生成的CURRENT接续，不因身份是维护者就省掉自己的工作本。
- **共同业务记事本**：共享组织行动、参与者、进展、安排及历史的业务真源，经NotebookPort维护，不是各员工笔记的复制库。
- **只读监控**：从已授权原记录派生工作台展示。它的缓存/快照不成为业务真源，不回写员工笔记，不把空投影当全员没有工作。

## 创建或接续

1. 先读已有岗位入口和原未完工作；确需新资料区时，采用[七模板](../../skills/digital-employee/references/new-workspace.md)，保留原项目和真实持续对话。已有岗位只局部补职责，不覆盖历史或原STATE。
2. 将选用的profile链接到本岗ROLE，写清服务对象、输入、负责结果、协作者、交付去向和不能顺带办理的动作。可以一个对话链接多个profile；业务作者保留最终结果责任，工具/监控/方法维护分清。
3. 入口与依赖见各profile。路径、来源、官方宿主/账号及唤醒由自己的实例配置；配置字段按[现有索引](../../docs/INSTALLATION-SLOTS.json)和[schema](../../host/installation.schema.json)，不能用合成示例代替真实身份。结构同步、真实读取纠旧、后续任务效果分别核。
4. 每岗个人工作本用原[workbook.py](../../skills/digital-employee/scripts/workbook.py)检查/刷新。资料/发件/原生回执未取得就保留欠账，unknown查同原单，不因更换工具或协作者重复外发。

## 完整离线例子

[合成活动资料协作者](../../examples/synthetic-employee/README.md)包含七模板的完整对应、三件工作、共享来源、依赖和未知原单示意。它不是生产员工资料。现有[seed_monitor](../../examples/seed_monitor.py)可预览或在新临时目录复制这套例子、刷新CURRENT并生成原只读网页的合成投影。无需安装真实账号或创建员工；实际工作台records、员工目录、原生回执和凭据均不在包里。
