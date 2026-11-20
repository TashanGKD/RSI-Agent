---
name: rsi-wechat-setup
description: Guide installation, pairing, verification and upgrades of the RSI Agent WeChat trigger and sender on Windows 11 x64 with WSL 2, or locate, enable and extend features using the full public repository.
---

# 接入个人微信到 Codex

从公开的 [RSI Agent](https://github.com/TashanGKD/RSI-Agent) 下载完整仓库，读取根目录 README、AGENTS.md 和 [Windows 安装与配对指南](https://github.com/TashanGKD/RSI-Agent/tree/main/deploy/wechat-wsl)。下载不需要 GitHub 账号：可用 `git clone https://github.com/TashanGKD/RSI-Agent.git` 或仓库页面的 Code → Download ZIP。已有工作副本时先核对来源、提交和未提交改动。选择已通过检查的固定版本，在下载的仓库根目录执行命令。

当前安装器负责准备 Linux、下载校验客户端和检查登录。账号授权、SSH 通道、触发器配置与接收器配对仍需按本机环境适配；不能把扫码成功报告成全链路完成。遇到缺失实现时定位仓库中的具体模块，报告该阶段的实际结果。

1. 从工作副本运行 `deploy/wechat-wsl/Install-WeChat.ps1 -Action Check`。通过后执行 `-Action Install -PrepareOnly`，下载校验官方客户端和 Ubuntu 底包，但先不开微信。补齐完整触发器依赖和首次授权所需的 GDB，在账号用户的私有配置及 runtime 中运行 `setup prepare-capture`。该命令只准备经过固定版本校验的自有子进程授权脚本，不能当作账号已授权。
2. 按指南用 `setup pair` 为新实例生成同一令牌的接收器和 Linux 后端配置，私有目录必须是新目录；已有安装沿用原配置，不重建令牌或队列。为小号建立可见回复会话，传入实际会话 ID，并把配置绝对路径和 `harness/DESKTOP-WECHAT.md` 交给该会话。按计划的属主部署 Linux 文件，配置 SSH 回环，用 `setup check` 分阶段检查；加 `--probe` 才连接健康接口。新生成配置不启用发送、工程或 owner 权限。
3. 在实际授权的自有子进程启动流程中由用户扫码或手机确认，核原生账号、数据库认证、普通进程状态和界面绑定，再准入接收范围。已有登录需要单独的客户端重启授权。确认同一原生账号没有另一套在线发送器后，用一条新私聊分别核触发器原 ID、Codex 收件与完成、原 V2 单次回执。`setup check` 的 configured、扫码成功和入队回执都不能当作真实送达。

启动语：**使用 rsi-wechat-setup，帮我从 GitHub 下载并接入自己的微信小号，到扫码时告诉我。**

## 查找或添加功能

先按关键词查完整仓库的源码、测试、[Issue](https://github.com/TashanGKD/RSI-Agent/issues)和[PR](https://github.com/TashanGKD/RSI-Agent/pulls)。接入范围和原始消息在 `trigger/`，交给 Codex 的请求和完成回执在 `receiver/`，微信收件人校验和实际发送在 `components/wechat-linux/operations/`，依赖与服务模板在 `deploy/`。`archive/` 是历史资料，不能按目录存在推断为可安装功能。用当前源码、测试和交付回执判断功能状态。

- 已实现：按对应模块说明配置启用，保留当前配置，验证这一功能的实际收发路径。
- 缺依赖：核对项目声明的版本、安装来源和适用平台，只安装所需组件；插件装好不等于微信能力接通。
- 尚未实现：用户明确要求开发时，基于当前主分支或已有对应 PR 做最小改动并验证受影响路径。没有仓库写权限时用自己的 fork 提交 PR；运行中的账号资料不进入代码或 PR。

## 升级与维护

全本地常驻优先复用安装指南的“本地常驻与登录启动”：用 `services stage --profile wsl`
生成 Xephyr 服务候选，沿用同一个接收器和私有队列，用 `Register-Startup.ps1` 检查、
注册当前用户登录任务。生成和注册不代表激活；在单独授权的维护窗口内切换旧显示与服务，
按 `audit --profile wsl` 核运行条件。分别记录任务注册、Linux 服务启动、重启恢复和原生收发，
不要直接把服务器 noVNC 模板当作本机 WSLg 配置，也不要为启动恢复另建发送器或请求 ID。

按安装指南的升级步骤核对实际版本、未完成请求及私有状态，选择检查通过的提交。保留旧源码与配置，使用独立工作副本验证，按原 ID 收束在途任务后再升级对应进程。仅更新 skill 或下载代码时，不报告发送器已升级。不覆盖私有队列或用户未提交的修改，不为升级重放旧消息。最终报告安装、登录、配对、Codex 实际接收和微信回执分别到哪一步。
