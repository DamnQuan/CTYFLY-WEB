# CTY 飞控 · 生产部署与运维手册

内测环境：**https://test.ccflysim.cn**（服务器 `YOUR_SERVER_IP`，Ubuntu 22.04）

> ⚠️ 访问务必带 **https://**。机房的备案检查层会间歇性在 **80 端口**注入拦截页，
> 详见文末「待解决事项」。HTTPS 不受该类注入影响。

## 一、架构与路径

| 项目 | 位置 |
|---|---|
| 后端代码 | `/opt/ctyfly/backend`（Python 3.10 + venv） |
| 后端端口 | `127.0.0.1:3015`（仅本机，由 Nginx 反代） |
| 前端产物 | `/opt/ctyfly/frontend/dist`（Nginx 直接托管） |
| 数据库 | `/opt/ctyfly/backend/data/ctyfly.db`（SQLite） |
| 上传文件 | `/opt/ctyfly/backend/data/uploads` |
| 航路规划 sidecar | `/opt/ctyfly/backend/navdata-planner`（Node v24，端口 4173，由后端自动拉起） |
| systemd 服务 | `ctyfly.service` |
| Nginx 站点 | `/etc/nginx/sites-available/test.ccflysim.cn.conf` |
| 备份 | `/opt/ctyfly/backups`（每日 04:00，保留 14 天） |
| 日志 | `journalctl -u ctyfly`、`/var/log/nginx/ctyfly-test.*.log` |

**与旧官网互不影响**：旧站走 `server_name ccflysim.cn / www.ccflysim.cn`（占用 80/443/8443），
本站走 `server_name test.ccflysim.cn`，各自的 server 块独立；旧站后端占用的
`127.0.0.1:8000`、`3010` 等端口均未改动。

## 二、常用运维命令

```bash
# 服务状态 / 启停 / 日志
systemctl status ctyfly
systemctl restart ctyfly
journalctl -u ctyfly -n 50 --no-pager
journalctl -u ctyfly -f

# Nginx 配置改动后
nginx -t && systemctl reload nginx

# 数据库备份（手动）
/opt/ctyfly/backup.sh
ls -lh /opt/ctyfly/backups/

# 管理员账号密码（首次登录后建议在「个人中心」修改）
grep ADMIN_PASSWORD /opt/ctyfly/backend/.env
```

## 三、如何发布更新

### 推荐：用一键部署脚本（`deploy\deploy.ps1`）

在**仓库根目录**（或任意位置）执行：

```powershell
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1          # 前端 + 后端 全量部署
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -Frontend # 只发前端
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -Backend  # 只发后端
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 -SkipBuild # 前端不重新构建，直接上传现有 dist
```

脚本做了这些事：

1. SSH 连通性预检（连不上直接中止）；打印工作区未提交改动，**有未提交改动默认中止**（加 `-AllowDirty` 放行；仓库根那份永不入库的未跟踪 `*.pdf` 调查报告已自动豁免，不算脏）
2. 前端：`npm run build` → 校验压缩包结构 → 上传 → 服务器先解包到 `dist.new-<时间戳>`，成功后旧 `dist` 改名 `dist-bak-<时间戳>`、新目录原子改名为 `dist`（**旧目录始终保留一份备份，自动只保留最近 3 份**）
3. 后端：打包 `backend\app` → 上传 → 服务器先解包到 `app.new-<时间戳>`，成功后旧 `app` 改名 `app-bak-<时间戳>`、新目录原子改名为 `app` → 清理 `__pycache__` → `systemctl restart ctyfly`
4. 健康检查：服务器上断言 `/api/health` 返回 `"ok":true`（否则报错退出并打印后端回滚命令）、首页 HTTPS 状态码为 200（否则报错退出并打印前端回滚命令）；`/privacy`、`/login`、`/register` **只打印状态码供人工确认，不做断言、不影响退出码**

任何服务器端步骤失败都会立即中止：旧版本原封不动，服务不重启。

**出问题怎么回滚**：脚本最后会打印本次备份目录名，照抄执行即可，例如：

```bash
# 前端：回滚到本次部署前的 dist
ssh root@YOUR_SERVER_IP "cd /opt/ctyfly/frontend && rm -rf dist && mv dist-bak-20260924-190556 dist"
# 后端：回滚到本次部署前的 app（app-bak-<时间戳> 是 deploy.ps1 每次部署自动保留的旧代码）
ssh root@YOUR_SERVER_IP "cd /opt/ctyfly/backend && rm -rf app && mv app-bak-20260924-190556 app && systemctl restart ctyfly"
```

> 脚本的两个「安全阀」是踩坑后加的，别删：
> - 打包必须用 `-C frontend\dist .`（只打包内容）。带上 `dist` 这层目录会让服务器解出
>   `dist/dist/index.html`，首页直接 **403**。
> - 健康检查必须校验首页状态码，否则坏的部署会被误报成「部署完成」。

### 手动方式（脚本不可用时）

**只改前端**：

```bash
# 本地：构建后打包 dist 的「内容」
cd frontend && npm run build
tar -czf dist.tar.gz -C dist .
scp dist.tar.gz root@YOUR_SERVER_IP:/tmp/
# 服务器：先解包到新目录，成功后再整体换名（解包失败时旧 dist 原封不动）
ssh root@YOUR_SERVER_IP "cd /opt/ctyfly/frontend && rm -rf dist.new-tmp && mkdir dist.new-tmp && \
  tar -xzf /tmp/dist.tar.gz -C dist.new-tmp && rm /tmp/dist.tar.gz && \
  rm -rf dist-bak-tmp && mv dist dist-bak-tmp && mv dist.new-tmp dist"
# 无需重启后端；index.html 为 no-cache，访客刷新即得新版
```

**改后端代码**：

```bash
ssh root@YOUR_SERVER_IP "systemctl restart ctyfly && sleep 3 && systemctl is-active ctyfly"
```
（或直接跑 `deploy.ps1 -Backend`，会自动上传并重启）

**改了依赖**（`requirements.txt`）：

```bash
ssh root@YOUR_SERVER_IP "cd /opt/ctyfly/backend && ./venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt && systemctl restart ctyfly"
```

## 四、HTTPS 证书

证书已改为 **DNS-01 验证 + 阿里云 DNS hook** 签发与续期，当前共有**两张证书**
（主站 `ccflysim.cn`、内测站 `test.ccflysim.cn`），位于 `/etc/letsencrypt/live/` 各自目录下。
续期时 hook 会调用阿里云 DNS API 自动添加/删除 `_acme-challenge` TXT 记录完成校验，
**完全不依赖 80 端口**，机房对 80 端口的间歇性拦截不再影响证书签发与续期。

阿里云 API 凭据只保存在服务器上（未入库）。续期由 certbot 自带的 systemd timer
在到期前 30 天自动完成。

```bash
certbot certificates                       # 查看两张证书的有效期
certbot renew --dry-run                    # 演练续期（会真实调用阿里云 hook 添加/清理 TXT 记录）
```

一般无需手动重签：`certbot renew` 会自动带上原配置的 DNS-01 hook。若确需重签，
按原有证书配置用同样的 DNS-01 方式执行即可。

## 五、备份与恢复

每日 04:00 自动备份数据库与上传目录到 `/opt/ctyfly/backups`（保留 14 天），
数据库使用 `sqlite3 .backup` 做一致性快照（避免 WAL 模式下直接复制导致数据不一致）。

恢复步骤：

```bash
systemctl stop ctyfly
cp /opt/ctyfly/backups/ctyfly-YYYYMMDD-HHMM.db /opt/ctyfly/backend/data/ctyfly.db
rm -f /opt/ctyfly/backend/data/ctyfly.db-wal /opt/ctyfly/backend/data/ctyfly.db-shm
tar -xzf /opt/ctyfly/backups/uploads-YYYYMMDD-HHMM.tar.gz -C /opt/ctyfly/backend/data
systemctl start ctyfly
```

## 六、待解决事项（需在机房/云平台侧操作）

### 1. 机房对 80 端口的间歇性拦截（影响较大）

**现象**：从公网访问 `http://test.ccflysim.cn` 或 `http://ccflysim.cn`，
约 50-80% 的请求被替换成机房拦截页（内容指向 `www.htuidc.com/block/index.htm`）；
443 端口也有约 20% 的连接被丢弃。

**原因**：机房（华通云 / htuidc）前置的备案检查/清洗层在拦截未在其系统登记备案的域名。

**处理**：联系机房客服，确认 `ccflysim.cn` 及其子域名的备案号已与该服务器 IP 关联，
并把 `test.ccflysim.cn` 加入白名单（子域名通常随主域名备案，但部分机房需单独登记）。

**临时规避**：内测期间一律使用 `https://test.ccflysim.cn`（HTTPS 不受注入影响），
遇到加载失败按 F5 重试。

### 2. 自研工作量证明人机验证

登录、注册、找回密码与发送验证码由自研 PoW 保护，不再依赖任何第三方验证码服务：

- 后端 `POW_CAPTCHA_ALLOW_LOCALHOST=false`，公网来源必须完成工作量证明；
- 前端 Worker 由本站打包产物加载，nginx 与后端 CSP 已放行 `worker-src 'self' blob:`；
- 无域名白名单、无第三方密钥、无外部网络请求，天然支持所有域名与子域名；
- 生产建议单独配置 `POW_CAPTCHA_SECRET`，留空则回落到 `JWT_SECRET`。

### 3. 邮件发信域名

`SMTP_FROM=noreply@ccflysim.cn`（QQ 企业邮箱）。如需提升送达率，
建议在 DNS 配置 SPF / DKIM 记录。

## 七、本地开发环境（与生产隔离）

| 项目 | 本地 |
|---|---|
| 后端 | `http://127.0.0.1:3001`（`cd backend && python run.py`） |
| 前端 | `http://localhost:5173`（`cd frontend && npm run dev`，代理 /api 与 /uploads 到 3001） |
| 生产构建预览 | 后端会自动托管 `frontend/dist`（访问 `http://localhost:3001`） |
| 人机验证 | 本地回环豁免（`POW_CAPTCHA_ALLOW_LOCALHOST=true`），不发题也不校验令牌 |

本地与生产的密钥各自独立：生产 `.env` 仅在服务器上（不入 git），
仓库内只有 `.env.example` 模板。

## 九、正式上线切换（✅ 已于 2026-10-04 执行完成）

> **以下预案已落地**：ccflysim.cn / www.ccflysim.cn（含 8443 老书签端口）现由新站 CTYFLY 服务；
> 老飞控平台已下线（PM2 cty-fly/cty-atc 已删除），源码与数据库完整备份于站长电脑 D:\CTYFLY-OLDWEB
> （ctyfly-oldweb-backup.tar.gz，含 nginx 配置/源码/cty_fly.db/db.sqlite/uploads）；fsd-sync 连飞同步与 fsd9（3010）保留未动。

> 决策已定（2026-10-04）：正式站用 **ccflysim.cn（含 www）**，test.ccflysim.cn 保留为内测环境。
> 主域当前由老「CTY 飞控」平台占用（nginx server 块 ccflysim.cn/www，后端 127.0.0.1:8000/3010）。
> 切换 = 老平台下线后，把主域的 server 块改为指向本站。全程预计 30 分钟，可随时回滚。

### 前置（切换前一次性做完，不影响现网）

1. **人机验证**：自研 PoW 无需第三方域名白名单；确认生产 `.env` 里
   `POW_CAPTCHA_ALLOW_LOCALHOST=false`，并建议配置独立的 `POW_CAPTCHA_SECRET`。
2. **后端 .env**（/opt/ctyfly/backend/.env）：
   - `ALLOWED_ORIGINS` 追加 `https://ccflysim.cn, https://www.ccflysim.cn`
   - `SITE_PUBLIC_URL=https://ccflysim.cn`（通知邮件里的站点链接）
   - 改完 `systemctl restart ctyfly`
3. **备份 nginx 现有主域配置**：`cp /etc/nginx/sites-available/ccflysim.cn.conf{,.bak-oldplatform}`

### 切换日（老平台确认可下线后）

1. 写新的主域 server 块：照抄 `test.ccflysim.cn.conf`，仅把
   `server_name` 改为 `ccflysim.cn www.ccflysim.cn`、日志路径改为 `ctyfly-main.*`
2. 老平台如需保留给老用户过渡：把它的 server 块挪到 `old.ccflysim.cn`（需加 DNS A 记录）或仅留 8000 端口内网访问
3. `nginx -t && systemctl reload nginx`（reload 不断连接）
4. 验证：`curl -I https://ccflysim.cn`（应为 200 且入口 hash 与 test 一致）、
   登录一次、发一封邮件验证码；提交表单时安全校验应在后台自动完成，用户无感
5. **301 重定向**：老平台若还有外部链接，保留一个只做
   `return 301 https://ccflysim.cn$request_uri;` 的 server 块 30 天
6. **回滚**：`mv /etc/nginx/sites-available/ccflysim.cn.conf.bak-oldplatform` 回原位 +
   `nginx -t && systemctl reload nginx`，2 分钟内恢复老平台

### 注意

- 证书已是双证（ccflysim.cn 与 test.ccflysim.cn 各一张，DNS-01 续期），切换无需动证书
- ICP 备案挂在主域下，子域/内容变更无需重新备案
- 切换当天先跑一次手动备份：`systemctl start ctyfly-backup`（或手动执行 step4 脚本）

## 十、外部监控哨兵（运维机侧，2026-10-04 上线）

告警闭环的最后一块：所有服务端告警都从服务器自己发出，**服务器整体挂掉时自身无法告警**。
补齐方案 = 运维机（站长电脑）上的外部哨兵，计划任务 `CTYFLY-ExternalWatchdog` 每 10 分钟：

1. 探测 `https://test.ccflysim.cn/api/health`（外部视角，连续 3 次失败 = 故障告警，恢复后发恢复通知）
2. 检查 `D:\CTYFLY-BACKUPS` 最新库备份是否超过 26 小时（备份链路断了立刻知道）
3. 监视 `pull-error.log` 是否有新报错

告警经 SMTP（noreply@ccflysim.cn）发往 `ALERT_TO`（配置在运维机 `D:\CTYFLY-OPS\smtp.env`，
可追加个人邮箱）。发信走 `smtps://` 465 + curl.exe（.NET SmtpClient 与 QQ 企业邮
STARTTLS 协商会卡死，勿改回）。

**已知边界**：哨兵依赖运维机开机。电脑长期关机期间，站点故障无人知晓——
建议后续有闲时再补一个免费第三方拨测（UptimeRobot 等）作双保险。
涉及凭据的文件（smtp.env）在本机 D:\CTYFLY-OPS\，已刻意放在仓库外，严禁拷入仓库。
