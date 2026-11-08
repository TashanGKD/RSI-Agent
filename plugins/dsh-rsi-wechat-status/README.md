# 星语微信运行态 · DSH 插件

这是第一块可独立安装的 DSH bundle，目前只提供 `rsi_wechat_status`。
它读取本人和已登记群的回复进程、状态新鲜度、待处理数量、部署版本，以及
原工程任务是否未收束。不会读取聊天正文，不收发消息，不启动或重试工程任务。
`idle` 是最近一次观察，不是投递验收；`recorded_state=running` 不证明工具进程仍在执行。

要求 Linux、RSI Agent 中的 `rsi_agent.dsh_status`，以及能读取相应私有状态的运维身份。
不要将这个插件装入普通群友可调用工具的会话。默认路径采用 RSI 的现有安装布局，
不复制模型密钥，不启动第二个微信消费者。

```sh
cd plugins/dsh-rsi-wechat-status
npm test
npm pack --pack-destination /tmp
dsh plugin --profile rsi-ops add /tmp/dsh-rsi-wechat-status-0.1.0.tgz
dsh --profile rsi-ops --dump-config
```

若路径不同，在该 profile 的 `cordis.patch.yml` 覆盖配置。`source` 必须包含本版
Python 读取模块；`current` 是要核对的实际发布入口，两者可在候选验证时不同。

```yaml
- id: rsi-wechat-status
  config:
    python: /usr/bin/python3
    source: /opt/rsi-agent/current
    ownerConfig: /var/lib/rsi-agent/owner-replies/config.json
    groupsConfig: /var/lib/rsi-agent/groups/config.json
    release: /var/lib/rsi-agent/release.json
    current: /opt/rsi-agent/current
```

调用：请调用 `rsi_wechat_status`，分别说明聊天观察和未收束工程工作。
工具无模型参数；路径只能由管理员配置。输出无原生消息 ID、会话名、原文或凭据。
发现 `needs_review` 时保留原请求；本插件没有“恢复”“重发”或“确认”按钮。

卸载：`dsh plugin --profile rsi-ops remove dsh-rsi-wechat-status`。
Cordis 的注册随插件卸载撤销，现有回复服务和私有状态不受安装/卸载影响。

原生加载和调用验收步骤见 [插件计划](../../harness/DSH-PLUGINS.md)。
