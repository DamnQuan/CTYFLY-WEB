"""CTYFLY 后端配置：读取 backend/.env，不存在则使用默认值"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    except OSError:
        pass


_load_env_file(BACKEND_DIR / ".env")


def env(key: str, fallback: str = "") -> str:
    return os.environ.get(key, fallback)


def flag(key: str, fallback: str = "false") -> bool:
    """布尔开关：true/1/yes/on 都算开启。

    不能只写 `== "true"` —— 运维在 .env 里写 "on"/"yes" 是很自然的，
    那样会被静默当成「关闭」，排查起来非常费劲，已踩过一次。
    """
    return env(key, fallback).strip().lower() in ("1", "true", "yes", "on")


PORT = int(env("PORT", "3001"))

# ---- 安全配置 ----
# CORS 允许的前端来源，生产环境改为你的正式域名，逗号分隔
ALLOWED_ORIGINS = [
    o.strip()
    for o in env(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if o.strip()
]
# 是否信任反向代理的 X-Forwarded-For，Nginx 等部署时设 true，否则限流按直连 IP 计
TRUST_PROXY = env("TRUST_PROXY", "false").lower() == "true"
# 是否开启 FastAPI 文档页，生产建议关闭
ENABLE_DOCS = env("ENABLE_DOCS", "false").lower() == "true"
# 是否启用限流，调试时可临时关闭，勿在生产关闭
RATE_LIMIT_ENABLED = env("RATE_LIMIT_ENABLED", "true").lower() == "true"

# 反向代理部署，Nginx 时设 true：uvicorn 依据 X-Forwarded-For 重写客户端 IP。
# 直连部署务必保持 false，防止伪造 XFF 头绕过限流与人机验证豁免。
PROXY_HEADERS = env("PROXY_HEADERS", "false").lower() == "true"

# ---- 本地上传，航司 Logo 等图片----
# 落盘目录：backend/data/uploads，由 /uploads 静态托管，不入 git
UPLOAD_DIR = Path(env("UPLOAD_DIR", str(BACKEND_DIR / "data" / "uploads")))
UPLOAD_URL_PREFIX = env("UPLOAD_URL_PREFIX", "/uploads")
# 单张图片上限，默认 2MB，仅对上传接口放宽，其余接口仍为 128KB
MAX_UPLOAD_BYTES = int(env("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024)))

# ---- 工单附件，图片 / PDF / Word----
# 安全设计：与公开静态托管的 uploads 目录物理隔离，data/attachments 不入 nginx，
# 只能经 /api/attachments/{id} 带鉴权读取，仅工单主人与管理员可见。
ATTACH_DIR = Path(env("ATTACH_DIR", str(BACKEND_DIR / "data" / "attachments")))
MAX_ATTACH_BYTES = int(env("MAX_ATTACH_BYTES", str(5 * 1024 * 1024)))
MAX_ATTACH_PER_TICKET = int(env("MAX_ATTACH_PER_TICKET", "6"))

# ---- 航路规划 sidecar，Node 服务，读取 AIRAC nd.db3----
NAVDATA_SIDECAR_URL = env("NAVDATA_SIDECAR_URL", "http://127.0.0.1:4173")
NAVDATA_SIDECAR_DIR = Path(
    env("NAVDATA_SIDECAR_DIR", str(BACKEND_DIR / "navdata-planner"))
)
NAVDATA_DB = env("NAVDATA_DB")  # 可选：指定 nd.db3 的自定义位置

JWT_SECRET = env("JWT_SECRET", "ctyfly-dev-secret-change-me")
JWT_EXPIRES = env("JWT_EXPIRES", "6h")

# ---- 自研工作量证明人机验证 ----
# 不依赖任何第三方验证码服务：服务端发 challenge，浏览器算 nonce，服务端一次哈希即可验完。
POW_CAPTCHA_ENABLED = flag("POW_CAPTCHA_ENABLED", "true")
# 前导 0 的十六进制位数，4 位约等于平均 6.5 万次哈希，浏览器百毫秒级、脚本成本明显上升
POW_CAPTCHA_DIFFICULTY = max(1, min(8, int(env("POW_CAPTCHA_DIFFICULTY", "4"))))
# challenge 与通过后签发的一次性令牌各自的有效期，单位秒
POW_CAPTCHA_CHALLENGE_TTL = max(30, int(env("POW_CAPTCHA_CHALLENGE_TTL", "300")))
POW_CAPTCHA_TOKEN_TTL = max(60, int(env("POW_CAPTCHA_TOKEN_TTL", "600")))
# 令牌签名密钥：没单独配置时回落到 JWT_SECRET，生产建议单独设置
POW_CAPTCHA_SECRET = env("POW_CAPTCHA_SECRET") or JWT_SECRET
# 本机回环与内网来源豁免，方便本地开发；生产环境应设为 false
POW_CAPTCHA_ALLOW_LOCALHOST = flag("POW_CAPTCHA_ALLOW_LOCALHOST", "true")

# JWT_SECRET 是「伪造管理员身份」的唯一门槛，必须显式配置：
# 若缺失或仍是模板默认值，任何人都能离线签出 role=admin 的令牌接管全站。
# 所以在这里直接拒绝启动，而不是带病运行。.env.example 有生成说明
if JWT_SECRET in ("", "ctyfly-dev-secret-change-me", "please-change-me-to-a-random-long-string"):
    raise RuntimeError(
        "JWT_SECRET 未配置或仍是示例默认值。请在 backend/.env 中设置一个随机长字符串，"
        "例如：python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )

SMTP_HOST = env("SMTP_HOST")
SMTP_PORT = int(env("SMTP_PORT", "465"))
SMTP_USER = env("SMTP_USER")
SMTP_PASS = env("SMTP_PASS")
SMTP_FROM = env("SMTP_FROM", SMTP_USER)

# 站点公开访问地址：通知邮件里的「请登录 xxx 查看详情」等文案引用，
# 生产换域名时改 .env 的 SITE_PUBLIC_URL 即可，不再写死测试域名
SITE_PUBLIC_URL = env("SITE_PUBLIC_URL", "https://test.ccflysim.cn")

# 是否播种演示内容，示例航路 / 示例活动 / 公告 / 商城商品。
# 默认 false：生产库只创建管理员账号与系统权限表，不写入任何示例数据。
# 本地开发想要这些示例数据，在 backend/.env 里设 SEED_DEMO_DATA=true。
SEED_DEMO_DATA = env("SEED_DEMO_DATA", "false").lower() == "true"

# ---- 日志保留与归档，2026-10-18----
# 站长要求：官网，管理后台只保留最近 LOG_RETENTION_DAYS 天；更早的日志不能丢，
# 过期前由 app/logretention.py 先归档为 gzip JSONL 到 LOG_ARCHIVE_DIR 再删除。
# 归档目录是**服务器本地数据**，不进 git、不在前端展示，需要时人工取证。
LOG_RETENTION_DAYS = int(env("LOG_RETENTION_DAYS", "30"))
LOG_ARCHIVE_DIR = Path(env("LOG_ARCHIVE_DIR", str(BACKEND_DIR / "data" / "log-archive")))

# 浏览器主动探测公网 IPv6，WebRTC/STUN 并回传。
# 为什么需要：站点当前只有 IPv4 入口，服务器无全局 IPv6、DNS 无 AAAA，
# 单看 HTTP 连接只能拿到 IPv4；客户端自身的 IPv6 只能由浏览器探测后回传。
# 隐私：会在浏览器内发起一次 STUN 查询，默认 Cloudflare STUN，并将探测结果存到
# users.last_ip_v6；已在隐私政策中披露。不需要时设 IPV6_PROBE_ENABLED=false 关闭。
IPV6_PROBE_ENABLED = env("IPV6_PROBE_ENABLED", "true").lower() == "true"


# ---- 航情数据源，可选的增强源，不配置也能用----
# CheckWX / AVWX 都提供免费额度的 API key，需各自官网注册。
# 配置后它们会加入 METAR/TAF 的多源竞速，进一步提高可用性；
# 不配置则只用免费公开源，aviationweather.gov / metar.vatsim.net / NOAA tgftp。
# Key 属于凭据，只写在 backend/.env，不进 git。
CHECKWX_API_KEY = env("CHECKWX_API_KEY")
AVWX_TOKEN = env("AVWX_TOKEN")

# ---- 桌宠 AI 对话，火山方舟 / 豆包----
# 未配置 ARK_API_KEY 时自动降级为前端预设台词，功能不受影响。
ARK_API_KEY = env("ARK_API_KEY")
ARK_BASE_URL = env("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
ARK_MODEL = env("ARK_MODEL", "doubao-seed-evolving")
PET_AI_ENABLED = flag("PET_AI_ENABLED", "true")
ARK_TIMEOUT = float(env("ARK_TIMEOUT", "25"))
# 单次回复的输出上限。注意 doubao-seed-evolving 是推理模型：
# 必须同时关闭思考，见 routers/pet.py，否则推理会把额度烧光、一个字都吐不出来。
PET_MAX_TOKENS = int(env("PET_MAX_TOKENS", "220"))
# 送给模型的历史轮数，仅进程内保存，不落库
PET_HISTORY_TURNS = int(env("PET_HISTORY_TURNS", "6"))
# 全站每日总调用上限，兜住成本
PET_DAILY_LIMIT = int(env("PET_DAILY_LIMIT", "2000"))

SEED_ADMIN = {
    "cid": env("ADMIN_CID", "1000"),
    "username": env("ADMIN_USERNAME", "admin"),
    "password": env("ADMIN_PASSWORD", ""),
    "email": env("ADMIN_EMAIL", "admin@ctyfly.local"),
}

# ---- 脚本/爬虫防线，2026-10-10 补强，见运维手册 §6.8----
# 自动封禁默认有效天数：动态 IP 被回收再分配给真实用户时不会永久误伤；0 = 永久。
# 手动封禁走管理后台「IP 黑名单」页，期限由管理员决定。
BAN_AUTO_DAYS = int(env("BAN_AUTO_DAYS", "90"))
# 行为异常检测，只写风险事件，绝不自动封禁：同一主体在窗口内的请求数 / 不同接口数。
# 阈值刻意放宽 —— 正常用户一次页面加载也会连打十几个接口，不能因此误报。
ANOMALY_ENABLED = flag("ANOMALY_ENABLED", "true")
ANOMALY_WINDOW = int(env("ANOMALY_WINDOW", "10"))         # 窗口，秒
ANOMALY_MAX_REQ = int(env("ANOMALY_MAX_REQ", "80"))       # 窗口内请求数上限
ANOMALY_MAX_PATHS = int(env("ANOMALY_MAX_PATHS", "30"))   # 窗口内不同接口数上限
ANOMALY_COOLDOWN = int(env("ANOMALY_COOLDOWN", "120"))    # 同一主体重复告警冷却，秒
# 客户端特征自洽性：UA 声称是浏览器但请求头不像浏览器 → 记风险事件，不封禁
UA_ANOMALY_ENABLED = flag("UA_ANOMALY_ENABLED", "true")


def smtp_enabled() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


def jwt_ttl_seconds() -> int:
    """把 '7d' / '12h' / '30m' 解析为秒"""
    import re

    m = re.fullmatch(r"(\d+)\s*([dhms])", JWT_EXPIRES.strip().lower())
    if not m:
        return 7 * 24 * 3600
    value = int(m.group(1))
    return value * {"d": 86400, "h": 3600, "m": 60, "s": 1}[m.group(2)]

# ---- 时间戳口径，2026-10-11 站长评审第 3 条：换服务器时区会有隐患----
# 现状：**所有时间戳按「服务器本地时间」存储**，schema 默认值统一 datetime 'now','localtime'，
# 49 张表、代码里 119 处，当前服务器时区 Asia/Shanghai UTC+8，存储值即北京墙上时间。
# 业务日边界，发薪每日上限、报告频率 24h 判定同样用 localtime —— 与存储同口径，所以现在自洽。
#
# 风险：一旦迁移到默认 UTC 的新机器且忘了设时区，存储会变成 UTC，而「业务日」的含义随之漂移
#用户以为的"今天"会错开 8 小时，每日发薪上限窗口跟着错位，且前端不做时区转换、直接展示。
# 因此这里显式声明「期望的业务时区偏移」，启动时校验并告警，见 main.py 的 lifespan。
# 完整迁移到 UTC 存储的方案与影响面见交接文档 §34.14，49 张表 DDL 默认值 + 119 处写入 +
# 前端每处展示，属跨端改动，按「先立约定、再迁移」的节奏单独做。
BUSINESS_TZ_OFFSET_HOURS = int(env("BUSINESS_TZ_OFFSET_HOURS", "8"))