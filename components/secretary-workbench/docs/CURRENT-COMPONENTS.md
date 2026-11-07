# 11月6日系统范围补齐

这次在同一私有仓库追加三个已存在的系统组件。只改交付副本，没有重建生产系统、复制运行实例或开启后台。各模块有自己的源码截止，详见 SOURCE-CUTOFF.json；不能把它们称为一个同时冻结的生产镜像。

| 入口 | 已导出的职责 | 操作者仍需提供 |
|---|---|---|
| `host/continuity/runtime.py` | 同一账本接住原生@、本人明确点名、busy/queued等待、合并接续、稳定ID与unknown核对 | 自有注册、既有对话/历史投影、工作入口、官方CLI和读取通道 |
| `host/continuity/native_source.py` | 有界原生来源身份、真实at列表、当前引用文字边界、覆盖缺口 | 自有合法读取环境和账号，不附库、密钥或来源记录 |
| `host/continuity/delivery_health.py` | 消费只读交付健康投影；交办、业务执行和原生送达分别核 | 明确client归属/owner，自己的监控投影和主管对话 |
| `monitor/backend/`、`monitor/web/` | 原只读采样、员工元数据/工作/交付投影、历史和关系展示；GET/HEAD网页 | 空配置外的每一项岗位/路径/来源范围与启动决策 |
| `host/aup-sender/sender_work_tools.py` | 普通MCP工具转发到同一读写SDK、原发送岗交办/回报与受限Mac文件client | 自有工作区/OWNER、官方Codex认证和宿主、MCP、原操作器、Mac端授权网关 |
| `host/tools/wechat_sender.py` | Mac到原发送岗的薄包装、稳定交办和原结果查询 | 明确SSH别名/远端API/本地回执目录；不附主机地址/凭据 |

监控映射不是发送权限。client是归属元数据，不是独立安全租户；入站优先级、被@或监控发现问题均不扩业务授权。监控不派活、不发送、不修改被观察员工的源工作本；其自身缓存和网页投影与业务真源分开。

## 配置与合成启动

`SECRETARY_INSTALLATION_CONFIG` 指向操作者指定的普通可读JSON配置，可使用相对路径、`~`或软链。读取遵循操作系统本身的可读性，不另限制UID、mode、文件大小或禁止软链。配置文件名的相对路径基于启动时当前目录；配置内所有路径字段（含列表、映射和岗位路径）统一基于**操作者指定的配置文件所在目录**，不是配置软链目标文件的目录；`~`按当前用户环境展开，路径软链由操作系统正常跟随。缺省映射/身份/来源列表为空，缺省路径仍在本包`var/unconfigured/`，不访问原真实系统。复制 `examples/installation.template.json` 后填写自己的值。字段索引见 `INSTALLATION-SLOTS.json`，类型见 `host/installation.schema.json`。此处只做移植配置，不新增权限门禁；各原工具自身的业务合同保持。

统一接续的空注册模板为 `examples/continuity-registry.template.json`，刻意不能启动；实际 `runtime.registry()` 还核账号、别名、路径/工作入口、owner、消息身份和私有文件边界。schema是结构说明，不能代替运行校验。配置 `continuity_workspace` 为注册所在的私有根；`continuity.runtime.HOME` 是自己的官方Codex资料根，不能给别人HOME。需要远端来源时，显式配置原已授权SSH读取命令；不自动安装watcher或timer。监控工作区与接续根的对应由自己的安装配置明确，不附真实注册表。

仅看合成网页可这样做，示例输出目录必须不存在：

```sh
python3 examples/seed_monitor.py --execute --output "$PWD/var/monitor-demo"
```

将自己的私有安装配置中 `paths.monitor_workspace` 指向该合成目录，然后：

```sh
cd monitor/web
npm ci --ignore-scripts
npm run build
cd ../..
SECRETARY_INSTALLATION_CONFIG=/absolute/private/installation.json python3 monitor/backend/serve.py --execute --port 18974
```

只监听回环地址，无写路由。此示例只展示合成投影，不调用collect、模型、微信或员工对话。原live采样依赖操作者的初始coverage/state与来源适配，没有把旧生产seed或11岗快照伪装成通用初始化器。在线同步缺省关闭；只有操作者私有online配置与安装层明确的SSH/root/URL精确一致才可执行，不能直接当公网发布入口。

## MCP与跨host

原宿主已核依赖为 `mcp==2.3.0`；在自己的隔离Python环境安装 `host/aup-sender/requirements.txt`。只开启MCP需显式 `--mcp-sender` 或 `--mcp-caller`，无参数不启动。sender暴露8个原薄工具、caller暴露2个交办查询工具，无第二个模型、微信队列或监听服务。

本地原操作器需设置 `SECRETARY_OPERATIONS_CODE`、`SECRETARY_OPERATIONS_STATE`、`SECRETARY_OPERATIONS_CONFIG`；读取器需 `SECRETARY_NATIVE_READER`。它们是管理员配置的本机路径，不从业务请求接受任意服务端文件。原上传、配额、预览、单次终端动作和核账仍由原SDK/操作器执行。未配置不会退回旧主机或偷偷选择账号。

Mac文件薄client需 `SECRETARY_MAC_SSH_TARGET`、`SECRETARY_MAC_SSH_KEY`、`SECRETARY_MAC_SSH_KNOWN_HOSTS`。保持严格host pin与原 `access-v1` 强制命令，服务端范围仍由操作者原网关决定。这里没有key、pins、Mac网关服务或采集器工程。原Mac发送岗client另需 `SECRETARY_SENDER_SSH_HOST`、`SECRETARY_SENDER_REMOTE_API`，回执根可用 `SECRETARY_SENDER_RECEIPTS` 配置；不是微信业务client权限开关。

## 去实例化与剩余条件

- 未带真实registry、OWNER、routes、event DB、队列、检查点、角色/个人工作本、来源/媒体/截图、网页实际投影或11岗名录。KNOWN/SUPPORT/client/peer/account映射为空，不只是删除一个registry文件。
- 旧 `build_snapshot.main` 的私人业务seed已移除；旧特定报文接受注册 `CASE=None`。旧逐项交办的专用obligation取材器不导出为可运行规则，通用build/validate/receipt/coverage逻辑保留；具体原问题和四图授权判断默认拒绝。既有历史不迁入新安装，不能因移植宣布原业务完成。
- 合成测试中的原账号/线程/来源/业务请求标识已经替换；需本机私人验收原件或真实岗位表的测试没有装成可复用fixtures。未将它们标作跳过后假称生产验收。
- 网页样式/组件来自原监控的他山组件实现。字体和背景位图未复制，移植采用系统字体/纯色后备；不含真实public目录、快照、node_modules或dist。构建产物不提交。
- Python/Node离线回归、实际MCP工具发现与合成HTTP检查不等于跨host认证、真微信收发、原生唤醒、全平台或长期运行验收。新环境仍须自己的来源/身份/官方宿主和界面验收。

贡献方式见 [CONTRIBUTING.md](../CONTRIBUTING.md)：现有Read协作者本地feature分支交patch/bundle，由维护者核后代推；没有因此授Write、放开fork或改变仓库保护/可见性。

固定维护职责可从[profile索引](../workspace-template/role-profiles/README.md)选择，已有真实岗位优先接续，不按文件数建员工。[完整合成例子](../examples/synthetic-employee/README.md)使用原七模板、workbook脚本和原网页投影。上述seed_monitor现在复制该例子到新的操作者指定目录并生成CURRENT与合成投影；不再要求演示目录只能在本包var下，仍不覆盖既有实例。输出的installation.example.json采用原version/modules/identities/paths结构，只有monitor_workspace相对路径，不含注册或账号。原监控、微信、共享Skill和实例配置未因此改变。

## 同日已发布phase2差量

主微信源已从20:09基线接上21:14实际发布的资源/图像/资产复用差量，22:06:20北京时间冻结本次静态源：14个已选入AUP模块和2个Mac wrapper逐个匹配发布后SHA，runtime621不变。逐文件哈希与新截止见SOURCE-CUTOFF.json；原基线另存其中的priorMainWeChatSnapshot。不是把晚些时候的未发布候选装成现行代码。

现行资源合同按真实磁盘、OS、解码器和官方客户端结果处理；移除旧固定文件/缓存/图像字节与尺寸门槛，10MB仅保留为上传路径偏好值。已存在asset可跨员工client复用，原上传者、assetID、文件身份不改；已验证图片复用仅排除来源元组中的client归属差异，其余原生来源、表示、哈希及冻结证明逐项核实，冲突不猜选。Mac两个薄wrapper同步这批已发布的实际可读路径和资源传输行为，继续复用本包同一SDK。

原navigation中这批通用的自有只读现场让路函数已同步，相关8项用例全为模拟。两份业务读取helper不属于本包选入范围，未复制；不据这些函数和用例宣称新安装已经具备完整自动历史取图入口。默认新发送确认、自动准确目标准备及剩余收尾覆盖仍在原维护未完项中，phase3候选未纳入；manual默认和现行真实目标/冻结内容/单次动作/unknown核账合同保持。此前普通配置helper纠正也完整保留。生产、UI、发件、权限和timer均未操作。
