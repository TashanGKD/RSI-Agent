# RSI Agent

将秘书工作台与 Mac 微信读取工程整合为一个私有代码仓库，统一配置、诊断和运行入口。
Linux 微信是当前运行适配主干；Mac 源码保留独立平台边界与缺失依赖记录。

## 现在可以使用

```sh
python -m rsi_agent --help
python -m rsi_agent sources
python -m rsi_agent --config examples/linux.json doctor
python -m rsi_agent --config examples/linux.json audit
python -m rsi_agent mac verify
```

`doctor` 只检查条件，不读取消息、不操作微信界面。它分别报告桌面依赖、读取条件和写操作条件，不把客户端存活当作真实收发验收。

Linux 的 `xwininfo_installed` 或 `xprop_installed` 为 false 时，桌面操作尚未就绪；Ubuntu 可运行 `sudo apt-get install x11-utils` 后重新检查。这两项不影响独立的数据库读取条件。

`audit` 在 Linux 上进一步检查实际可见窗口、调试器状态和服务持久化，输出脱敏 JSON；它不读取聊天内容、不发送输入，发现退化会返回非零状态。检查通过也不等于完成收发或故障恢复验收。

启动一个新的合成记事本：

```sh
python -m rsi_agent notebook --workspace ./var/demo --demo
# http://127.0.0.1:8876/
```

已有目录不允许被 `--demo` 覆盖；后续只需省略 `--demo`。模型执行默认关闭，保留原记事本数据和权限实现。

## Linux 微信接入

先在私有配置中填写自己的准确账号、profile 和运行目录。`examples/linux.json` 适配合睿当前 `:92` 显示与 Xauthority 路径，但没有填账号或密钥，写操作默认关闭。

```sh
python -m rsi_agent --config /private/installation.json doctor
python -m rsi_agent --config /private/installation.json wechat read < request.json
python -m rsi_agent --config /private/installation.json wechat operations < operation.json
```

配置中的相对路径以配置文件所在目录为基准。工具应以拥有微信账号资料及授权文件的同一专用用户运行，不能通过改变文件所有者绕过原身份检查。

只读入口仅接受 `resolve/messages/voice/attachments/attachment`，不能夹带发送动作。
写操作继续走同一 V2 队列、稳定请求 ID、目标/草稿检查和原生回执，不新增第二个发送器；未知结果核原请求，不自动换 ID 重发。

桌面、解密密钥暂不可用或写开关关闭时，仍可查询已有的单条回执：

```json
{"op":"get","client":"original-client","request_id":"original-request-id"}
```

把这份 JSON 通过上面的 `wechat operations` 入口传入。Linux 下须由原专用用户持有已有的私有 `operations-state/config.json` 和 `queue.sqlite`；查询不会新建缺失队列或启动执行器。`unknown` 保持原状态，不自动重发；其他 operations 仍受原就绪门禁约束。

Linux 原生辅助函数已经统一使用 `WECHAT_DISPLAY` 和 `WECHAT_XAUTHORITY`，不再分别写死显示号。通过 RSI Agent 入口会从配置传入；直接使用原入口时仍保留原 `:97` 默认值，以兼容既有调用方。账号绑定、窗口布局和版本仍需在实际机器上验收。

持久化桌面服务可通过 `python -m rsi_agent services stage` 生成可审查的候选包，详见
[合睿服务部署说明](deploy/wechat-gui/README.md)。该命令只生成文件；线上服务尚未切换。

## 两个原项目如何合在一起

```text
rsi_agent/                         统一入口、安装配置与就绪诊断
components/secretary-workbench/    记事本、Linux微信、ClawBot、协作与方法
components/wechat-collector-mac/   Mac静态源码、worker、来源与依赖缺口
examples/                         不含真实账号的安装示例
scripts/check.py                  同一套适配检查与Linux合成回归
docs/                             集成边界、验证结果与后续验收
memory/                           GitHub管理的项目状态、决策、经验与下一步
harness/                          回归/运行时验证入口及Penguin接入约定
.agents/skills/                   Codex与Penguin共用的维护Skill
```

这不是给两份源码改名：Linux 的显示/授权路径接到了同一配置，所有入口有统一诊断和测试，原始业务实现继续复用。没有将 macOS 原生界面硬接到 Linux，也没有创建重复队列、影子账号或重复定时任务。

来源版本在 [SOURCES.lock.json](SOURCES.lock.json)，来源声明与许可边界见 [NOTICE.md](NOTICE.md)。先提交完整固定快照，再单独提交集成修改，可据 Git 历史核对改动。原项目完整 Git 历史保留在原仓，本仓导入的是固定源码快照。

## 验证与当前边界

```sh
python -B scripts/check.py
# 在独立 Linux 环境安装测试依赖后：
python -m pip install -r requirements-linux-tests.txt
# Ubuntu 24.04：隔离 X/VNC bootstrap 和 systemd 定义校验所需依赖
sudo apt-get install --no-install-recommends tigervnc-standalone-server xauth x11-utils websockify novnc socat
python -B scripts/check.py --linux
# 使用系统 Python 运行真实 Qt/Openbox 草稿取消回归（独立显示，不启动微信）：
sudo apt-get install --no-install-recommends openbox python3-gi gir1.2-gtk-3.0 python3-pyqt5
/usr/bin/python3 -B scripts/rehearse_composer_cleanup.py --execute
```

测试使用合成账号、模拟 driver、临时数据库和独立显示号的 X/VNC 子进程，不触碰真实微信或调用模型。Linux bootstrap 校验在 Windows 上明确跳过，不能计为通过。
Mac 的 `verify` 只验证静态源码完整性；缺失 PortableCore、OriginalDesktop、资源与 helper 的情况见 [Mac 构建缺口](components/wechat-collector-mac/docs/BUILD_GAPS.md)。

合睿实机已完成当前账号读取与文件传输助手单条文本发送验收：V2 队列只点击一次发送，原生记录状态为成功，发送者、会话和全文匹配；相同请求 ID 返回原回执。实测记录及尚未完成的普通启动、布局覆盖和长稳验收见 [合睿接入记录](docs/HORYZON-ACCEPTANCE.md)。Mac 构建缺口及服务持久化工作仍按 [集成计划](docs/INTEGRATION.md) 跟进。

## 持续改进

从 [项目记忆](memory/README.md) 恢复当前状态，每轮以一个实际可用性问题为目标，建立假设、验证候选并通过 PR 留下依据。没有合格变化就不制造提交。现有 Codex 循环负责工程迭代，[Penguin 接入约定](harness/PENGUIN.md) 负责将来固定模型下的 Agent/Skill 优化；目前尚无 Penguin 正式基线或 RSI 效果分数。
