"""CTYFLY 后端入口，FastAPI"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import (ALLOWED_ORIGINS, ENABLE_DOCS, MAX_ATTACH_BYTES,
                     MAX_UPLOAD_BYTES, PORT, POW_CAPTCHA_ENABLED,
                     UPLOAD_DIR, smtp_enabled)
from .database import init_db
from . import logretention
from .middleware import (AccessLogMiddleware, ApiMetricsMiddleware,
                         BodySizeLimitMiddleware, GlobalRateLimitMiddleware,
                         SecurityHeadersMiddleware)
from .routers import (admin, airlines, applications, auth, captcha, events,
                      misc, navdata, perf, pet, shop, survey, tickets, uploads, weather)
from .routers import dispatch, pirep, wallet
from .routers.shop import shop_admin_router
from .routers import va_shop
from .routers import bidding, achievements, market, incidents, archive


def _console(text: str) -> None:
    """启动日志打印：控制台编码不支持时退回 ASCII。

    为什么要有这层：2026-10-17 本地起服务实测，自检输出的「⚠️」在 Windows GBK 控制台
    上 print 直接抛 UnicodeEncodeError，把 lifespan 整个带崩 —— 自检本来就设计成
    「只告警、不挡启动」，不能反过来被控制台编码弄死。Linux/CI，UTF-8 不受影响，
    但本地开发机不该因为一条告警起不来服务。
    """
    try:
        print(text)
    except UnicodeEncodeError:
        fallback = text.encode("ascii", "ignore").decode("ascii").strip()
        print(fallback or "[startup] 当前控制台编码无法显示该日志")


def _check_storage_timezone() -> None:
    """启动自检：库内时间口径，SQLite 的 'localtime'是否落在期望的业务时区

    存储，schema 默认值与业务日边界，发薪每日上限、报告 24h 频率都用 'localtime'，
    与服务器时区绑定。一旦迁到默认 UTC 的新机器又忘了设时区，「今天」的含义、
    每日额度窗口、前端展示会整体偏移 8 小时 —— 启动时明确告警，不要等用户发现。
    详见交接文档 §34.14 与 config.BUSINESS_TZ_OFFSET_HOURS。
    """
    from .config import BUSINESS_TZ_OFFSET_HOURS
    from .database import get_conn

    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT CAST(ROUND((julianday(datetime('now','localtime'))"
                " - julianday(datetime('now'))) * 24) AS INTEGER) AS off"
            ).fetchone()
        offset = int(row["off"] if row else 0)
    except Exception as exc:                     # noqa: BLE001 - 自检失败不该挡住启动
        _console(f"[tz] 时间口径自检失败，不影响启动：{exc}")
        return

    if offset != BUSINESS_TZ_OFFSET_HOURS:
        _console(
            f"[tz] ⚠️ 服务器时区偏移 UTC{offset:+d}，期望 UTC{BUSINESS_TZ_OFFSET_HOURS:+d}。"
            f"库内时间戳与「业务日」边界都按服务器本地时间存储/计算：时区不符会导致"
            f"前端展示与每日发薪额度窗口整体偏移。请修正系统时区，或显式设置"
            f" BUSINESS_TZ_OFFSET_HOURS 并同步迁移既有数据。"
        )
    else:
        _console(f"[tz] 时间口径：服务器本地时间 = UTC{BUSINESS_TZ_OFFSET_HOURS:+d}，与业务时区一致")


def _check_ledger_invariant() -> None:
    """启动自检：账本不变量 —— 每家公司 SUM amount 必须等于 airlines.balance

    为什么要有这道自检：2026-10-11 收口验收时发现测试环境有 4 行 expense 被存成正数
    修 `abs amount ` 符号 bug 之前留下的数据，导致「账本净额 8000」而「余额 6000」。
    这类脏数据此前没有任何机制能发现 —— 界面照常显示，直到有人对账才暴露。
    这里在启动时用一条只读查询扫一遍，有问题就明确告警，只告警、不挡启动。
    账本口径见 routers/wallet.py 的 airline_ledger_view：amount 带符号，收入为正、支出为负。
    """
    from .database import get_conn

    try:
        with get_conn() as conn:
            bad = conn.execute(
                "SELECT a.id, a.name, a.balance,"
                " (SELECT COALESCE(SUM(amount), 0) FROM airline_ledger l WHERE l.airline_id = a.id) AS net"
                " FROM airlines a"
                " WHERE a.balance <> (SELECT COALESCE(SUM(amount), 0) FROM airline_ledger l"
                "                     WHERE l.airline_id = a.id)"
            ).fetchall()
            mis_signed = conn.execute(
                "SELECT COUNT(*) c FROM airline_ledger"
                " WHERE (type = 'expense' AND amount > 0) OR (type = 'revenue' AND amount < 0)"
            ).fetchone()["c"]
    except Exception as exc:                     # noqa: BLE001 - 自检失败不该挡住启动
        _console(f"[ledger] 账本自检失败，不影响启动：{exc}")
        return

    if bad:
        detail = "；".join(f"#{r['id']} {r['name']} 余额{r['balance']}/账本{r['net']}" for r in bad[:5])
        _console(f"[ledger] ⚠️ 账本不变量不成立，{len(bad)} 家：{detail}"
                 f" —— 请核对 airline_ledger 的符号，支出应为负数")
    elif mis_signed:
        _console(f"[ledger] ⚠️ 发现 {mis_signed} 行符号异常，expense 为正 / revenue 为负，请核对")
    else:
        _console("[ledger] 账本自检：全部航司账实对平")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _check_storage_timezone()
    _check_ledger_invariant()
    if smtp_enabled():
        print("[smtp] SMTP 已配置，验证码将通过邮件发送")
        # 预热 SMTP：腾讯企业邮箱对新建连接有冷启动惩罚，实测可达 17s+，
        # 启动即建立常驻连接并保活，用户第一次请求验证码也能秒回秒到
        from . import mailer
        mailer.prewarm()
    else:
        print("[smtp] 未配置 SMTP，验证码将以开发模式直接返回，请在 backend/.env 中配置 SMTP_HOST/SMTP_USER/SMTP_PASS")
    # 人机验证关闭时给出提示：这是有意开关，不是配置缺失
    if not POW_CAPTCHA_ENABLED:
        print("[pow] 工作量证明人机验证已关闭，登录、注册、找回密码将不要求 PoW 令牌")
    # 种子管理员若使用源码里公开的默认密码，必须大声提醒，新库首次启动时会真的用它建号
    # 注意：ADMIN_PASSWORD 是 config.seed_demo_data 的函数内变量，这里要用 env 助手重取；
    # 写成 `from .config import ADMIN_PASSWORD` 会 ImportError 并让整个应用拒绝启动，踩过的坑。
    from .config import env as _env
    if not _env("ADMIN_PASSWORD"):
        print("[security] 警告：ADMIN_PASSWORD 未配置。首次建库会生成随机管理员密码并打印到日志，"
              "请立即登录修改，或在 backend/.env 显式配置")
    # 后台预热航路规划 sidecar，不阻塞启动
    try:
        navdata.warm_start()
    except Exception:
        pass
    # 日志保留期：官网只展示最近 30 天；过期前先归档到服务器，log-archive 再删除。
    # 启动跑一次 + 每 24h 一次，见 logretention.py。
    try:
        summary = logretention.purge_old_logs()
        changed = {
            k: {"archived": v.get("archived", 0), "deleted": v.get("deleted", 0)}
            for k, v in summary.items()
            if v.get("archived") or v.get("deleted") or v.get("error")
        }
        if changed:
            print(f"[retention] 启动归档/清理超过 30 天的日志: {changed}")
    except Exception as exc:
        print(f"[retention] 启动归档/清理失败: {exc}")
    logretention.start()
    yield


app = FastAPI(
    title="CTYFLY API",
    lifespan=lifespan,
    # 生产默认关闭文档页，减小攻击面；需要调试时设 ENABLE_DOCS=true。
    # 文档路径放在 /api 下：/docs 已由前端问卷调查页占用。
    docs_url="/api/docs" if ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if ENABLE_DOCS else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# 中间件顺序：后添加的在外层。安全头放最后，最外层，429/413 也带安全头，
# 其内依次为：访问量统计 → 全局限流 → 请求体大小限制
# 上传接口需要放宽体积上限，其余接口维持 128KB
app.add_middleware(
    BodySizeLimitMiddleware,
    path_limits={
        "/api/uploads/": (
            MAX_UPLOAD_BYTES + 64 * 1024,
            f"图片大小不能超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB，请压缩后再上传",
        ),
        # 工单附件，单文件上限 + multipart 表单开销
        "/api/tickets/": (
            MAX_ATTACH_BYTES + 512 * 1024,
            f"附件大小不能超过 {MAX_ATTACH_BYTES // (1024 * 1024)} MB",
        ),
        # 活动海报 / 简报截图，2026-10-18 修复：此前没有这一条，落到默认 128KB，
        # 一张普通海报就被 413「请求体过大」拦掉 —— 前端压到 2MB 内也照样失败。
        "/api/events/": (
            MAX_ATTACH_BYTES + 512 * 1024,
            f"图片大小不能超过 {MAX_ATTACH_BYTES // (1024 * 1024)} MB，请压缩后再上传",
        ),
    },
)
app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(ApiMetricsMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(misc.router)
app.include_router(captcha.router)
app.include_router(survey.router)
app.include_router(auth.router)
app.include_router(weather.router)
app.include_router(events.router)
app.include_router(events.briefing_router)
app.include_router(applications.router)
app.include_router(tickets.router)
app.include_router(tickets.attach_router)
app.include_router(navdata.router)
app.include_router(airlines.router)
app.include_router(pirep.router)
app.include_router(dispatch.router)
app.include_router(wallet.router)
app.include_router(wallet.wallet_router)
app.include_router(va_shop.router)
app.include_router(bidding.router)
app.include_router(achievements.router)
app.include_router(market.router)
app.include_router(incidents.router)
app.include_router(archive.router)
app.include_router(archive.admin_router)
app.include_router(perf.router)
app.include_router(shop.router)
app.include_router(shop_admin_router)
app.include_router(uploads.router)
app.include_router(pet.router)
app.include_router(admin.router)

# ---- 本地上传文件托管，/uploads/*，与 API 同源，前端可直接作为图片地址----
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# ---- 统一错误格式：与前端约定 { error: "..." } ----

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0]["msg"] if exc.errors() else "参数错误"
    return JSONResponse(status_code=400, content={"error": first})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import traceback

    traceback.print_exc()
    return JSONResponse(status_code=500, content={"error": "服务器内部错误"})


# ---- 生产模式：直接托管 frontend/dist，存在即启用 ----
#
# 前端构建产物由后端同源提供，无需 Nginx 也无需 CORS；
# dist 不存在，纯后端开发时此段完全不生效。
#
# 安全头说明：middleware 给所有响应附带最严格 CSP，default-src 'none'，
# 那对 JSON 无碍；但 HTML 文档必须用下面这套站点 CSP 放行自身静态资源。
# 人机验证已改成同源自研 PoW，Worker 由本站打包产物加载，不再需要任何第三方来源。
SPA_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
HTML_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    # media-src 需要 blob:：桌宠动画走「fetch 整文件 → blob → <video>」加载
    #直连 src 流式加载在部分网络下会 stall，见交接文档 §35.9。
    # blob 只能由同源页面自己创建，放开它不引入任何第三方来源。
    "media-src 'self' blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    # 工作量证明跑在 Web Worker 里，Vite 打包后是同源独立文件；部分浏览器
    # 走 blob: 创建 Worker，这里一并放行，仍只限本站来源。
    "worker-src 'self' blob:; "
    "frame-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)

if SPA_DIST.is_dir():
    if (SPA_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=SPA_DIST / "assets"), name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # 同步 def：体内只有路径解析 / is_file / FileResponse，没有任何 await。
        # 写成 async def 会让这些同步 I/O 在事件循环里执行，而它处理的是**每一次前端页面请求**
        # —— 由 tests/test_route_execution_model.py 的守卫测试抓出。改成 def 后自动进入线程池。
        # 未匹配到的 /api/* 仍返回 JSON 404，而不是把前端首页吐回去
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        candidate = (SPA_DIST / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(SPA_DIST):
            return FileResponse(candidate)
        # SPA history 路由回退：/airlines/1、/va/CTY、/admin/... 全部交回前端路由
        return FileResponse(
            SPA_DIST / "index.html",
            headers={"Cache-Control": "no-cache", "content-security-policy": HTML_CSP},
        )

    print(f"[spa] 已托管前端构建产物: {SPA_DIST}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
