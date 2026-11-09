# 完整合成员工例子：活动资料协作者

本目录全部为synthetic教学资料，不是现有员工、业务记录、真实消息或原生回执。没有账号/peer/真实thread/registry/调度。阅读或复制它不创建员工，不获得任何渠道权限。一个活动资料协作者说明自己的责任及可选维护分工，不要求同时创建五个固定员工。

## 按现有格式接续

1. [AGENTS](AGENTS.md)是短入口；[ROLE](ROLE.md)交代服务对象、来源、协作者、依赖、交付去向及职责边界；[STATE](STATE.json)只留空渠道/检查点/真实回执数组与明确合成标识。
2. [CURRENT](CURRENT.md)由原workbook脚本生成。三份笔记分别示范[待推进](workbook/W001-materials.md)、[等反馈/unknown原单](workbook/W002-question.md)、[只完成本地合成结果](workbook/W003-local-plan.md)，都采用原八字段，不把三种状态挤成一个总“已完成”。
3. [来源](sources/request.md)和[后续补充](sources/update.md)是虚构内容。准备稿、入队示意、真正交付的区别在[阶段说明](sources/delivery-stages.md)；本例没有真实native accepted证明。
4. [JOURNAL](JOURNAL.md)记合成岗位重要变化，逐件过程仍在笔记；[经验索引](experience/index.md)和[案例](experience/one-case.md)明确只做教学模拟，未证真实迁移。

这套文件对应共享七模板，不导入另一种工作本格式。固定职责参考[profile索引](../../workspace-template/role-profiles/README.md)。业务作者负责最终材料与回应，机械执行按需要协作，不新增AI审批；监控维护不改本岗笔记，共同记事本维护不替本岗完成业务。

## 离线查看

在仓库根运行，输出必须是尚不存在的新目录；也可用操作系统临时目录下的普通可写位置，无须放在指定生产路径：

```sh
python3 examples/seed_monitor.py
python3 examples/seed_monitor.py --output /your/new/demo
# 上一句只预览，不连接、不写入。
python3 examples/seed_monitor.py --execute --output /your/new/demo
python3 skills/digital-employee/scripts/workbook.py check --root /your/new/demo/employee
```

显式执行只复制本目录合成文件、刷新/核对生成CURRENT，并用现有monitor发布只读投影到输出live目录。失败会清除本次新建的输出，不碰既有目录或旁边文件；存在的实例目录不会被覆盖。通过可读的相对路径、~或父目录别名选择输出均可；不会因为复制例子去改生产配置。示例中指向本包的方法链接在复制时调整为当前包位置，内部来源链接仍相对。

输出中的`installation.example.json`使用原schema，仅以`paths.monitor_workspace="."`指向本次合成输出，没有账号、映射或注册。按[既有只读展示说明](../../docs/CURRENT-COMPONENTS.md)在monitor/web构建网页，再回仓库根运行：

```sh
SECRETARY_INSTALLATION_CONFIG=/your/new/demo/installation.example.json python3 monitor/backend/serve.py --execute --port 18974
```

只是本地演示，不访问真实employees工作台records。页面初始关系图、岗位资料及工作列表均来自这套合成来源。页面的“重载”只重取本地快照，没有员工控制或发送动作；“工作”页默认是收件视图，切“工作本记录”看逐件摘要，已办好结果保留在“全部”筛选，不因默认隐藏而消失。

原模板/脚本自己的路径和结构合同保持；本例通过已有脚本生成总览，不复制业务真源或新建格式。实际实例仍需用户职责依据、自己的官方工具/宿主/来源、账号身份和持续接续分别验收。缺这些条件时部分完成，不用教学例子或网页可见替代。
