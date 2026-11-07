# 安装和配置

## 本地演示

建议Python 3.10+。在仓库根执行README中的seed_demo与local_server。它们只使用显式新工作区与合成资料。输入/附件/状态记录不带原微信或私人会议数据。UI字体文件未捆绑，使用系统回退字体。CLI默认禁用模型，只有显式 `--enable-codex-exec` 才允许自己已配置/授权的本机模型入口。

## 可选依赖

Node.js 22+；`npm ci --ignore-scripts`只安装锁定ws。Linux WeChat还需pycryptodome、Pillow、GTK3/PyGObject、X11/libXtst、tesseract及合适语言数据，使用自己的平台包管理器安装；requirements-aup.txt保留旧可选依赖说明，不代表本包需要对原加密库建立实时SQLCipher连接。不要把已安装库或node_modules复制进仓库。

Mac reader依赖另交采集器中的解码foundation（crypto/security/library）与已有模型/转码组件，本包不提供该工程和模型；指定WECHAT_MAC_FOUNDATION，否则不能声称Mac读取已可用。飞书CLI和腾讯会议MCP分别按各自官方/获授权入口安装，明确账号/组织/范围。SILK/ASR在bridge.media/voice_text中仍有宿主资源适配，缺资源时保留读取缺口。

## 私有运行目录

按.env.example设置自己的运行路径；目录700/文件600，不在仓库内放真实账户/密钥/数据库。微信工具的db-keys.json/capture-secret.hex、native-ui.json/tool-targets.json、Xauthority与官方账号资料必须来自操作者自己已有的合法授权，本次交付没有准备或提取它们。首次账号/版本接入及UI校准是新环境验收，不是直接复制别人的运维配置。

V2使用独立root/config；空白示意见examples/wechat-operations.example.json。account与clients是当前cli.load_config要求的两个顶层字段。Policy v2的clients是归属元数据，空对象不再表示逐目标权限拒绝；它不能充当安全租户或宿主沙箱。先取得自己实例的登录与工具授权，核真实peer、布局及所需原生条件；本包没有这些实例资料，也没有自动配置可用账号。

## ClawBot/桌面宿主

通信工作区中的account.json、native-context.json等均由操作者自己的官方绑定生成，本仓无这些文件。两侧SECRETARY_THREAD_ID相同；未配置时只存在不可用的合成测试路由，不能接真实业务。只连接自己受控、所有者与权限可核的socket，不启动第二个秘书模型。Mac桌面共享adapter基于特定协议版本，Windows/Linux同等接入未验收。

协作回报主路由使用独立 `SECRETARY_MAIN_THREAD_ID`，不要把它与ClawBot的 `SECRETARY_THREAD_ID` 混为一个开关。两者由自己的实例明确配置，默认只含不可用于真实服务的合成标识。

## 协作/运行

host/tools下薄客户端无参数只帮助，真实assign/report必须显式execute和私有brief；旧固定宿主目录/允许工作根需要在新实例的明确配置中核对。生产systemd/LaunchAgent/权限/目标绑定未捆绑；maintenance-reference只是经过脱敏的旧代码文本，不作为可执行安装器。没有后台或timer自动开启步骤。

可选AUP协作源码在 `host/aup-sender/`。配置 `SECRETARY_SENDER_WORKSPACE`、`SECRETARY_SENDER_THREAD_ID`、`SECRETARY_CODEX_HOME`、`SECRETARY_CODEX_BIN` 指向自己的已有工作区、持续对话和受支持的官方宿主。还须有该实例自身的原生历史投影与安全socket；本包不提供认证/历史、不创建第二个模型服务。Mac回报若要用独立文件网关，需另配 `SECRETARY_MAC_GATEWAY_TOOLS`。现行MCP源码已补入host/aup-sender/sender_work_tools.py，与原SDK和队列复用；独立文件网关薄client已选入，Mac端授权服务、SSH配置和实例资料需另配。

`WECHAT_TOOL_ROOT`是自己的私有运行目录，`WECHAT_NATIVE_CODE`指本仓wechat代码，`WECHAT_HOST_SUPPORT_CODE`指其host_support辅助代码。桌面维护另可设置 `WECHAT_DESKTOP_BIND`（缺省回环）、`WECHAT_DESKTOP_REMOTE_CODE`、`WECHAT_SSH_HOST`。普通SDK发送无需先开启桌面。各客户端必须使用同一实例的原队列、guard和回执，不复制旧目标绑定或改unknown状态。

共享Skill可从本仓 `skills/digital-employee/SKILL.md` 直接读，或由自己的宿主按正常Skill安装方式配置。它引用的统一事件系统、小时调度和监控不是随本仓自动安装的服务；新环境先确定实际负责人和接口，不将合成ID、示例渠道或旧验证叙述当已生效实例。

统一接续与监控的通用源码已在本轮同仓补齐，但没有安装任何后台或调度。按 [CURRENT-COMPONENTS.md](CURRENT-COMPONENTS.md) 配置自己的私有安装文件；空模板不能接真实岗位。先用合成网页和离线测试核包，再分别办理自己的来源、宿主和业务验收。
