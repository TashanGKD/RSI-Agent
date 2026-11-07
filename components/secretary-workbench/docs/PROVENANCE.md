# 来源与许可

- notebook/：现有共同记事本4.4源码，保留数据/HTTP/前端/测试/契约，排除原始基线、验收收据、设计稿/字体二进制与所有生产配置。
- wechat/：现有Linux原生工具与V2 operations。host_support仅从已有辅助源提取实际依赖的编辑类与文件预览/回执函数；原业务服务、群范围/私人联系人配置与其他业务逻辑未随包复制。旧部署入口以不可执行.txt参考保存，无自动安装或启用。
- clawbot/：现有通信、媒体、持久对话适配。保留Tencent/openclaw-weixin官方MIT最小协议参照及原LICENSE/来源commit清单。未捆绑从桌面二进制导出的完整协议schema镜像；实际宿主协议兼容需新实例核验。
- host/desktop：由现有桌面共享适配抽出的所需三个源文件，非整个移动端项目；ws8.22.0为外部MIT依赖，只带lockfile，不带node_modules。
- skills/：已审的自有秘书/微信/审计/录制归档方法。个人画像、历史案例、运行/验证收据和旧运维镜像已排除或改成合成范例。notebook-secretary的个人定时定义不进入通用版。
- 外部lark-cli/飞书Skill、腾讯会议MCP连接器、Mac移植采集器/foundation、模型/字体/OCR资源、官方客户端均单独安装/授权或另交；没有默认其许可可随整包再分发。Windows发行包未复制。

本仓没有为自有部分新增统一开源授权，见NOTICE.md；第三方继续遵守licenses/原许可与上游版本。内部来源逐文件哈希在docs/SOURCE-MANIFEST.json，仅列逻辑源位置及变换，不含私人绝对路径、凭据或运行资料。测试与真实新环境验收分开。


2026-11-06更新来源见SOURCE-MANIFEST.json。AUP原生/operations从原维护发布manifest与静态已加载代码逐文件核SHA后冻结，没有从旧打包副本覆盖生产。共享digital-employee30文件逐份对应其原发布manifest，再做路径、身份和历史安装证据脱敏；其空白岗位模板不包含任何真实岗位资料。新AUP协作适配仅代码，私有认证、历史投影和Mac文件网关另配。原单专用差异CASE去实例化为None，真实接受记录不提供。第三方原许可未改，没有追加自有部分的统一开源许可。
