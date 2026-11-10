---
name: rsi-wechat-setup
description: Install or verify the RSI Agent WeChat trigger and sender on Windows 11 x64 with WSL 2, pair a WeChat account to a dedicated Codex conversation, or locate and extend a feature in the full RSI Agent repository.
---

# 接入个人微信到 Codex

从 [RSI Agent](https://github.com/TashanGKD/RSI-Agent) 获取有权限访问的代码。用当前已审查的版本，按仓库内 [Windows 安装与配对指南](https://github.com/TashanGKD/RSI-Agent/tree/main/deploy/wechat-wsl)执行。已有工作副本时先核对来源和提交。仓库是私有的，下载使用用户已有的 GitHub 授权。

1. 从工作副本运行 `deploy/wechat-wsl/Install-WeChat.ps1 -Action Check`。通过后执行 `-Action Install`，由安装器下载并校验官方客户端和 Ubuntu 底包。首次登录由用户扫码或在手机确认，用 `-Action WaitForLogin` 核对实际窗口。
2. 为这个小号新建一个可见的 Codex 回复会话，把实际会话 ID 固定到本机接收器。将用户这次登录的原生账号与 Linux 触发器、V2 发送器绑定。发现同一账号已有在线发送器时，先保持本机只读，按指南核对交接范围。
3. 初次验收限定为本人和小号之间的一条新私聊。分别核对触发器原 ID、专用会话实际收件与完成、发送器原 V2 单次回执。仅有扫码成功或入队回执时，按实测阶段报告。

启动语：**使用 rsi-wechat-setup，帮我从 GitHub 下载并接入自己的微信小号，到扫码时告诉我。**

## 查找或添加功能

使用完整仓库。先读根目录 README 和 AGENTS.md，再按关键词查源码、测试、[Issue](https://github.com/TashanGKD/RSI-Agent/issues)和[PR](https://github.com/TashanGKD/RSI-Agent/pulls)。接入范围和原始消息在 `trigger/`，交给 Codex 的请求和完成回执在 `receiver/`，微信收件人校验和实际发送在 `components/wechat-linux/operations/`。用当前源码、测试和交付回执判断功能是否已上线。

用户明确要求实现时，基于当前主分支或已有对应 PR 做最小改动，验证受影响的触发、接收或回传路径，再按仓库维护流程交付 PR。
