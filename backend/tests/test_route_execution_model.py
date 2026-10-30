"""路由执行模型守卫：async 路由体内不得出现同步阻塞，即必须含 await

为什么值得有：站长评审指出「SQLite 同步调用直接跑在 async 路由里会阻塞事件循环」。
FastAPI 对**同步 def** 路由会用 run_in_threadpool 执行，所以纯 DB 处理器应当是 sync def；
只有真的需要 await，人机验证、httpx、邮件、文件读取的路由才该是 async def。

2026-10-11 已把 152 个「async 且无 await」的处理器改回同步 def。本测试锁住这个模型：
以后新写的路由如果误用 `async def` 却只做同步 DB 操作，CI 会直接报出来。
"""
import ast
import inspect
import textwrap

import pytest


def route_handlers():
    """ 端点函数, HTTP 方法, 路径 —— 从各 router 对象自身收集

    为什么不再遍历 app.routes：**fastapi 0.141.1，锁定/生产版本把 include_router 变成惰性的
    `_IncludedRouter`**，app.routes 里看到的是这些包装对象、拿不到 endpoint；
    而旧版 fastapi 会当场展开成 APIRoute。这个差异导致同一套测试「本地旧版全绿、
    CI，按 lock 装生产版本全红」—— 2026-10-16 的真实事故。
    改为直接读 router 对象，它们始终持有 APIRoute，与 FastAPI 版本无关。
    """
    import importlib

    from fastapi import APIRouter

    import app.main  # noqa: F401  —— 先触发全部 router 模块被导入

    modules = (
        "admin", "airlines", "applications", "auth", "captcha", "dispatch", "events", "misc",
        "navdata", "pet", "pirep", "shop", "survey", "tickets", "uploads", "va_shop", "wallet",
        "weather",
    )
    for name in modules:
        mod = importlib.import_module(f"app.routers.{name}")
        for attr in vars(mod).values():
            if not isinstance(attr, APIRouter):
                continue
            for r in attr.routes:
                ep = getattr(r, "endpoint", None)
                methods = sorted(getattr(r, "methods", None) or [])
                if ep is None or not callable(ep) or not methods:
                    continue
                yield ep, methods, getattr(r, "path", "?")


def has_await(source: str) -> bool:
    # 嵌套函数，如 SPA 回退的源码带原始缩进，必须先 dedent 再解析
    tree = ast.parse(textwrap.dedent(source))
    return any(isinstance(n, (ast.Await, ast.AsyncWith, ast.AsyncFor)) for n in ast.walk(tree))


async_routes = []
for ep, methods, path in route_handlers():
    if inspect.iscoroutinefunction(ep):
        async_routes.append((ep, methods, path))


@pytest.mark.parametrize("ep,methods,path", async_routes,
                         ids=[f"{'/'.join(m)} {p} ({e.__module__}.{e.__name__})"
                              for e, m, p in async_routes])
def test_async_routes_must_await(ep, methods, path):
    src = inspect.getsource(ep)
    assert has_await(src), (
        f"{path} 是 async 路由但体内没有任何 await —— 同步 DB 操作在 async 路由里会阻塞事件循环。"
        f"如果它只做同步 DB 操作，请改成同步 def（FastAPI 会自动放进线程池）。"
    )


def test_db_heavy_modules_are_synchronous():
    """纯 DB 模块的路由应全部是同步 def，这些模块里没有任何 await 需求"""
    db_only_modules = {
        "app.routers.wallet", "app.routers.pirep", "app.routers.dispatch",
        "app.routers.va_shop", "app.routers.shop",
    }
    seen = {}
    for ep, _methods, _path in route_handlers():
        if ep.__module__ in db_only_modules:
            seen.setdefault(ep.__module__, []).append((ep.__name__, inspect.iscoroutinefunction(ep)))

    assert seen, "未找到这些模块的路由（模块名或注册方式变了？）"
    bad = [f"{mod}.{name}" for mod, items in seen.items() for name, is_async in items if is_async]
    assert not bad, f"这些纯 DB 路由仍是 async def（会阻塞事件循环）：{bad}"


def test_sync_routes_are_actually_being_used():
    """确认同步化改造确实生效，而不是所有路由又变回 async"""
    handlers = list(route_handlers())
    assert len(handlers) >= 150, f"只收集到 {len(handlers)} 个路由（预期 ≥150），收集方式可能失效了"
    sync = sum(1 for ep, _m, _p in handlers if not inspect.iscoroutinefunction(ep))
    assert sync >= 100, f"同步路由只有 {sync} 个，改造可能被回退了（预期 ≥100）"
