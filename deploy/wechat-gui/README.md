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

## 切换与回滚仍需演练

生产切换会中断 X、微信和网页桌面，应在另行确认的维护窗口执行。此前一次
普通微信重启授权已使用，不能据此周期性重启或再发消息。

切换前需要将当前三个 transient 服务、两个 `/run` 网关定义、普通 session
脚本及其路径/权限保存到 root 私有备份，并记录当前活动版本与进程。
`/run/systemd/transient` 的定义优先于 `/etc/systemd/system`；仅复制文件再
daemon-reload 不能证明已切换。应先在独立名称和显示号下演练停止、旧定义卸载、
持久定义加载和回滚，再确定准确命令。不要手动改写正在运行的 transient 文件。
加载优先级依据 [systemd v255 的单元加载规则](https://github.com/systemd/systemd/blob/v255/man/systemd.unit.xml)，
私有目录生命周期依据 [RuntimeDirectory 约定](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml)。

未来实机验收至少包括：各单元 FragmentPath 来自 `/etc`，启用 target，普通
启动、现有网页入口、无调试器、布局/私有绑定恢复，以及失败后恢复旧定义。
主机重启后的可用性需要实际维护窗口验证；本候选没有执行这些操作。
