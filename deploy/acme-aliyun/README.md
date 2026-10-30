# 阿里云云解析自动签发（DNS-01）

给 `ccflysim.cn` 的泛域名证书做**无人值守自动续期**。

## 为什么需要它

原来 certbot 里那条 `ccflysim.cn` lineage（`*.ccflysim.cn` + `ccflysim.cn`）用的是
`authenticator = manual`：签发时靠人工去阿里云控制台加 TXT 记录，**到期续期时无人值守必然失败**，
证书于 2026-09-10 过期且没有任何告警。本目录用阿里云 API 把这一步自动化。

> 注意：nginx 旧官网（`server_name ccflysim.cn`）当时并没有用这张过期的证书，
> 而是指向 `/etc/nginx/ssl/ccflysim/` 下手动安装的 TrustAsia 证书（2026-12-10 到期）。
> 两件事互不影响，详见文末「切换 nginx」。

## 文件

| 文件 | 说明 |
| --- | --- |
| `aliyun_dns_hook.py` | certbot manual 钩子。**只用 Python 标准库**，无需 pip 安装任何依赖 |

## 凭据

服务器上 `/etc/ctyfly/aliyun-dns.ini`，权限 `600`、属主 `root`（**绝不入 git**）：

```ini
accessKeyId=LTAI...
accessKeySecret=...
# 可选，留空则自动探测主域名
zone=ccflysim.cn
```

脚本按以下顺序查找：`$ALIYUN_DNS_INI` → `/etc/ctyfly/aliyun-dns.ini` → `~/.aliyun-dns.ini`，
都找不到时回落到环境变量 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET`。

## 签发 / 续期

```bash
HOOK=/opt/ctyfly/deploy/acme-aliyun/aliyun_dns_hook.py

certbot certonly \
  --cert-name ccflysim.cn \
  --manual --preferred-challenges dns \
  --manual-auth-hook "$HOOK auth" \
  --manual-cleanup-hook "$HOOK cleanup" \
  -d ccflysim.cn -d '*.ccflysim.cn' \
  --non-interactive --agree-tos --no-eff-email
```

### ⚠️ 两个必须记住的坑

1. **`auth` / `cleanup` 子命令必须写进 certbot 的选项字符串里。**
   certbot 1.21 的 `manual` 插件在 `_execute_hook()` 里是把 hook 命令**原样**执行的，
   **不会**自动附加 `auth`/`cleanup` 参数。写成 `--manual-auth-hook "$HOOK"` 会让脚本收不到参数而直接退出，
   表现为 `unauthorized` 但日志里其实一条 TXT 都没写。
2. **泛域名 + 主域名会命中同一个 `_acme-challenge` RR。**
   certbot 会调用两次 auth 钩子（两个不同的校验值），必须让两条 TXT 记录并存。
   阿里云云解析支持同 RR 多值 TXT，本钩子靠「值不同则追加、值相同则跳过」来保证这一点。

## 钩子做了什么

- 自动探测主域名（对 `test.ccflysim.cn` 这类子域会定位到 `ccflysim.cn`，主机记录写成 `_acme-challenge.test`）
- `auth`：新增 TXT → **向该域名的权威 NS 直接轮询**（标准库手写 DNS 查询，不依赖 dig/dnspython），
  确认所有权威 NS 都能查到校验值后才返回，避免盲目 `sleep`
- `cleanup`：按值精确删除自己加的那条，幂等（重复调用不报错）

## 验证

```bash
# 只读检查
certbot certificates
grep -E 'manual_(auth|cleanup)_hook' /etc/letsencrypt/renewal/ccflysim.cn.conf

# 演习：走 Let's Encrypt staging，不替换正式证书，但完整跑一遍 hook
certbot renew --cert-name ccflysim.cn --dry-run
```

自动续期由系统已有的 `certbot.timer`（`systemctl status certbot.timer`）驱动，无需额外 cron。

## 切换 nginx（**本目录未执行**）

旧官网目前指向 `/etc/nginx/ssl/ccflysim/` 那张 TrustAsia 证书（2026-12-10 到期）。
如果希望它改用 Let's Encrypt 这张（自动续期），改 `sites-enabled/ccflysim`：

```nginx
ssl_certificate     /etc/letsencrypt/live/ccflysim.cn/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/ccflysim.cn/privkey.pem;
```

然后 `nginx -t && systemctl reload nginx`。
LE 证书已包含 `ccflysim.cn` 与 `*.ccflysim.cn`，能覆盖旧站现有的 `ccflysim.cn` / `www.ccflysim.cn`。

## 回滚

部署前的备份在 `/root/ctyfly-cert-backup-<时间戳>/`（含 `ccflysim-ssl/`、`renewal/`、`letsencrypt-live.tgz`）。
