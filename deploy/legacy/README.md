# deploy/legacy —— 首次部署（2026-09/10）的一次性脚本存档

这些脚本是 CTYFLY 服务器**第一次**搭建时用的分步脚本（原在本地 `_deploy/` 目录）。
它们与当前正式部署工具**不是同一套**，不要直接拿来重跑：

| 文件 | 用途 |
|---|---|
| `server_step1.sh` | 清理 BOM、校验并加载 nginx 配置 |
| `server_step2.sh` | 申请并安装 Let's Encrypt 证书 |
| `server_step3.sh` | 重试签发证书（机房对 80 端口的拦截绕行） |
| `server_step4.sh` | 数据库备份 + 服务验证（含用管理员账号走一遍登录链路） |
| `server_step5.sh` | 校验导航库、重启服务、航路规划端到端验证 |
| `recon.sh` / `recon2.sh` | 当时的 ACME / certbot 现状勘查脚本 |
| `ctyfly.service` | 早期 systemd 单元（**现役版本在 `deploy/ctyfly.service`，两者内容不同**） |
| `test.ccflysim.cn.conf` | 早期测试环境 nginx 配置（现役在 `deploy/nginx-test.ccflysim.cn.conf`） |

**为什么留档**：重装/迁移服务器时，这些脚本记录了当时的坑（BOM、80 端口拦截、证书绕行、
导航库校验）与验证顺序，比重新摸索快。

**现在该怎么部署**：看 `deploy/README.md`，日常用 `deploy/deploy.ps1`（主站，要求工作区干净）
与 `deploy/deploy-test.ps1`（测试环境）。

> 归档原因（2026-10-11，站长指出）：本地同时存在 `deploy/`（仓库内的正式工具）与
> `_deploy/`（被 .gitignore 忽略的临时目录），两者名字只差一个下划线，很容易搞混；
> 而 `_deploy/` 里其实是**有价值的历史脚本**，放在忽略目录里既容易误删又搜不到。
> 因此移入仓库归档，并删掉那个容易混淆的目录。
