# 证券智能体治理评测

面向证券机构的智能体上线验收和版本回归。首期以「证券研究资料助手」验证读取授权材料、核对公告口径、在测试表内完成受控更新的流程。交付形态为私有部署评测 API 和可接入 WorkBuddy 的 Skill + MCP 连接器。业务人员在已有产品中查看报告，风控与技术团队使用同一份结构化结果复核。

## 公开材料及使用边界

在本轮核查范围内，未找到可直接用于证券机构智能体验收的统一公开题集。以下材料各有具体用途。基础模型选型依据、通用风险框架、模型能力题和机构级智能体运行验收，分别记录适用范围。

| 来源 | 可复用的设计 | 落到本产品 |
|---|---|---|
| [证监会 JR/T 0357—2026，第 5 至 6 节](https://www.csrc.gov.cn/csrc/c101954/c7667691/content.shtml) | 基础大模型选型的合规、数据、算法、模态、安全和运营保障六个维度 | 建立条款映射和证据清单。组织制度、供应商能力等交由客户人工复核 |
| [证监会第 218 号令](https://www.csrc.gov.cn/csrc/c101953/c7202800/content.shtml)与 [JR/T 0250—2022](https://www.csrc.gov.cn/csrc/c101954/c6550642/content.shtml) | 网络及信息安全管理、数据全生命周期保护 | 由客户确定分类分级、只读数据视图、留存、脱敏和出网范围，逐条转成可复核控制项 |
| [NIST AI 600-1](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)、[ISO/IEC 42001](https://www.iso.org/standard/42001) | 自愿风险管理参考、组织 AI 管理体系要求 | 对齐风险登记、负责人、发布前评测、复测和事件处置。ISO 仅参考官网公开说明 |
| [CNFinBench](https://github.com/open-compass/CNFinBench) | 29 个金融专业、执行和安全合规子任务 | 优先参考金融场景覆盖和分级。项目主页未标明完整题集商用许可，首版采用自编数据 |
| [FinEval](https://github.com/SUFE-AIFLM-Lab/FinEval)、[FinanceBench](https://github.com/patronus-ai/financebench) | 中文金融题型、开卷财务问答和原文证据标注。FinanceBench 仓库公开 150 条样例 | 编写国内证券语境的报告期、单位、口径、公告更正和拒答题 |
| [BFCL 多轮评测](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)、[τ²-bench 评分](https://github.com/sierra-research/tau2-bench/blob/main/docs/running-the-benchmark.md#scoring) | 工具调用、必经动作、后端状态和基础设施错误计数 | 同时检查有序审批与最终写入状态，允许已确认等价的读步骤 |
| [AIR-Bench](https://github.com/stanford-crfm/air-bench-2024) | 政策条款映射到风险标签 | 参考分类方法，结合客户政策编制自有业务边界用例 |
| [Microsoft Foundry Agent Evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/agent-evaluators)、[LangSmith](https://docs.langchain.com/langsmith/evaluation-types) | 过程和结果分别验收，用历史任务比较版本 | 报告同时呈现失败步骤、最终状态及版本差异 |

评测集登记来源、版本、可获得范围、商业使用许可、标注人和适用场景。公开材料先作方法对照。客户内部题留在客户的隔离环境。发现与开发题重复的验收题，应移出验收集并补足对应风险分层。

## 已实现的本地首版

- **读取工具**按机构预登记的材料 ID 读取 UTF-8 文本、PDF 文本层、DOCX 正文和表格、XLSX 缓存单元格。返回材料 SHA-256 和页码、段落、表格或单元格位置。提取失败、无文本和摘要截断均有可见状态。试点材料由运维写入目录并登记清单。
- **评测工具**读取固定版本的案例，接收结构化问答或已记录的沙盒执行事件及终态。输出逐题判定、规则、定位、修正建议、四类状态计数与同条件版本差异。包含八条完全自编的问答和执行样例。
- **接入**一套 HTTP 与 MCP 后端，WorkBuddy 连接器模板位于 `connector/`。本地走独立实例、固定题集和单个令牌。令牌持有者能读取该实例登记的全部材料和题目，客户上线前需要收紧到角色和项目权限。实测使用官方 MCP Python 客户端，WorkBuddy 客户端接入待验证。

### 运行和接口

将 `GOVERNANCE_DATA_DIR` 设为本目录下 `examples` 的绝对路径，并将 `GOVERNANCE_TOKEN` 设为环境中独立保存的随机 ASCII 令牌（至少 32 字符）。以下命令在本组件目录运行。

```sh
uv sync --locked
uv run --locked python -m unittest -v
uv run --locked uvicorn server:app_from_env --factory --host 127.0.0.1 --port 8010 --no-access-log
```

接口使用 `Authorization: Bearer <token>`。局域网试点使用机构网关提供 HTTPS，并以网关验证身份。切换题集或材料时启动对应快照的实例。

| HTTP | MCP | 用途 |
|---|---|---|
| GET /v1/materials/{asset_id}?location=… | read_material | 查材料位置和证据正文 |
| GET /v1/cases | list_cases | 取固定题集版本和测试任务 |
| POST /v1/evaluations | evaluate_run | 提交一次测试记录 |
| POST /v1/comparisons | compare_runs | 输入 before、after 两份记录 |

问答观测包含 `case_id`、`answer.decision`（answer、abstain、escalate）、`answer.values` 和 `answer.citations`。执行观测包含 `case_id`、有序的 `execution.events` 及 `execution.final_state`，工具事件由测试环境记录。使用同一组 `dataset_id`、`dataset_version`、`conditions_id` 传入两版 `subject_version` 与各自的 `observations`。首版 `conditions_id` 由测试方登记，暂未接入签名运行清单。缺失记录给出未验证，基础设施故障单独统计。关键题失败时报告阻断，`completed` 表示评测已完成，最终上线判定由试点方确认。完整字段与运行示例见 `schemas.py`、`examples/` 与 `test_service.py`。

## 完整开发与验收方案

| 阶段 | 交付 | 验收 |
|---|---|---|
| 1. 确定试点和规则 | 业务确定研究公告流程，风控确认规则和关键失败，IT 提供权限矩阵、数据样例、脱敏要求及隔离测试环境 | 每条高风险规则都能关联适用角色、批准动作、数据来源、证据和负责人。确认首期接入范围后冻结 |
| 2. 完成读取接入 | 增加机构文档登记与上传、扫描件/OCR 路由、客户授权只读视图。材料访问校验用户、项目与数据级别 | 验证来源定位、版本更新、授权拒绝、权限变更生效和无文本页处理。对 WorkBuddy 实测传输路径，敏感材料仅在客户认可的处理边界内开放 |
| 3. 建立机构题集 | 初版规模建议 100 题，问答 60、执行 40。设计题、冻结验收题按发行主体或文档族分开。业务和风控双人标注，冲突交第三人复核 | 冻结题集、来源快照、政策版本和评分器。题目覆盖正常、边界和缺失数据。每道题能追溯标准答案和逐项判定依据 |
| 4. 实现测试运行与复核 | 接入客户测试 API。用沙盒执行工作流，记录角色、授权、动作次序、参数和前后状态，绑定被测版本、模型、Skill、工具和预算 | 同一隔离初态可复跑。覆盖重复提交、数据源超时、无审批和失败回滚。授权或审批被破坏即阻断。缺失证据单列，保持通过率分母透明 |
| 5. 客户接入与发布 | 真实 WorkBuddy 客户端加机构 HTTPS 网关。补上机构身份、按项目授权、异步任务和幂等 ID、脱敏审计及可导出报告 | 客户业务和风控抽查逐题证据并签署门槛，至少完成一次从材料读取到版本对比的原生调用。分开验证部署状态、可访问性和真实数据处理边界 |

题集以场景和风险覆盖为准。问答题覆盖公告更正、财务期间与单位、制度解释、缺证据及无权时转人工。执行题覆盖正确更新、审批先于动作、只读角色、重复事件和上游失效。每条记录应有题号、角色、规则版本、输入快照、预期结果、证据位置和严重度。执行题另记初始状态、允许动作、必经动作和终态。数值、单位、引用、动作与状态优先用确定性规则。开放回答后续增加经业务校准的评分细则和人工复核。客户另行确定分组门槛及错误预算。

本地首版已具备离线读证据、判定和比较。扫描件 OCR、现场数据库、主动运行被测智能体、生产身份与审计、WorkBuddy 真机和客户验收属于后续接入。公开仓库只保存合成样例、公开链接和实现。
