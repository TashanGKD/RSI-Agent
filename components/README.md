# 配套组件

- [秘书工作台](secretary-workbench/) 提供 Linux 微信读写、原 V2 发送队列和本地记事本。可以用 `python -m rsi_agent notebook --workspace ./var/demo --demo` 在新目录启动合成示例。
- [Mac 微信采集器](wechat-collector-mac/) 保存 Mac 相关源码。用 `python -m rsi_agent mac verify` 检查静态源码。实际构建所需依赖见[构建缺口](wechat-collector-mac/docs/BUILD_GAPS.md)。

原始仓库与版本见[来源锁定](../SOURCES.lock.json)。分发范围见[来源与许可](../NOTICE.md)。
