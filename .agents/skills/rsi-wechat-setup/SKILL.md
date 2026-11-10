---
name: rsi-wechat-setup
description: Install or verify the RSI Agent WeChat trigger and sender on Windows 11 x64 with WSL 2. Use when pairing a personal WeChat account by QR code to a new visible conversation in the user's own Codex.
---

# 接入个人微信到 Codex

从 [RSI Agent](https://github.com/Yu-Yang-Li/RSI-Agent) 获取有权限访问的代码。用当前已审查的版本，按仓库内 [Windows 安装与配对指南](https://github.com/Yu-Yang-Li/RSI-Agent/tree/main/deploy/wechat-wsl)执行。已有工作副本时先核对来源和提交。仓库是私有的，下载使用用户已有的 GitHub 授权。

1. 从工作副本运行 `deploy/wechat-wsl/Install-WeChat.ps1 -Action Check`。通过后执行 `-Action Install`，由安装器下载并校验官方客户端和 Ubuntu 底包。首次登录由用户扫码或在手机确认，用 `-Action WaitForLogin` 核对实际窗口。
2. 为这个小号新建一个可见的 Codex 回复会话，把实际会话 ID 固定到本机接收器。将用户这次登录的原生账号与 Linux 触发器、V2 发送器绑定。发现同一账号已有在线发送器时，先保持本机只读，按指南核对交接范围。
3. 初次验收限定为本人和小号之间的一条新私聊。分别核对触发器原 ID、专用会话实际收件与完成、发送器原 V2 单次回执。仅有扫码成功或入队回执时，按实测阶段报告。

启动语：**使用 rsi-wechat-setup，帮我从 GitHub 下载并接入自己的微信小号，到扫码时告诉我。**
