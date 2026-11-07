# RSI Agent

将秘书工作台与 Mac 微信读取工程整合为一个私有代码仓库，统一配置、诊断和运行入口。
Linux 微信是当前运行适配主干；Mac 源码保留独立平台边界与缺失依赖记录。

## 现在可以使用

```sh
python -m rsi_agent --help
python -m rsi_agent sources
python -m rsi_agent --config examples/linux.json doctor
python -m rsi_agent mac verify
```

`doctor` 只检查条件，不读取消息、不操作微信界面。它分别报告桌面依赖、读取条件和写操作条件，不把客户端存活当作真实收发验收。

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

Linux 原生辅助函数已经统一使用 `WECHAT_DISPLAY` 和 `WECHAT_XAUTHORITY`，不再分别写死显示号。通过 RSI Agent 入口会从配置传入；直接使用原入口时仍保留原 `:97` 默认值，以兼容既有调用方。账号绑定、窗口布局和版本仍需在实际机器上验收。

## 两个原项目如何合在一起

```text
rsi_agent/                         统一入口、安装配置与就绪诊断
components/secretary-workbench/    记事本、Linux微信、ClawBot、协作与方法
components/wechat-collector-mac/   Mac静态源码、worker、来源与依赖缺口
examples/                         不含真实账号的安装示例
scripts/check.py                  同一套适配检查与Linux合成回归
docs/                             集成边界、验证结果与后续验收
```

这不是给两份源码改名：Linux 的显示/授权路径接到了同一配置，所有入口有统一诊断和测试，原始业务实现继续复用。没有将 macOS 原生界面硬接到 Linux，也没有创建重复队列、影子账号或重复定时任务。

来源版本在 [SOURCES.lock.json](SOURCES.lock.json)，来源声明与许可边界见 [NOTICE.md](NOTICE.md)。先提交完整固定快照，再单独提交集成修改，可据 Git 历史核对改动。原项目完整 Git 历史保留在原仓，本仓导入的是固定源码快照。

## 验证与当前边界

```sh
python -B scripts/check.py
# 在独立 Linux 环境安装测试依赖后：
python -m pip install -r requirements-linux-tests.txt
python -B scripts/check.py --linux
```

测试只使用合成账号、模拟 driver 和临时数据库，不触碰真实微信或调用模型。
Mac 的 `verify` 只验证静态源码完整性；缺失 PortableCore、OriginalDesktop、资源与 helper 的情况见 [Mac 构建缺口](components/wechat-collector-mac/docs/BUILD_GAPS.md)。

本轮是源码合并与第一轮 Linux 接入打磨，尚不声称 Mac 完整应用可构建、合睿真实微信已自动收发或已通过 24–72 小时长稳。实际账号授权、界面校准、服务持久化和维护窗口恢复验收见 [集成计划](docs/INTEGRATION.md)。
