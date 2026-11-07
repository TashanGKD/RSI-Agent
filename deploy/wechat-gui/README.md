# 合睿微信桌面的持久化部署候选

当前 `wechat-gui-x/desktop/web` 来自 `/run/systemd/transient`，网关 socket
定义也在 `/run`。这些定义不能跨主机启动保留。仅把现有命令复制到 `/etc`
仍缺少 `/run/wechat-gui` 和 Xauthority 的启动初始化。

本目录提供六个 systemd 定义、普通微信启动脚本和私有运行目录初始化工具。
假设是：在空运行目录中先创建授权，再等待真实 X/VNC 就绪，才能启动依赖的
桌面和网页通道。隔离测试要求有效授权能访问 X、无授权不能访问、VNC Unix
socket 返回握手，且原有 socket 存在时拒绝覆盖授权；任一失败都会否定该候选。

## 生成、核对

在 Linux 的候选源码目录执行。把 `REVIEWED_SHA` 替换为实际已审查版本，目标
目录必须不存在；`--release` 应指向稍后保留的完整只读版本，不依赖可变 current。
实测 `/var/tmp` 中的包只用于隔离校验；生产切换前须指向持久版本重新生成，不能
直接安装该测试包。

```sh
release=/opt/rsi-agent/releases/REVIEWED_SHA
bundle=/var/tmp/rsi-agent-services-REVIEWED_SHA
python3 -B -m rsi_agent services stage --release "$release" --output "$bundle"
SYSTEMD_UNIT_PATH="$bundle:" systemd-analyze verify --man=no \
  "$bundle"/*.service "$bundle"/*.socket "$bundle"/*.target
```

`plan.json` 记录实际文件 SHA-256、校验命令和 `activated: false`。
生成器只写新目录，不调用 systemctl、不读取账号配置、不安装服务。
systemd 校验会同时加载系统依赖；已有主机单元的诊断须与本候选分开判断。

依赖为 systemd、Python 3、Xtigervnc、xauth、xdpyinfo、dbus-run-session、openbox、
官方 `/usr/bin/wechat`、websockify、noVNC 和 socat。当前合睿已有这些组件。
CI 的隔离 bootstrap 不安装或启动微信，只安装 X/VNC/定义校验所需工具。

## 运行边界

- X 服务用 `RuntimeDirectory` 建立专用用户所有的 0700 目录，再以该用户生成
  0600 的 Xauthority。cookie 通过 xauth 的标准输入传入，不放在命令参数中。
- 桌面通过版本内 `session.sh` 普通启动 openbox 和官方微信；不使用调试器。
- RFB 继续只开放 0600 Unix socket，关闭 RFB TCP 与 X11 TCP。noVNC 在私有
  网络命名空间内监听回环，网关 relay 加入同一命名空间。沿用当前 Caddy
  私有 volume socket 与登录网关；生成器不改网关或登录策略。
- target 提供未来的开机入口。现阶段未安装、enable 或 start；定义校验和
  隔离 X/VNC 启动通过不等于主机启动验收或微信自动恢复。

## 独立迁移与回滚演练

在已有上述依赖、`wechat-gui` 用户及 systemd PID 1 的 Linux 主机，以 root 执行：

```sh
python3 -B scripts/rehearse_service_migration.py --execute
```

省略 `--execute` 只显示帮助。脚本从实际模板生成随机前缀的独立 unit，使用独立
显示号、运行目录和 Unix socket；桌面进程用 `sleep` 替身，不启动微信。它临时
建立 `/run` 和 `/etc/systemd/system` 定义，依次验证 transient、persistent、
rollback 三阶段，再停止并清理本次对象，不执行 enable。

每阶段都经私有 gateway→网络命名空间→noVNC→VNC 验证 HTTP 200、WebSocket
101 和 RFB 握手，核对私有权限和真实 FragmentPath。实机三阶段及清理已通过，
生产三个服务 PID 未变；证据见
[迁移演练](../../harness/evidence/2026-11-08-horyzon-service-migration.json)。

首次演练发现：`systemctl stop target` 返回时，子服务的停止和 RuntimeDirectory
清理仍可能进行中。修正后显式请求停止全部本次加载的 unit，再检查目录；不能在
只等待 target 后立即删除授权或启动替换服务。

## 生产切换的剩余边界

生产切换会中断 X、微信和网页桌面，应在另行确认的维护窗口执行。此前一次
普通微信重启授权已使用，不能据此周期性重启或再发消息。

维护窗口内的步骤与检查点如下；这些生产步骤尚未执行：

1. 固定已审查且 CI 通过的持久 release，重新生成生产路径的包。将当前三个
   transient 定义、两个 `/run` 网关定义、普通 session 脚本及运行授权/绑定的
   路径与权限备份到 root 私有目录，记录活动版本和进程。
2. 安装候选定义后，显式停止此次切换的全部旧服务、网关 socket 及其连接实例；
   等待全部请求完成，确认旧 transient 文件已由 manager 卸载。保存旧运行目录
   后从空目录启动候选 target，确认 FragmentPath 来自 `/etc`。
3. 验证既有登录网页、普通微信登录、无调试器及窗口/私有绑定。独立演练中的
   `sleep` 替身没有验收微信重启、缓存登录或布局恢复。
4. 回滚时同样等待全部新 unit 停止，恢复原网关定义及私有运行资料，再按备份的
   ExecStart、环境和权限用 systemd-run 重建三个原 transient 服务；不能把备份
   直接写回 manager 管理的 `/run/systemd/transient`。回滚后的微信验收仍需实机。

`/run/systemd/transient` 的定义优先于 `/etc/systemd/system`；仅复制文件再
daemon-reload 不能证明已切换，演练已复现这个优先级。不要手动改写正在运行的
transient 文件。
加载优先级依据 [systemd v255 的单元加载规则](https://github.com/systemd/systemd/blob/v255/man/systemd.unit.xml)，
私有目录生命周期依据 [RuntimeDirectory 约定](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml)。

未来实机验收至少包括：各单元 FragmentPath 来自 `/etc`，启用 target，普通
启动、现有网页入口、无调试器、布局/私有绑定恢复，以及失败后恢复旧定义。
主机重启后的可用性需要实际维护窗口验证；本候选没有执行这些操作。
