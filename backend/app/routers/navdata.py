"""航路规划 sidecar，Node 版 A* 规划器的托管与 JSON 代理，
以及机场地面图，Airport GIS 矢量数据查询。

sidecar 即 backend/navdata-planner/server.js：读取 AIRAC nd.db3，
后端启动时预热拉起，首次访问时若未就绪则等待；规划结果做进程内缓存。

机场地面图：backend/data/airport-gis/airports/<ICAO>/*.geojson
X-Plane 机场场景 GIS 数据：跑道/滑行道/机坪/停机位/标志牌/灯光等 47 层，
按请求读取合并返回，带内存缓存；不依赖 sidecar。
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..config import NAVDATA_DB, NAVDATA_SIDECAR_DIR, NAVDATA_SIDECAR_URL
from ..deps import require_auth
from ..ratelimit import enforce

router = APIRouter(prefix="/api/nav", tags=["navdata"])

_lock = threading.Lock()
_proc: subprocess.Popen | None = None

# 规划结果缓存：AIRAC 数据静态，同一 OD + 程序组合直接复用
_plan_cache: dict[tuple, tuple[float, dict]] = {}
_PLAN_CACHE_TTL = 600
_PLAN_CACHE_MAX = 300


def _sidecar_available_on_disk() -> bool:
    return (NAVDATA_SIDECAR_DIR / "server.js").exists()


def _spawn_sidecar() -> bool:
    """拉起 Node sidecar；返回是否成功启动"""
    global _proc
    if not _sidecar_available_on_disk():
        return False
    env = {**os.environ, "HOST": "127.0.0.1", "PORT": NAVDATA_SIDECAR_URL.rsplit(":", 1)[-1]}
    if NAVDATA_DB:
        env["NAVDATA_DB"] = NAVDATA_DB
    kwargs: dict = {"cwd": str(NAVDATA_SIDECAR_DIR), "env": env}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        _proc = subprocess.Popen(["node", "server.js"], **kwargs)
        return True
    except (OSError, FileNotFoundError):
        return False


async def _wait_healthy(timeout_s: float = 90) -> dict:
    """等待 sidecar 就绪，首次需构建航路图，可能耗时较长"""
    async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
        deadline = asyncio.get_event_loop().time() + timeout_s
        last_err = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(f"{NAVDATA_SIDECAR_URL}/api/status")
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001 - 轮询期间容忍一切连接错误
                last_err = exc
                await asyncio.sleep(1.0)
    # 把最后一次错误带进提示：排障时「超时」和「sidecar 起不来/端口被占」是两回事，
    # 原实现把 last_err 丢了，ruff F841 顶出来的，只能看到笼统的超时
    raise HTTPException(503, f"航路规划服务启动超时，请稍后重试，最后一次错误：{last_err}")


async def ensure_sidecar() -> dict:
    """确保 sidecar 在运行并返回其 status"""
    global _proc
    async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
        try:
            resp = await client.get(f"{NAVDATA_SIDECAR_URL}/api/status")
            resp.raise_for_status()
            return resp.json()
        except Exception:
            pass

    with _lock:
        if _proc is None or _proc.poll() is not None:
            if not _sidecar_available_on_disk():
                raise HTTPException(
                    503, "航路规划服务未安装，缺少 navdata-planner 目录"
                )
            if not _spawn_sidecar():
                raise HTTPException(
                    503, "无法启动航路规划服务，请确认服务器已安装 Node.js"
                )
    return await _wait_healthy()


async def proxy_get(path: str, params: dict | None = None) -> dict:
    await ensure_sidecar()
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=120) as client:
            resp = await client.get(f"{NAVDATA_SIDECAR_URL}{path}", params=params)
    except httpx.TimeoutException:
        raise HTTPException(504, "航路计算超时，请稍后重试")
    except Exception:
        raise HTTPException(503, "航路规划服务暂时不可用")
    return _relay(resp)


async def proxy_post(path: str, payload: dict) -> dict:
    await ensure_sidecar()
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=120) as client:
            resp = await client.post(f"{NAVDATA_SIDECAR_URL}{path}", json=payload)
    except httpx.TimeoutException:
        raise HTTPException(504, "航路计算超时，请稍后重试")
    except Exception:
        raise HTTPException(503, "航路规划服务暂时不可用")
    return _relay(resp)


def _relay(resp: httpx.Response) -> dict:
    """sidecar 的业务错误，{error: ...}按原状态码透传"""
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", "航路规划请求失败")
        except Exception:
            detail = "航路规划请求失败"
        raise HTTPException(resp.status_code, detail)
    return resp.json()


def _norm_airport(r: dict) -> dict:
    """sidecar 的 SQLite 行使用大写列名，ICAO/Name/...，统一为前端使用的小写键"""
    return {
        "icao": r.get("ICAO") or r.get("icao") or "",
        "name": r.get("Name") or r.get("name") or "",
        "lat": r.get("Latitude", r.get("lat")),
        "lon": r.get("Longtitude", r.get("lon")),
        "elevation": r.get("Elevation", r.get("elevation")),
    }


def warm_start() -> None:
    """后端启动时后台预热：立即拉起 sidecar 并等待建图完成，用户首次查询即秒回"""
    if not _sidecar_available_on_disk():
        return

    def _run():
        try:
            if not _spawn_sidecar():
                return
            deadline = time.time() + 120
            while time.time() < deadline:
                try:
                    urllib.request.urlopen(f"{NAVDATA_SIDECAR_URL}/api/status", timeout=2)
                    print("[navdata] sidecar 已预热就绪")
                    return
                except Exception:
                    time.sleep(1)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True, name="navdata-warmup").start()


@router.get("/status")
async def nav_status(user: dict = Depends(require_auth)):
    return await ensure_sidecar()


@router.get("/airports")
async def nav_airports(request: Request, q: str = "", user: dict = Depends(require_auth)):
    enforce(request, "navsearch", 120, 60)
    q = q.strip()[:32]
    if not q:
        return {"airports": []}
    data = await proxy_get("/api/airports", {"q": q})
    return {"airports": [_norm_airport(a) for a in data.get("airports", [])]}


@router.get("/airports/{icao}/details")
async def nav_airport_details(request: Request, icao: str, user: dict = Depends(require_auth)):
    enforce(request, "navdetails", 60, 60)
    icao = icao.strip().upper()[:4]
    data = await proxy_get(f"/api/airports/{icao}/details")
    if isinstance(data.get("airport"), dict):
        data["airport"] = _norm_airport(data["airport"])
    return data


class PlanBody(BaseModel):
    origin: str = Field("", max_length=4)
    destination: str = Field("", max_length=4)
    originRunway: str | None = Field(None, max_length=8)
    destinationRunway: str | None = Field(None, max_length=8)
    sid: str | None = Field(None, max_length=16)
    star: str | None = Field(None, max_length=16)


@router.post("/routes/plan")
async def nav_plan(body: PlanBody, request: Request, user: dict = Depends(require_auth)):
    enforce(request, "navplan", 20, 60)
    key = (body.origin, body.destination, body.sid or "", body.star or "")
    now = time.time()
    hit = _plan_cache.get(key)
    if hit and now - hit[0] < _PLAN_CACHE_TTL:
        return hit[1]

    data = await proxy_post("/api/routes", body.model_dump(exclude_none=True))

    if len(_plan_cache) >= _PLAN_CACHE_MAX:
        oldest = min(_plan_cache, key=lambda k: _plan_cache[k][0])
        _plan_cache.pop(oldest, None)
    _plan_cache[key] = (now, data)
    return data


class AnalyzeBody(BaseModel):
    route: str = Field("", max_length=1000)
    origin: str | None = Field(None, max_length=4)
    destination: str | None = Field(None, max_length=4)


@router.post("/routes/analyze")
async def nav_analyze(body: AnalyzeBody, request: Request, user: dict = Depends(require_auth)):
    enforce(request, "navanalyze", 30, 60)
    return await proxy_post("/api/routes/analyze", body.model_dump(exclude_none=True))


# ---------- 机场地面图，Airport GIS 矢量数据查询 ----------

from pathlib import Path as _Path

_GIS_DIR = _Path(__file__).resolve().parent.parent.parent / "data" / "airport-gis" / "airports"
_gis_list_cache: dict = {"at": 0.0, "items": None}
_gis_data_cache: "dict[str, tuple[float, dict]]" = {}
_GIS_CACHE_MAX = 8
_GIS_LOCK = threading.Lock()


def _gis_dir():
    return _Path(os.environ.get("AIRPORT_GIS_DIR", str(_GIS_DIR)))


@router.get("/fuel-estimate")
def fuel_estimate(request: Request, type: str, dist: float, fl: int = 0, pax: int = 0,
                        cargo: int = 0, intl: int = 0, user: dict = Depends(require_auth)):
    """签派自动油量估算，OpenAP 燃油模型 + 国内/国际备用油规章，机型不在库时返回 ok=False"""
    enforce(request, "fuel", 60, 3600)
    ac = type.strip().upper()[:4]
    # fl 限幅：OpenAP 的燃油模型只对合理巡航高度层有效，超出范围的 fl 会让
    # 计算异常放大，耗时长/结果离谱；clamp 到 50-450，FL050–FL450
    fl = max(50, min(int(fl), 450))
    from ..fuel import estimate_fuel
    from .airlines import FLEET_CATALOG
    spec = FLEET_CATALOG.get(ac, {})
    oew = spec.get("oew", 40000)
    payload = max(0, pax) * 95 + max(0, cargo)
    res = estimate_fuel(ac, max(0, dist), payload, oew, fl, intl=bool(intl))
    if res is None:
        return {"ok": False, "reason": f"机型 {ac} 不在 OpenAP 性能数据库中，请手动填写油量"}
    return {"ok": True, **res}


@router.get("/runways/{icao}")
async def nav_runways(icao: str, request: Request, user: dict = Depends(require_auth)):
    """机场跑道列表，签派表单的跑道选择标签用"""
    enforce(request, "navrunways", 60, 60)
    icao = icao.strip().upper()[:4]
    data = await proxy_get(f"/api/airports/{icao}/runways")
    return data


@router.get("/ground-map/airports")
def ground_map_airports(request: Request, user: dict = Depends(require_auth)):
    """可用地机场地面图列表，目录扫描，5 分钟缓存"""
    d = _gis_dir()
    now = time.time()
    with _GIS_LOCK:
        if now - _gis_list_cache["at"] > 300 or _gis_list_cache["items"] is None:
            items = []
            if d.is_dir():
                for entry in d.iterdir():
                    if entry.is_dir() and len(entry.name) == 4 and entry.name.isalnum():
                        items.append(entry.name)
            items.sort()
            _gis_list_cache["at"] = now
            _gis_list_cache["items"] = items
    return {"ok": True, "airports": _gis_list_cache["items"]}


@router.get("/ground-map/{icao}")
def ground_map_data(icao: str, request: Request, user: dict = Depends(require_auth)):
    """机场地面图数据：合并该机场全部 GeoJSON 图层"""
    enforce(request, "gismap", 60, 3600)
    icao = icao.strip().upper()[:4]
    if not (icao.isalnum() and len(icao) == 4):
        raise HTTPException(400, "ICAO 格式无效")
    d = _gis_dir() / icao
    if not d.is_dir():
        raise HTTPException(404, "该机场暂无地面图数据")

    sig = str(max((f.stat().st_mtime for f in d.glob('*.geojson')), default=0))
    with _GIS_LOCK:
        cached = _gis_data_cache.get(icao)
        if cached and cached[0] == sig:
            return cached[1]

    layers: dict = {}
    try:
        for f in sorted(d.glob("*.geojson")):
            name = f.stem
            try:
                layers[name] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
    except Exception:
        raise HTTPException(500, "地面图数据读取失败")

    manifest = None
    mf = d / "manifest.json"
    if mf.is_file():
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            manifest = None

    payload = {"ok": True, "icao": icao, "layers": layers, "manifest": manifest}
    with _GIS_LOCK:
        _gis_data_cache[icao] = (sig, payload)
    return payload
