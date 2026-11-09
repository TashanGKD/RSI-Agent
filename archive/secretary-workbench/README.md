# Secretary Workbench

> 共同记事本、独立信源工具、普通微信操作、ClawBot同对话入口与数字员工共同方法的脱敏源码交接包。

2026-11-06沿原私有仓更新，保留原历史和六个边界。新增完整30文件的 `digital-employee` 共同Skill；微信部分来自当时已加载的AUP静态源码，包含dispatch、Policy v2、精确原生导航、读取卡片与合并记录、队列核账和收尾。记事本同步4.4的事项与实际工作记录。源码截止、逐文件SHA和打包适配见[来源清单](docs/SOURCE-MANIFEST.json)与[本轮边界](docs/REFRESH-20261106.md)。

这是私有代码与方法交付，不是当前生产环境的克隆，也不是安装后全部渠道即可工作的一体成品。所有示例为合成数据；账号、密钥、真实目标绑定、消息/媒体、数据库、画像和调度状态均不提供。现有服务不因本仓上传而改变。

## 从零运行本地记事本

建议 Python 3.10+（数据/HTTP核心仅标准库）。以下只创建新 `var/demo`，监听数字回环，不连接微信或云端、不运行模型和定时器：

```sh
python3 examples/seed_demo.py --workspace ./var/demo --apply
python3 notebook/local_server.py --workspace ./var/demo --port 8876
# 打开 http://127.0.0.1:8876/；Ctrl+C停止
```

初始化合成事项、备注和日程的结果见种子命令输出。无参数只显示帮助。不要将此本地演示导入或覆盖任何既有业务库。

演示入口默认拒绝模型执行，包括配置了同名环境开关的情况；只有显式 `--enable-codex-exec` 才可使用自己已配置/授权的本机Codex。没有自动接入现有生产实例。

## 常用命令

| 命令 | 用途 |
|---|---|
| `python3 examples/seed_demo.py --help` | 查看合成示例初始化，默认不写入 |
| `python3 notebook/local_server.py --help` | 本地记事本网页，必须指定工作区 |
| `(cd notebook && python3 -m unittest discover -s tests -p 'test_notebook.py')` | 数据核心回归（完整交付检查见 docs/VALIDATION.md） |
| `cd wechat && python3 -m operations.cli` | V2微信操作接口帮助，不接触微信 |
| `cd clawbot && python3 -m bridge.cli --help` | ClawBot工具帮助，不默认联网 |
| `node host/tools/conversations.mjs` | 真实对话协作帮助，不默认派工 |
| `python3 scripts/check_package.py` | 脱敏与默认交付结构检查，不打印命中的原值 |
| `npm ci --ignore-scripts` | 安装固定版本ws（无安装脚本）；不包含node_modules |

## 六个复用边界与目录

```text
notebook/          数据、权限、Web、日程、已保存来源模块及本机读取适配
wechat/            Linux原生读取、V2串行操作与必要原生编辑/文件辅助函数
clawbot/           ClawBot通信/多模态/固定持久对话适配
host/              桌面共享RPC辅助、薄客户端与真实对话交办/回报
skills/            共同digital-employee、脱敏秘书规范与独立工具使用手册
workspace-template/  可选的新工作区骨架，无本人画像或运行状态
examples/          合成资料与空白配置示例
scripts/           本地交付检查工具
licenses/          原样保留的第三方许可
```

六边界不等于六个新服务；职责与文件目录分开即可。来源接口负责取得事实；记事本接口负责保存和查询；秘书负责理解、协调和验收；执行者按授权完成交付。原件、业务状态、角色工作区和工具回执分开。

## 安装边界与可运行程度

| 部分 | 本包提供 | 另需准备/仍未验收 |
|---|---|---|
| 记事本本地数据/Web | 可在新合成工作区运行；版本、事务、备注、日程与历史代码 | 私有在线服务需要自己的域名/HTTPS、初始化凭据；不附生产数据或配置 |
| 已保存信源模块 | 本地导入、版本、资产、coverage与检查点 | cached_only不代表已连微信/飞书/会议；上游分别授权 |
| Mac微信读取 | 有界读取/语音/迟到资料适配源代码与手册 | Mac采集器/解码foundation由独立仓库另交；本包不复制该工程、授权材料、模型或聊天库 |
| Linux普通微信 | 当前原生读取、dispatch批量准入/核账、manual与显式verified_fast、草稿/导航收尾；卡片及合并记录的有界解析 | 官方Linux微信、X11/GTK、Pillow、自己的授权资料、准确账号/目标/布局/OCR；新安装账号未实机验收。建群/好友/二维码等以实际capabilities及配方为准 |
| ClawBot | 官方协议适配、媒体处理、同一持久对话传输与恢复代码 | 自己的ClawBot绑定、桌面App原生共享端口和显式允许thread；跨平台全链不承诺 |
| 语音与附件 | 身份/预算/哈希/保存与处理流程 | SILK/ASR工具或模型由操作者明确安装配置；没有附原音/文件或模型 |
| 飞书/腾讯会议 | 秘书调用约定与录制归档技能/脚本 | 官方lark-cli、组织profile、腾讯会议连接器单独安装授权；无第三方Skill整目录镜像 |
| 邮箱 | 现有只读IMAP/系统Keychain适配 | 自己的账号与Keychain条目；Mac特定接口，不附凭据 |
| 宿主协作/触发 | Mac薄客户端、AUP原生队列协作适配与共享端口辅助；共同Skill的接续方法 | 相应官方宿主、原生协议、精确已有对话及自己的工作区；统一事件系统/监控部署、调度与Mac文件网关由各原模块另配，不自动安装或启用 |

完整离线检查可先在独立虚拟环境安装 `requirements-tests.txt`；`scripts/run_checks.py --suite <notebook|wechat|clawbot|node|audit|recording> --execute` 仅跑选定合成测试，资源相关未覆盖项见验证文档。

## 文档与Skill

- [架构与边界](docs/ARCHITECTURE.md)
- [安装与配置](docs/INSTALL.md)
- [微信唯一操作接口](../../components/wechat-linux/docs/OPERATIONS-API.md)
- [微信只读接口](../../components/wechat-linux/docs/TOOL-API.md)
- [秘书更新入口](skills/notebook-secretary/SKILL.md)
- [数字员工共同入口](skills/digital-employee/SKILL.md)（30文件的方法、参考和空白模板）
- [真实对话交接入口](skills/codex-thread-handoff/SKILL.md)
- [2026-11-06更新与实例化边界](docs/REFRESH-20261106.md)
- [文件来源与许可](docs/PROVENANCE.md)
- [脱敏、排除项与验证](docs/VALIDATION.md)

## 配置和环境变量

`.env.example`仅是字段示意，不自动加载，也不包含可用凭据。显式导出或通过自己的进程环境提供。移植配置`SECRETARY_INSTALLATION_CONFIG`读取操作者指定的普通可读JSON，支持相对路径、`~`和软链；统一路径基准见[当前组件说明](docs/CURRENT-COMPONENTS.md)。真实账号与运行资料不随本包分发。

| 变量 | 含义 | 需要时机 |
|---|---|---|
| `SECRETARY_WORKSPACE` | 自己的新私有角色工作区 | 真实对话协作 |
| `SECRETARY_NATIVE_SOCKET` | 自己的受控桌面原生socket | 原生协作薄客户端 |
| `SECRETARY_MAIN_THREAD_ID` | 协作回报的主秘书对话，与ClawBot固定交互路由独立配置 | 真实对话协作 |
| `SECRETARY_THREAD_ID` | 明确允许接入的唯一持久对话 | ClawBot原生接入；两侧必须一致 |
| `SECRETARY_SENDER_THREAD_ID` / `SECRETARY_SENDER_WORKSPACE` | 自己已有的AUP发送责任对话与私有工作区 | 可选宿主协作；不是微信client权限开关 |
| `SECRETARY_CODEX_HOME` / `SECRETARY_CODEX_BIN` | 自己已受支持的官方Codex安装与已有认证目录 | AUP原生协作；缺配置拒绝启动，不附认证材料 |
| `WECHAT_SSH_HOST` / `WECHAT_REMOTE_CODE_ROOT` / `WECHAT_REMOTE_STATE_ROOT` | 自己的SSH别名、远端代码与状态路径 | 薄客户端显式执行 |
| `WECHAT_TOOL_ROOT` | Linux微信工具的独立私有运行目录 | 已授权Linux读取/操作 |
| `WECHAT_NATIVE_CODE` / `WECHAT_HOST_SUPPORT_CODE` | 本包wechat及其host_support代码目录 | Linux运行 |
| `WECHAT_PROFILE` / `WECHAT_ACCOUNT_ID` | 自己已授权的准确资料路径/账号 | 原生读取 |
| `WECHAT_MAC_ACCOUNT_ID` / `WECHAT_MAC_FOUNDATION` | Mac账号/另交解码组件 | Mac读取 |
| `WECHAT_OCR_ROOT` / `WECHAT_OCR_RUNTIME` | 另安装的OCR资源目录 | 已校准UI操作 |
| `SECRETARY_MAIL_ACCOUNT` / `SECRETARY_MAIL_KEYCHAIN_SERVICE` | 自己的邮箱身份与系统条目名 | Mac邮箱读取 |

部分历史维护参考保留了通用占位部署布局，仅供后续适配，不能原样视为部署命令。无参数入口和演示不应访问已有账户。

## 部署、权限与交付边界

本仓没有自动部署Actions，不推送生产服务，不修改系统或账号权限，不恢复监听/定时。Linux/桌面接入需操作者按当前官方客户端和许可逐项校准，不能复用别人的目标绑定。`submit → 实际核最终预览 → confirm → 原生读回`是普通写流程；unknown只核账，不能换ID重发。分派不表示业务完成。

当前Policy v2中的client用于归属与回执，不再以逐client/peer/action名单建立权限租户。拥有宿主工具权限的调用者仍须遵守真实业务授权；身份、原件、草稿、共享guard、单次终端动作和原生回执校验保留。空示例配置也不是一个对所有已登录微信账户安全隔离的沙箱；新安装没有原登录、凭据、绑定或运行资料。优先级不授予业务授权。

普通新文字/图片/文件可显式选择 `verified_fast`，缺省仍为manual。先上传自己的原件，再核当前源条件后用同一个 `dispatch_batch` 准入；pending等原ID，review_required审预览，unknown核原单。新安装未做真人收发、跨平台或长期运行验收，历史生产成功不能代替这些条件。

仓库保持私有；成员GitHub身份与read权限由任务主协调者单独落实。私有上传、组织成员身份和具体成员实际可读是不同验收，本包不会默认给write/admin或打开公网。

Skill以本仓内相对文档为准；可直接让AI读取对应SKILL.md。宿主自动发现/安装方式按其自身文档配置，本包不会自动覆盖已有同名Skill。

## 11月6日补齐的当前组件

同仓已追加 `host/continuity/` 统一入站/@/点名接续与delivery-health消费者、`monitor/backend/` 和 `monitor/web/` 只读监控，以及 `host/aup-sender/` 普通MCP/跨host薄包装。现有SDK、原生队列和回执复用；没有第二个发送器或业务模型。实际注册、11岗资料、运行数据、认证和定时不随源码移交。

主微信源码另已接上同日21:14实际发布的phase2资源/图像/asset复用差量，并于22:06:20冻结相关原源SHA；此前普通配置helper纠正保留。该批剩余工作及未发布phase3候选没有冒充完成或纳入代码。新截止、逐文件哈希和实际边界见 `docs/SOURCE-CUTOFF.json` 与 `docs/CURRENT-COMPONENTS.md`。

共同方法另已采用正式 `digital-employee-20261107-merged-queue-closeout-91198fef284c` 增量：数字员工方法仍在 `skills/digital-employee/`，原生对话交接在 `skills/codex-thread-handoff/`，记事本机制与微信工具保持各自原目录。协作回报按同一原事项合并消费，保留真实未完与未知原请求；人工核定后先归档原文，再通过已有官方队列接口收口，不逐条回投“已核收/无新增动作”。[一次性收口脚本及合同](skills/codex-thread-handoff/references/native-delivery.md)默认help，带计划不加`--execute`只预览，不连接。它不是自动判定业务完成的服务，也不安装后台或操作微信作业。

随后已采用正式共同方法 `digital-employee-20261107-responsibility-recovery-adoption-31eb12ed0ba6` 的六文档增量，前版保留在Git历史。业务负责人持续负责最终交付，成熟操作无需额外发送AI审批；工具实现由原维护者、人事/方法维护由原责任方承担。文件发布同步、原岗读取纠旧及真实任务采用效果分别留证，普通回报不强制另索终态确认。该更新只导出通用方法，不代表本包替所有岗位完成了采用验收；原一次性队列脚本和工具快照未变。

## 固定职责与完整合成工作本

[职责profile索引](workspace-template/role-profiles/README.md)补齐人事/共同方法、微信通道工具维护、工作台监控维护、共同业务记事本维护及按需机械发送五类职责。它们不是五个必须新建的员工，可以复用已有主责或同岗多职责；个人工作本、共享业务本与只读监控分别有明确维护者。

[完整合成活动资料协作者](examples/synthetic-employee/README.md)沿原七模板展示责任/关系/来源、三件工作与生成CURRENT：资料待补、unknown原请求、独立本地结果完成分别保留。例子没有真实账号、线程绑定、原生回执、registry或调度；不因网页展示就宣称生产员工已接入。

```sh
python3 examples/seed_monitor.py --output /your/new/demo
# 仅预览，不创建目录或连接外部。
python3 examples/seed_monitor.py --execute --output /your/new/demo
python3 skills/digital-employee/scripts/workbook.py check --root /your/new/demo/employee
```

输出必须是新目录，可以位于普通可写临时路径；使用原工作本脚本及原监控投影，不另造格式。详情含原schema配置与只读网页启动方式。任何真实实例仍需自己的职责/来源、宿主与账号、官方目标和持续唤醒分别配置验收；本轮未操作真实employees工作台、401鉴权、微信或timer。

| 文档/命令 | 用途 |
|---|---|
| [当前组件与安装边界](docs/CURRENT-COMPONENTS.md) | 包含/排除范围、空配置、合成网页、MCP及真实未验条件 |
| [配置字段索引](docs/INSTALLATION-SLOTS.json) | 操作者自己的路径、岗位归属与可选适配字段，不含实例值 |
| [只读贡献方式](CONTRIBUTING.md) | Read协作者本地feature分支交patch/bundle，由维护者审核代推 |
| `python3 scripts/run_checks.py --suite continuity --execute` | 统一接续合成回归 |
| `python3 scripts/run_checks.py --suite monitor --execute` | 只读采样、隐私投影、交付证明合成回归 |
| `npm ci --ignore-scripts && npm test && npm run build`（在monitor/web） | 网页测试、类型与构建；不含真实投影 |
| `python3 scripts/check_mcp_stdio.py --execute`（先安装可选MCP依赖） | 仅隔离工具发现和缺配置拒绝，不联系微信/员工 |

网页第三方字体/位图未捆绑，采用系统字体和纯色后备；源码导出与上述离线检查不等于新机器微信收发、跨host认证或长期运行验收。仓库仍为私有，read邀请及实际成员可读由原协调者核实；本轮未改权限、保护或可见性。
