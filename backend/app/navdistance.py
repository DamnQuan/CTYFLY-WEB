"""从 AIRAC nd.db3 读取机场坐标，计算大圆距离，NM。
只读访问，进程内缓存结果；导航数据不可用时返回 None，工资自动跳过距离补贴。
"""
import math
import sqlite3
import threading
from pathlib import Path

from .config import NAVDATA_DB, NAVDATA_SIDECAR_DIR

R_NM = 3440.065  # 地球半径，海里

_cache: dict[tuple, float | None] = {}
_lock = threading.Lock()


def _resolve_db() -> Path | None:
    if NAVDATA_DB:
        p = Path(NAVDATA_DB)
        return p if p.exists() else None
    p = Path(NAVDATA_SIDECAR_DIR) / "Navdata" / "nd.db3"
    return p if p.exists() else None


def _haversine_nm(c1, c2) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (c1[0], c1[1], c2[0], c2[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(a))


def airport_distance_nm(dep: str, arr: str) -> float | None:
    """返回两机场大圆距离，NM，数据不可用或机场不存在时返回 None"""
    dep, arr = dep.upper(), arr.upper()
    if dep == arr:
        return 0.0
    key = (dep, arr)
    with _lock:
        if key in _cache:
            return _cache[key]

    db = _resolve_db()
    if not db:
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        rows = conn.execute(
            "SELECT ICAO, Latitude, Longtitude FROM Airports WHERE ICAO IN (?, ?)",
            (dep, arr),
        ).fetchall()
        conn.close()
    except Exception:
        return None

    coords = {r[0]: (r[1], r[2]) for r in rows if r[1] is not None and r[2] is not None}
    if dep not in coords or arr not in coords:
        result = None
    else:
        result = round(_haversine_nm(coords[dep], coords[arr]), 1)

    with _lock:
        _cache[key] = result
        _cache[(arr, dep)] = result
    return result
