# 以只读权限提交协作分支

本说明适用于获准读取本私有仓库、但没有主干写入或合并权限的协作者。现有维护者的权限和发布分工保持。

当前私有仓库未开放fork。只读协作者可以在本地创建开发分支、提交改动，并把分支补丁或bundle通过本仓私有Issue交给现有维护者。维护者核对后代推到本仓贡献分支，再决定是否合并主干。这是当前可用的贡献方式，不代表协作者已获直接推送远端分支的Write权限。

## 提交方式

克隆仓库并记录基准提交，在自己的本地分支修改：

```sh
git fetch origin
git switch -c feature/my-change origin/main
# 修改需要的文件并完成本地检查
git add <本次修改文件>
git commit -m "fix: describe the change"
git rev-parse origin/main
git format-patch --binary --stdout origin/main..HEAD > changes.patch
```

将基准SHA、改动说明、实际检查结果及changes.patch放进本仓私有Issue；补丁较大时可打成ZIP附件。也可交分支bundle：

```sh
git bundle create changes.bundle origin/main..HEAD
git bundle verify changes.bundle
```

请勿在补丁、附件或Issue里放入运行凭据、真实微信/邮件记录、媒体、个人工作本、数据库或生产配置。本仓仅交付脱敏静态代码与方法；未公开的上游/第三方文件不因能本地读取就成为可提交材料。

## 维护者接收

现有维护者先核基准、范围和内容，再在独立贡献分支应用补丁或导入bundle，运行相应检查后推送。合并主干仍由现有维护者负责；不要把分支改动直接覆盖当前主干或重写历史。

如将来需要协作者直接推送远端分支，必须先在GitHub支持的套餐/规则中落实其不能更新、合并或绕过默认主干，再单独调整该账号角色。不能仅授予Write就声称主干受限，也不为此擅自公开仓库或改变整个组织的分叉策略。
