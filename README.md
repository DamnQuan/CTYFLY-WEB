# CTY 飞控官网 · CTYFLY-WEB

CTY 飞行管制社区（CTYFLY）的官网与运营平台：**Vue 3 前端 + Python FastAPI 后端**，Apple 风格玻璃拟态（Glassmorphism）UI，前后端完全分离、各自独立依赖。覆盖账号体系、航情与航路、连飞活动、工单、虚拟航司（VA）运营、市场与经济、成就、桌宠 AI 与管理后台。

- 🌐 线上：https://ccflysim.cn（测试环境：https://test.ccflysim.cn）
- 🧩 同作者项目：**CWFLY**（[CWFLY-WEB](https://github.com/yuanshen-123-ui/CWFLY-WEB) / [CWFLY-FSD](https://github.com/yuanshen-123-ui/CWFLY-FSD) 等 6 个仓库）

---

## 一、功能清单

### 账号与安全
- 注册：CID（纯数字、查重、随机 CID、每会话限次）、用户名、邮箱验证码、QQ 号（选填，自动拉 QQ 头像）、密码
- 登录：CID / 用户名 + 密码；连续失败 5 次锁定 10 分钟；邮箱找回密码
- **自研 PoW 人机验证**：服务端下发 challenge，浏览器 Web Worker 本地算 nonce，服务端复算哈希后签发一次性令牌；业务接口校验 `X-PoW-Token`；全程无第三方验证码服务、用户无感
- 合规页：隐私政策、服务条款、Cookie 政策、关于、合作伙伴、服务状态

### 飞行相关
| 模块 | 能力 |
|---|---|
| 航情 | METAR 报文、TAF 预报（aviationweather.gov 为主，可叠加 CheckWX / AVWX；httpx 上游代理） |
| 航路规划 | AIRAC 导航数据 A* 高空航路规划 + SID/STAR + 备选航线 + 自定义航路分析 + Leaflet 地图（`navdata-planner` sidecar，Node 服务读 `nd.db3`） |
| 连飞活动 | 活动列表/详情/简报、报名（自定义呼号）、历史活动；管理员创建/开始/结束/取消/删除 |
| 机场地图 | 机场分布与检索（公开数据） |

### 社区与运营
- 仪表盘：个人统计、报名活动、公告
- 申请中心：管制员申请、职员申请，含审核状态跟踪
- 工单中心：提交、对话式回复、关闭/重开；附件（图片/PDF/Word，带权限校验）
- 平台发展问卷：公开路由 `/docs`，题目服务端下发；登录用户自动带身份，游客可匿名提交
- ACIS 事件检索：飞圈事件智能检索与论坛，标题拼音全量浏览、最新最热精选、免登录投稿纠错、点赞收藏评论与后台审核
- 个人中心：资料修改（QQ 头像同步）、修改密码

### 虚拟航司（VA）与经济
| 模块 | 能力 |
|---|---|
| 航司 | 航司列表/详情、公开航司主页、航司排行榜、航司审核 |
| 运营 | 抢标（bidding）、机队（fleet）、航线（routes）、签派（dispatch）、PIREP 上报 |
| 经济 | 钱包、市场（market）、航司商店（va_shop）、商品（shop） |
| 成就 | 成就列表与解锁进度（achievements） |

### 趣味与 AI
- **桌宠**：前端 `deskpet/` 组件 + 后端 `pet.py`；可接入火山方舟（豆包）模型，未配置 Key 时自动降级为内置预设台词 + 关键词应答
- 事件/事故记录（incidents）

### 管理后台
- 数据概览：用户、待审申请、待审批、工单、活动、航司、今日登录、登录失败、风险事件、注册趋势
- 用户管理：查看注册 IP / 地理位置 / 设备指纹 / 最近登录；调整管制等级、飞行员等级、重置密码
- 权限管理：角色能力矩阵（11 项能力 × ADM/SUP/USER），ADM 恒有全部权限且不可修改
- 审批中心：角色变更 / 封禁 / 删除账号需 **2 名 ADM 或 SUP 复核通过**；发起人与当事人不能审批；任一驳回即终止
- 申请审核：管制员申请、职员申请（两个独立页面）
- 活动 / 工单 / 公告 / 航司审核
- 日志中心：登录日志、注册日志（IP/地理位置/设备指纹/UA）、网络日志（按接口聚合访问量/错误率）、审计日志（七类事件）

---

## 二、技术栈

| 端 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + Vue Router + Pinia；自定义 Apple 风格玻璃拟态设计系统（深色模式）；Leaflet 地图 |
| 后端 | Python 3.12 · FastAPI + Uvicorn；SQLite（标准库 `sqlite3`，单文件库，幂等迁移） |
| 认证 | PyJWT + bcrypt 口令哈希；自研 PoW 人机验证 |
| 邮件 | 标准库 `smtplib`（SMTP_SSL / STARTTLS）：注册验证码、找回密码、通知 |
| 上游 | `httpx`（METAR/TAF，默认遵循 `HTTPS_PROXY`）；navdata sidecar（Node + AIRAC） |
| 部署 | systemd（`ctyfly.service`）、Nginx、PowerShell/Bash 部署脚本、smoke 测试 |

---

## 三、目录结构

```
CTYFLY-WEB/
├── backend/                     # Python 后端（FastAPI）
│   ├── app/
│   │   ├── main.py              # 入口：中间件、统一错误格式、路由注册
│   │   ├── config.py            # .env 配置
│   │   ├── database.py          # SQLite 建库 + 幂等迁移 + 种子数据
│   │   ├── security.py          # bcrypt + PyJWT
│   │   ├── deps.py              # 登录态 / 管理员依赖
│   │   ├── middleware.py        # 安全响应头
│   │   ├── ratelimit.py         # 限流（滑动窗口）
│   │   ├── captcha.py           # PoW 人机验证（challenge/校验/令牌）
│   │   ├── mailer.py            # SMTP 验证码
│   │   ├── permissions.py       # 能力/角色矩阵
│   │   ├── approvals.py         # 双人复核审批
│   │   ├── audit.py             # 审计日志
│   │   ├── economy.py / fuel.py # 经济与油耗
│   │   ├── navdistance.py       # 航路距离计算
│   │   ├── pet_context.py       # 桌宠 AI 上下文
│   │   ├── survey.py / seed_data.py / text.py / requestinfo.py / logretention.py
│   │   ├── migrations/          # 幂等迁移函数
│   │   └── routers/             # 22 个路由模块（见下表）
│   ├── navdata-planner/         # 航路规划 sidecar（Node，AIRAC nd.db3）
│   ├── data/                    # ctyfly.db、上传与附件目录（不入库）
│   ├── tests/                   # pytest
│   ├── run.py                   # 启动脚本
│   ├── requirements.txt
│   └── .env.example
├── frontend/                    # Vue 3 前端
│   ├── src/
│   │   ├── views/               # 38 个页面（见下）
│   │   ├── components/          # Sidebar / Icon / RoutePlanner / RouteMap / AppModal / CookieConsent …
│   │   ├── deskpet/             # 桌宠组件
│   │   ├── composables/         # 组合式函数
│   │   ├── lib/                 # 工具库
│   │   ├── stores/              # Pinia
│   │   ├── styles/main.css      # Apple 玻璃拟态设计系统（含深色模式）
│   │   └── router/              # 路由 + 守卫
│   ├── public/  scripts/        # 静态资源与构建脚本
│   ├── package.json             # dev / build / lint / test / preview / check:pet
│   └── vite.config.js / vitest.config.js
├── deploy/                      # 部署资产
│   ├── ctyfly.service / ctyfly-test.service   # systemd
│   ├── nginx-ccflysim.cn.conf / nginx-test.ccflysim.cn.conf
│   ├── deploy.ps1 / deploy-test.ps1 / step1-nginx.sh / step4-backup.sh / remote-swap.sh
│   ├── install-airdata.ps1 / install-airdata.sh
│   └── smoke.ps1                # 部署后冒烟检查
├── 交接文档/                     # 历次交接与功能历史（含恢复演练记录）
├── check-all.ps1                # 一键检查（前端 lint/test + 后端 pytest 等）
└── README.md
```

### 后端路由（`backend/app/routers/`）

| 模块 | 说明 |
|---|---|
| `auth.py` | 注册 / 登录 / 找回密码 / 刷新 / 登出 |
| `captcha.py` | PoW challenge 下发与校验 |
| `achievements.py` | 成就 |
| `admin.py` | 管理后台聚合接口 |
| `airlines.py` | 航司列表/详情/审核/排行榜 |
| `applications.py` | 管制员 / 职员申请 |
| `bidding.py` | 抢标 |
| `dispatch.py` | 签派 |
| `events.py` | 连飞活动 |
| `incidents.py` | 事件/事故记录 |
| `market.py` | 市场 |
| `misc.py` | 其他/公共 |
| `navdata.py` | 航路规划 sidecar 代理 |
| `pet.py` | 桌宠 AI |
| `pirep.py` | 航班报告 |
| `shop.py` / `va_shop.py` | 商店 / 航司商店 |
| `survey.py` | 平台发展问卷 |
| `tickets.py` | 工单（含附件） |
| `uploads.py` | 图片上传 |
| `wallet.py` | 钱包/交易 |
| `weather.py` | METAR / TAF |

### 前端页面（`frontend/src/views/`，节选）

登录/注册/找回、首页、仪表盘、航情（METAR/TAF/航路）、航线、机场地图、活动（列表/简报/历史）、申请、工单、问卷、个人中心、市场、钱包、商店、成就、排行榜、航司（列表/详情/公开页/机队/航线/签派/PIREP/商店/抢标）、公告/变更日志、隐私/条款/Cookie/关于/合作伙伴/状态。

---

## 四、环境变量（`backend/.env`）

| 分类 | 变量 | 说明 |
|---|---|---|
| 基础 | `PORT` | API 端口（默认 3001） |
| 基础 | `JWT_SECRET` / `JWT_EXPIRES` | JWT 密钥（生产必改）/ 有效期 |
| 网络 | `ALLOWED_ORIGINS` | CORS 允许来源（逗号分隔） |
| 网络 | `TRUST_PROXY` / `PROXY_HEADERS` | 是否信任反代 XFF（Nginx 部署 true，直连 false，防伪造绕过限流） |
| 文档 | `ENABLE_DOCS` | 是否开放 `/api/docs`（生产 false） |
| 限流 | `RATE_LIMIT_ENABLED` | 生产必须 true |
| 上传 | `UPLOAD_DIR` / `UPLOAD_URL_PREFIX` / `MAX_UPLOAD_BYTES` | 图片上传目录/URL 前缀/单图上限（默认 2MB） |
| 附件 | `ATTACH_DIR` / `MAX_ATTACH_BYTES` / `MAX_ATTACH_PER_TICKET` | 工单附件目录/单件上限（5MB）/每单数量（6） |
| 航路 | `NAVDATA_SIDECAR_URL` / `NAVDATA_SIDECAR_DIR` / `NAVDATA_DB` | 航路 sidecar 地址/代码目录/nd.db3 路径 |
| 邮件 | `SMTP_HOST/PORT/USER/PASS/FROM` | 未配置时进入开发模式（验证码直接显示在页面） |
| AI | `ARK_API_KEY` / `ARK_BASE_URL` / `ARK_MODEL` / `PET_AI_ENABLED` / `ARK_TIMEOUT` / `PET_HISTORY_TURNS` / `PET_MAX_TOKENS` / `PET_DAILY_LIMIT` | 火山方舟（豆包）；未配置自动降级 |
| 站点 | `SITE_PUBLIC_URL` | 站点公开地址（邮件里的链接） |
| 初始管理员 | `ADMIN_CID` / `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | 首次启动自动创建；**`ADMIN_PASSWORD` 必须自行设置强口令** |
| 种子 | `SEED_DEMO_DATA` | false=仅建表+管理员；true=演示数据（生产保持 false） |
| 航情增强 | `CHECKWX_API_KEY` / `AVWX_TOKEN` | 可选，填入后加入竞速源 |
| 代理 | `HTTPS_PROXY` / `HTTP_PROXY` | 服务器无直连外网时配置 |
| PoW | `POW_CAPTCHA_ENABLED` / `POW_CAPTCHA_DIFFICULTY` / `POW_CAPTCHA_CHALLENGE_TTL` / `POW_CAPTCHA_TOKEN_TTL` / `POW_CAPTCHA_SECRET` / `POW_CAPTCHA_ALLOW_LOCALHOST` | 人机验证；生产必须 `ALLOW_LOCALHOST=false` 并单独配置 `SECRET` |

---

## 五、本地开发

```bash
# 1) 前端依赖
cd frontend && npm install

# 2) 后端依赖（建议虚拟环境）
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 3) 环境变量（可选，不配置则验证码走开发模式）
copy .env.example .env            # 然后在 backend/.env 填 SMTP / 管理员口令

# 4) 启动后端（http://localhost:3001）
python run.py

# 5) 启动前端（http://localhost:5173）
cd frontend && npm run dev
```

- 首次启动自动建库（`backend/data/ctyfly.db`）、执行幂等迁移、创建管理员账号
- 未配置 SMTP 时为**开发模式**：验证码直接返回给页面提示条并打印到后端控制台
- 航情查询需访问 aviationweather.gov；无直连外网时在 `.env` 配置 `HTTPS_PROXY`

### 测试与检查

```bash
cd frontend && npm run lint && npm run test     # ESLint + Vitest
cd backend && pytest                            # 后端测试
pwsh ./check-all.ps1                            # 一键全检查
```

---

## 六、部署

```bash
# 构建前端
cd frontend && npm run build

# 部署（Windows PowerShell 脚本）
pwsh ./deploy/deploy.ps1                        # 生产
pwsh ./deploy/deploy-test.ps1                   # 测试环境
pwsh ./deploy/smoke.ps1                         # 冒烟检查

# 服务器侧（Linux）
sudo systemctl daemon-reload
sudo systemctl enable --now ctyfly.service      # 或 ctyfly-test.service
sudo systemctl status ctyfly.service
```

- Nginx：`deploy/nginx-ccflysim.cn.conf`（生产）、`deploy/nginx-test.ccflysim.cn.conf`（测试）
- 部署脚本包含：`step1-nginx.sh`（Nginx 配置）、`step4-backup.sh`（备份）、`remote-swap.sh`（远端切换）、`install-airdata.*`（导航数据）
- 备份：`deploy/step4-backup.sh`；数据库为单文件 SQLite（`backend/data/ctyfly.db`），直接复制即可

---

## 七、安全要点

- **首次部署必须修改 `ADMIN_PASSWORD`**，不要使用示例值
- 生产：`ENABLE_DOCS=false`、`POW_CAPTCHA_ALLOW_LOCALHOST=false`、`RATE_LIMIT_ENABLED=true`、`TRUST_PROXY`/`PROXY_HEADERS` 按是否反代设置
- 敏感项（SMTP 授权码、`ARK_API_KEY`、`JWT_SECRET`、PoW `SECRET`）**只写 `.env`**，仓库只提交 `.env.example`
- 高危操作（角色变更 / 封禁 / 删除账号）强制 **2 人复核**；审计日志留存
- 上传目录与附件目录物理隔离，附件仅工单主与管理员可读

---

## 八、与 CWFLY 的区别

| 维度 | CTYFLY-WEB | CWFLY（6 仓库） |
|---|---|---|
| 定位 | CTY 飞控社区官网 + VA 运营 | 模拟飞行社区 + FSD 连线 + 管制中心 |
| 后端 | Python FastAPI + SQLite | Node.js Express + Prisma + MySQL |
| 前端 | Vue 3 + 玻璃拟态 | Vue 3 + AMap/Mapbox 3D |
| 特色 | VA 运营、经济系统、桌宠 AI、PoW 验证、双人复核审批 | FSD 协议栈、在线地图、航迹回放、管制中心、QQ 机器人 |

---

## 九、相关仓库

| 仓库 | 内容 |
|---|---|
| [CTYFLY-WEB](https://github.com/yuanshen-123-ui/CTYFLY-WEB) | 本项目（本仓库） |
| [CWFLY-WEB](https://github.com/yuanshen-123-ui/CWFLY-WEB) | 同作者项目：模拟飞行社区主站 |
| [CWFLY-FSD](https://github.com/yuanshen-123-ui/CWFLY-FSD) | 同作者项目：FSD 连线服务器 |

---

## 贡献

欢迎参与！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；
提交 PR 即视为同意 [CLA.md](CLA.md)（你保留自己贡献的版权，同时授予项目发起人再许可能力）。

---

## 许可证

本项目采用 **GNU General Public License v3.0**（GPL-3.0）开源。
完整条款见仓库根目录 [LICENSE](LICENSE)；简单说明：

- 允许自由使用、修改、分发本软件（含商业用途）
- 分发修改版或衍生作品时必须同样以 GPL-3.0 开源，并提供源码
- 不提供任何担保（详见 GPL-3.0 第 15、16 条）

版权归**所有著作人**（项目发起人及所有贡献者）所有。
Copyright (C) 2026 全体著作人（All contributors）
