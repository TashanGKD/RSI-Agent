---
name: rsi-wechat-setup
description: Guide installation, pairing, verification and upgrades of the RSI Agent WeChat trigger and sender on Windows 11 x64 with WSL 2, or locate, enable and extend features using the full public repository.
---

# 接入个人微信到 Codex

从公开的 [RSI Agent](https://github.com/TashanGKD/RSI-Agent) 下载完整仓库，读取根目录 README、AGENTS.md 和 [Windows 安装与配对指南](https://github.com/TashanGKD/RSI-Agent/tree/main/deploy/wechat-wsl)。下载不需要 GitHub 账号：可用 `git clone https://github.com/TashanGKD/RSI-Agent.git` 或仓库页面的 Code → Download ZIP。已有工作副本时先核对来源、提交和未提交改动。选择已通过检查的固定版本，在下载的仓库根目录执行命令。

当前安装器负责准备 Linux、下载校验客户端和检查登录。账号授权、SSH 通道、触发器配置与接收器配对仍需按本机环境适配；不能把扫码成功报告成全链路完成。遇到缺失实现时定位仓库中的具体模块，报告该阶段的实际结果。

1. 从工作副本运行 `deploy/wechat-wsl/Install-WeChat.ps1 -Action Check`。通过后执行 `-Action Install`，由安装器下载并校验官方客户端和 Ubuntu 底包。首次登录由用户扫码或在手机确认，用 `-Action WaitForLogin` 核对实际窗口。
2. 按指南生成本实例的私有配置、令牌与状态目录。为这个小号新建一个可见的 Codex 回复会话，将实际会话 ID 固定到接收器，并把本实例配置的绝对路径和仓库内 `harness/DESKTOP-WECHAT.md` 交给该会话。将用户这次登录的原生账号与 Linux 触发器、V2 发送器绑定。不要沿用维护者的账号、路径或会话 ID。发现同一账号已有在线发送器时，先保持本机只读，按指南核对交接范围。
3. 初次验收限定为本人和小号之间的一条新私聊。分别核对触发器原 ID、专用会话实际收件与完成、发送器原 V2 单次回执。仅有扫码成功或入队回执时，按实测阶段报告。

启动语：**使用 rsi-wechat-setup，帮我从 GitHub 下载并接入自己的微信小号，到扫码时告诉我。**

## 查找或添加功能

先按关键词查完整仓库的源码、测试、[Issue](https://github.com/TashanGKD/RSI-Agent/issues)和[PR](https://github.com/TashanGKD/RSI-Agent/pulls)。接入范围和原始消息在 `trigger/`，交给 Codex 的请求和完成回执在 `receiver/`，微信收件人校验和实际发送在 `components/wechat-linux/operations/`，依赖与服务模板在 `deploy/`。`archive/` 是历史资料，不能按目录存在推断为可安装功能。用当前源码、测试和交付回执判断功能状态。

- 已实现：按对应模块说明配置启用，保留当前配置，验证这一功能的实际收发路径。
- 缺依赖：核对项目声明的版本、安装来源和适用平台，只安装所需组件；插件装好不等于微信能力接通。
- 尚未实现：用户明确要求开发时，基于当前主分支或已有对应 PR 做最小改动并验证受影响路径。没有仓库写权限时用自己的 fork 提交 PR；运行中的账号资料不进入代码或 PR。

## 升级与维护

按安装指南的升级步骤核对实际版本、未完成请求及私有状态，选择检查通过的提交。保留旧源码与配置，使用独立工作副本验证，按原 ID 收束在途任务后再升级对应进程。仅更新 skill 或下载代码时，不报告发送器已升级。不覆盖私有队列或用户未提交的修改，不为升级重放旧消息。最终报告安装、登录、配对、Codex 实际接收和微信回执分别到哪一步。
