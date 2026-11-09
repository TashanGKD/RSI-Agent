# 在线层契约

基础业务API复用LOCAL-API.md，所有私人路径强制鉴权。访问层是运行基础，不新造一套事项语义。

## 访问与登录（root实现）

- GET /login：独立登录页；GET /auth.js,/auth.css匿名可用。主页面与api未登录跳login／401，API/assets/source/download均受保护。
- POST /api/auth/activate {token,password,username?}：一次性私人激活设置账号、密码并登录；账号为3至64位字母、数字或下划线。
- POST /api/auth/login {password,username?}：登录本人私有记事本。已设置账号的主人必须提交正确username，不能仅凭密码跳过账号校验；原有未设置账号的独立测试工作区保留密码登录兼容。
- POST /api/auth/logout {}：撤销当前会话。
- GET /api/auth/status：{authenticated,initialized,usernameRequired}，只返回是否需要账号，不公开账号值、私人数据或令牌。
- 浏览器使用Secure+HttpOnly+SameSite Cookie，POST检查固定公共Origin+CSRF。首次激活token在URL片段#activate=...，前端只通过POST交换，不进访问日志；提交后清掉片段。成功后跳 /#today。
- 口令至少8字符，最多256；登录／激活错误显示中文，不暴露账户细节。默认保持登录14天，可撤销。
- 设备worker用Authorization: Bearer <deviceToken>，同一私人工作区，禁止扩权；只有worker能claim/report。浏览器不能冒充设备回执。实际actor由鉴权身份确定。

## 云任务队列与Mac出站worker（agent实现）

`CloudSecretaryQueue(notebook_port,workspace)`复用submit(message_id=None,request_id=None)／get_job／list_jobs，持久queued/running/completed/failed，不在AUP调用Mac路径Codex。

- `claim(worker_id)` -> {job,leaseToken}或null；一个租约，过期可安全恢复，不重复消费已完成输入。
- `report(job_id,worker_id,lease_token,status,result=None,error=None)` -> job；验证租约与归属，result只允许可公开给本人看的摘要／对象ID／数量，不放上下文、计划和认证信息。
- HTTP（root挂载）：POST /api/worker/claim {workerId}；POST /api/worker/jobs/{id}/report {workerId,leaseToken,status,result?,error?}。
- POST /api/secretary/run对已保存的人类留言排队；来源更新另走授权入口，不自动读微信。

`HTTPNotebookPort(base_url,device_token,workspace)`（agent实现，建议modules/notebook/http_port.py）公开方法与NotebookService相同；通过HTTPS调用既有api，初始化bootstrap获取CSRF并带固定Origin；401明确报认证失效，403可重取CSRF并按同requestId重试一次；不盲重试副作用，409抛公共ConflictError。无原文／任意路径接口。

Mac worker用显式私有配置运行，出站轮询claim→本机SecretaryService(HTTPNotebookPort,本地worker工作区) prepare/run→report。message与任务仍只保存在云主库，本机worker只保存运行步骤与有限附件缓存；不能维护第二份可写任务库。复用已安装Codex，不传auth.json。cookie密码不用worker。参数无配置打印usage，不默认接正式站；loop需显式参数；配置600、日志不输出凭证／消息正文。队列离线状态真实。支持有限时间／失败恢复／原始输入幂等。

## 云端投影（agent实现）

`modules/notebook/cloud_projection.py`独立导出／导入，不改正式库。公开建议：`export_projection(notebook_port, output_dir)`生成最小JSON投影＋审核清单；`import_projection(bundle_dir, db_file, workspace)`建立空的新云库，不覆盖已有库。

保留所有303个稳定ID、实际state/kind/domain/assignee/planDate/reviewDate/condition、revision及needsReview/recommendation；保留历史身份、作者、时间和状态经过。源quote/XML/本机绝对路径/媒体访问参数/凭证不进入包。title/summary/completionCriterion等只保留必要整理文本，源引文不复制；人类批注不含源引用的可保留，疑似直接源引文改成本机保留说明；AI进展用必要操作摘要，不夹原文。原始完整历史在本机保留。sourceContacts仅定位必要名称／时间／稳定原生ID与版本等，不带path/key或认证参数；可选无认证HTTPS来源链接。

云对象evidence使用{label:'原文保留Mac',quote:'原文保留Mac，线上仅保存事项摘要。',localOnly:true}，不冒充可读原文。全部历史记录若部分仅本地，清楚标识；保留原事件ID／作者／时间／状态变化。审计清单只列ID、类型、计数、理由和校验值，不回显被排除的原文。

注意NotebookService：local_objects保存canonical payload（含基线revision），detail仅真正legacy表记录才调用旧detail；纯云投影不能因legacy=true去查不存在的tasks。可新增readonlyderived importedLegacyPlanning以保留旧待办兼容，不编造计划日。迁移自有表写入只在notebook模块，不让部署脚本绕过API改业务状态。


4.3工具能力的实际运行合同见[NOTEBOOK-TOOLS](NOTEBOOK-TOOLS.md)；来源版本、附件、收据与检查点见[SOURCE-TOOLS](SOURCE-TOOLS.md)。秘书和定时能力没有随工具升级开启。
