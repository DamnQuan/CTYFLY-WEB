"""OpenAP 油量估算：签派自动油量，爬升/巡航/下降分段积分 + 规章备用油。

备用油规则，参照 CCAR-121 部简化模型：
- 国内航班：最终储备 = 45 分钟巡航等待油
- 国际航班：最终储备 = 30 分钟等待油 + 航程油 5% contingency

依赖 openap 包，pip install openap；机型不在 OpenAP 数据库时返回 None，
前端据此提示"暂无自动油量模型"，不影响签派流程。
"""
try:
    import openap
    _OPENAP = True
except Exception:  # ImportError 及其内部依赖缺失
    _OPENAP = False

_ff_cache: dict = {}

# 巡航 TAS 估算，kt：涡桨与喷气差异大，按机型族区分
_TAS_JET = 445
_TAS_TP = 265

_TP_PREFIX = ("AT4", "AT7", "ATR", "DH8", "SF3", "E145", "E12", "C208", "B19")

# OpenAP 库不支持、回退到近似母型的机型， neo/衍生型号 → 基础型号
_TYPE_FALLBACK = {
    "A19N": "A319", "A21N": "A321", "A339": "A333", "A35K": "A359",
    "B39M": "B738", "B3XM": "B739", "B78X": "B789", "B77E": "B77W",
}


def _resolve_type(ac: str) -> str | None:
    """机型解析：先原样，再回退到近似母型；都不支持返回 None"""
    try:
        _ff(ac)
        return ac
    except Exception:
        pass
    fallback = _TYPE_FALLBACK.get(ac)
    if fallback:
        try:
            _ff(fallback)
            return fallback
        except Exception:
            return None
    return None


def _is_turboprop(ac: str) -> bool:
    return ac.startswith(_TP_PREFIX)


def _ff(ac: str):
    if ac not in _ff_cache:
        _ff_cache[ac] = openap.FuelFlow(ac)
    return _ff_cache[ac]


def default_fl(distance_nm: float) -> int:
    """按航程给推荐巡航高度层"""
    if distance_nm < 250:
        return 240
    if distance_nm < 550:
        return 300
    if distance_nm < 900:
        return 350
    return 370


def estimate_fuel(ac: str, distance_nm: float, payload_kg: float, oew_kg: float,
                  cruise_fl: int = 0, intl: bool = False) -> dict | None:
    """分段油量估算。返回 {fuel_kg, trip_kg, reserve_kg, cruise_alt_ft, cruise_hours, model} 或 None。"""
    if not _OPENAP or distance_nm <= 0:
        return None
    ac = ac.strip().upper()
    resolved = _resolve_type(ac)
    if not resolved:
        return None
    ff = _ff(resolved)

    tp = _is_turboprop(resolved)
    tas = _TAS_TP if tp else _TAS_JET

    # 巡航高度：签派填了 FL 用之，否则按航程推荐；涡桨压低
    alt_ft = int(cruise_fl) * 100 if cruise_fl else default_fl(distance_nm) * 100
    if tp:
        alt_ft = min(alt_ft, 22000)

    payload = max(0.0, payload_kg)
    # 质量初值：油量猜测按 2400kg/h × 预计航时
    fuel = distance_nm / max(tas, 1) * 2400.0

    mass = oew_kg + payload + fuel
    climb_min = alt_ft / 2000.0                      # 爬升率 2000ft/min
    climb_dist = tas * 0.55 * climb_min / 60.0       # 爬升段 TAS ≈ 55% 巡航
    cruise_dist = max(0.0, distance_nm - climb_dist - 60)  # 下降段约 60nm
    cruise_h = cruise_dist / tas

    for _ in range(3):  # 质量迭代收敛
        try:
            climb_flow = ff.enroute(mass=mass, tas=tas * 0.55, alt=alt_ft / 2, vs=2000)
            cruise_flow = ff.enroute(mass=mass * 0.96, tas=tas, alt=alt_ft, vs=0)
            descent_flow = ff.enroute(mass=mass * 0.9, tas=tas * 0.7, alt=10000, vs=-1500)
        except Exception:
            return None
        climb_fuel = climb_flow * climb_min * 60
        cruise_fuel = cruise_flow * cruise_h * 3600
        descent_fuel = descent_flow * 25 * 60
        trip = climb_fuel + cruise_fuel + descent_fuel
        mass = oew_kg + payload + trip

    # 备用油，规章简化模型：落地质量下的等待油流
    mass_ldg = oew_kg + payload + trip
    try:
        hold_flow = ff.enroute(mass=mass_ldg, tas=tas * 0.6, alt=5000, vs=0)
    except Exception:
        hold_flow = cruise_flow * 0.9 if cruise_flow else 0
    if intl:
        # 国际：30 分钟等待油 + 航程油 5% contingency，CCAR-121 国际规则简化
        reserve = hold_flow * 30 * 60 + trip * 0.05
    else:
        # 国内：45 分钟巡航等待油
        reserve = hold_flow * 45 * 60

    trip = int(round(trip))
    reserve = int(round(reserve))
    return {
        "fuel_kg": trip + reserve,       # 携带燃油 = 航程油 + 备用油
        "trip_kg": trip,
        "reserve_kg": reserve,
        "cruise_alt_ft": alt_ft,
        "cruise_hours": round(cruise_h, 2),
        "intl": intl,
        "model": "OpenAP FuelFlow",
    }
