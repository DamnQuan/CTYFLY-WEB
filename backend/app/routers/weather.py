"""航情 API：METAR / TAF 多源代理。

上游链，并发竞速，任一成功即返回，全部失败才报错：
  METAR: aviationweather.gov JSON → metar.vatsim.net 文本
         → NOAA tgftp 文本 → aviationweather.gov raw 文本
         → CheckWX 需 key / AVWX 需 key，若在 .env 配置
  TAF: aviationweather.gov JSON → NOAA tgftp 文本
         → aviationweather.gov raw 文本 → CheckWX 需 key / AVWX 需 key，若配置

为什么要多源：aviationweather.gov 是国内访问最不稳的一个，此前是唯一数据源，
它一超时整个「航情查询」就没法用。文本备用源，VATSIM / NOAA 走不同主机与线路。
CheckWX / AVWX 需要免费注册的 key，在 backend/.env 配置 CHECKWX_API_KEY / AVWX_TOKEN
即自动加入竞速；不配置则完全不参与，绝不因为缺 key 而报错。
"""
import asyncio
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..config import AVWX_TOKEN, CHECKWX_API_KEY
from ..deps import require_auth

router = APIRouter(prefix="/api/weather", tags=["weather"])

ICAO_RE = re.compile(r"^[A-Za-z]{4}$")
UA = {"User-Agent": "CTYFly-Web/1.0 (flight control community site)"}

AV_BASE = "https://aviationweather.gov/api/data"
VATSIM_METAR = "https://metar.vatsim.net/{ids}"
NOAA_METAR = "https://tgftp.nws.noaa.gov/data/observations/metar/stations/{icao}.TXT"
NOAA_TAF = "https://tgftp.nws.noaa.gov/data/forecasts/taf/stations/{icao}.TXT"
CHECKWX_BASE = "https://api.checkwx.com"
AVWX_BASE = "https://avwx.rest/api"


def _validate_ids(ids: str) -> list[str]:
    parts = [p for p in re.split(r"[,\s]+", ids.strip().upper()) if p]
    if not parts or not all(ICAO_RE.match(p) for p in parts):
        raise HTTPException(400, "请输入 4 位 ICAO 机场代码，多个用逗号分隔，如 ZSPD,ZBAA")
    return parts


def _simplify(rows: list[dict]) -> list[dict]:
    """统一成前端使用的结构。

    注意字段大小写：aviationweather 的 TAF JSON 是 rawTAF，大写 TAF 和
    issueTime/validTimeFrom，此前取的是 rawTaf/validTime —— TAF 因此一直
    只显示「无报文内容」，这也是用户反馈「taf 查不到」的另一个原因。
    """
    out = []
    for r in rows:
        raw = r.get("rawOb") or r.get("rawTAF") or r.get("rawTaf") or ""
        if not raw:
            continue
        out.append({
            "icaoId": r.get("icaoId") or r.get("site"),
            "reportTime": r.get("reportTime") or r.get("validTime")
            or r.get("issueTime") or _fmt_epoch(r.get("validTimeFrom")) or "",
            "rawOb": raw,
            "lat": r.get("lat"),
            "lon": r.get("lon"),
            "elevationM": r.get("elev") or r.get("elevationM"),
            "name": r.get("name") or "",
        })
    return out


def _fmt_epoch(v) -> str:
    if not isinstance(v, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _latest_per_station(rows: list[dict]) -> list[dict]:
    """上游按时间倒序返回历史报文，这里每个机场只保留最新一条"""
    seen: set = set()
    latest: list[dict] = []
    for r in rows:
        key = r.get("icaoId") or r.get("site")
        if key in seen:
            continue
        seen.add(key)
        latest.append(r)
    return latest


# ---------- 各数据源 ----------

async def _get_json(url: str, params: dict) -> list:
    async with httpx.AsyncClient(timeout=6, trust_env=True) as client:
        resp = await client.get(url, params=params, headers=UA)
        resp.raise_for_status()
        data = resp.json()
    return data if isinstance(data, list) else []


async def _get_text(url: str, params: dict | None = None) -> str:
    async with httpx.AsyncClient(timeout=6, trust_env=True) as client:
        resp = await client.get(url, params=params, headers=UA)
        resp.raise_for_status()
        return resp.text


async def _src_av(path: str, ids: list[str], hours: str | None) -> list[dict]:
    """aviationweather.gov 官方 JSON，含经纬度/海拔等结构化字段。

    出错抛异常，让 _race 能区分「源挂了」和「没数据」；
    上游正常应答但没这个机场时返回 []。
    """
    params: dict = {"ids": ",".join(ids), "format": "json"}
    if hours:
        params["hours"] = hours
    return await _get_json(f"{AV_BASE}/{path}", params)


def _parse_plain_reports(text: str, ids: list[str], kind: str) -> list[dict] | None:
    """把纯文本报文解析成与 aviationweather 相同的结构。

    tgftp 的 METAR 是「日期行 + 报文行」成对出现；
    tgftp 的 TAF 是日期行后跟多行报文，BECMG / TEMPO 等续行，
    所以 TAF 要把同一机场的续行合并进同一条报文。
    VATSIM 的 metar.vatsim.net 则一行一条。
    """
    wanted = set(ids)
    reports: list[dict] = []
    station_date = ""
    current: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 日期行：2026/09/19 02:30 或 2026.09.19 0230 UTC
        if re.match(r"^\d{4}[/.]\d{2}[/.]\d{2}", line) and " " in line:
            station_date = line
            continue
        # 报文行：以 4 位 ICAO 开头，TAF 报文可能带 TAF 前缀
        m = re.match(r"^(?:TAF\s+)?([A-Z]{4})\b(.*)$", line)
        if m and m.group(1) in wanted:
            icao = m.group(1)
            body = m.group(1) + " " + m.group(2).strip()
            current = {
                "icaoId": icao,
                "reportTime": station_date,
                "rawOb": body.replace("=", "").strip(),
                "kind": kind,
            }
            reports.append(current)
            continue
        # 续行，TAF 的 BECMG / TEMPO / PROB 等：并进当前报文
        if current is not None and not line.startswith("="):
            current["rawOb"] = (current["rawOb"] + " " + line.replace("=", "")).strip()

    return reports or None


async def _src_vatsim_metar(ids: list[str]) -> list[dict]:
    """VATSIM 的 METAR 文本服务，免费无需 key，国内可达性远好于 NOAA 官网"""
    text = await _get_text(VATSIM_METAR.format(ids=",".join(ids)))
    return _parse_plain_reports(text, ids, "metar") or []


async def _src_noaa(kind: str, ids: list[str]) -> list[dict]:
    """NOAA tgftp 的纯文本报文，每个机场一个 URL，并发抓取。

    只要有一个机场抓取失败就抛错 —— 否则部分失败会被当成「全部没数据」。
    """
    url_tpl = NOAA_TAF if kind == "taf" else NOAA_METAR

    async def one(icao: str) -> dict:
        text = await _get_text(url_tpl.format(icao=icao))
        parsed = _parse_plain_reports(text, [icao], kind)
        if not parsed:
            raise ValueError(f"{icao} 无报文")
        return parsed[0]

    results = await asyncio.gather(*(one(i) for i in ids))
    return list(results)


async def _src_av_raw(kind: str, ids: list[str]) -> list[dict]:
    """aviationweather 的 raw 文本端点。

    与 JSON 端点同主机，不增加线路多样性，但走的是不同的响应格式 ——
    JSON 解析出问题，如上游字段变更时它仍可能可用。
    """
    text = await _get_text(f"{AV_BASE}/{kind}", {"ids": ",".join(ids), "format": "raw"})
    return _parse_plain_reports(text, ids, kind) or []


async def _src_checkwx(kind: str, ids: list[str]) -> list[dict]:
    """CheckWX，免费 key：一次请求可查多机场，返回 raw 报文数组"""
    path = "taf" if kind == "taf" else "metar"
    async with httpx.AsyncClient(timeout=6, trust_env=True) as client:
        resp = await client.get(
            f"{CHECKWX_BASE}/{path}/{','.join(ids)}/raw",
            headers={"X-API-Key": CHECKWX_API_KEY, **UA},
        )
        resp.raise_for_status()
        data = resp.json()
    rows: list[dict] = []
    for raw in (data.get("data") or []):
        raw = (raw or "").strip()
        m = re.match(r"^(?:TAF\s+|METAR\s+)?([A-Z]{4})\b", raw)
        if not m:
            continue
        rows.append({"icaoId": m.group(1), "rawOb": raw, "reportTime": "", "kind": kind})
    return rows


async def _src_avwx(kind: str, ids: list[str]) -> list[dict]:
    """AVWX，免费 token：一次一个机场，并发抓取"""
    path = "taf" if kind == "taf" else "metar"

    async def one(icao: str) -> dict | None:
        async with httpx.AsyncClient(timeout=6, trust_env=True) as client:
            resp = await client.get(
                f"{AVWX_BASE}/{path}/{icao}",
                headers={"Authorization": AVWX_TOKEN, **UA},
            )
            resp.raise_for_status()
            data = resp.json()
        raw = (data.get("raw") or "").strip()
        if not raw:
            return None
        m = re.match(r"^(?:TAF\s+|METAR\s+)?([A-Z]{4})\b", raw)
        return {"icaoId": m.group(1) if m else icao, "rawOb": raw,
                "reportTime": data.get("time", {}).get("dt", "") or "", "kind": kind}

    results = await asyncio.gather(*(one(i) for i in ids))
    return [r for r in results if r]


# ---------- 多源竞速，合并模式 ----------

async def _race_merge(coros: list, wanted: set) -> tuple[list[dict], bool]:
    """并发请求所有源，按机场合并结果，直到覆盖全部请求机场或所有源结束。

    为什么要合并而不是「任一源成功即返回」：
      第一源，aviationweather 对多机场批量查询常只返回其中常见机场的报文，
      若立即采纳并取消其余源，ZULS 这类不常见机场的报文就永远查不到
      用户实测：单查 ZULS 能查到，多机场一起查 ZULS 就消失。

    返回 数据, 是否有源失败：
      - merged 覆盖了全部请求机场 → 提前结束
      - 所有源结束仍未覆盖 → 返回已合并的部分，让前端提示哪些机场缺失
    """
    if not coros:
        raise HTTPException(502, "气象数据源暂时不可用，请稍后重试")

    pending = {asyncio.ensure_future(c): i for i, c in enumerate(coros)}
    merged: dict[str, dict] = {}
    order: list[str] = []
    last_error = ""
    failed_sources = 0
    source_count = len(coros)

    def absorb(result: list) -> None:
        for row in result or []:
            key = row.get("icaoId") or row.get("site")
            if key and key not in merged:
                merged[key] = row
                order.append(key)

    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for fut in done:
                try:
                    result = fut.result()
                except Exception as exc:    # 源自身抛错，超时/5xx，记录后继续等其它源
                    last_error = str(exc)[:120]
                    failed_sources += 1
                    continue
                absorb(result)
            if wanted and wanted.issubset(merged.keys()):
                break   # 全部请求机场都有数据了，提前收工
    finally:
        # 收掉输掉的竞速任务：取消并显式消费异常，
        # 否则 asyncio 会在日志里刷「exception was never retrieved」
        for fut in pending:
            fut.cancel()
        if pending:
            _, left = await asyncio.wait(pending)
            for fut in left:
                if fut.done() and not fut.cancelled():
                    fut.exception()         # 显式取回，消掉告警

    rows = [merged[k] for k in order]
    degraded = failed_sources > 0 or (wanted and not wanted.issubset(merged.keys()))
    if not rows and failed_sources == source_count:
        raise HTTPException(502, f"气象数据源暂时不可用，请稍后重试{('（' + last_error + '）') if last_error else ''}")
    return rows, degraded


def _keyed_sources(kind: str, ids: list[str]) -> list:
    """需要 key 的增强源：配置了才加入竞速，绝不因为缺 key 而报错"""
    out = []
    if CHECKWX_API_KEY:
        out.append(_src_checkwx(kind, ids))
    if AVWX_TOKEN:
        out.append(_src_avwx(kind, ids))
    return out


async def fetch_metar(ids: list[str]) -> tuple[list[dict], bool]:
    return await _race_merge([
        _src_av("metar", ids, "3"),
        _src_vatsim_metar(ids),
        _src_noaa("metar", ids),
        _src_av_raw("metar", ids),
        *_keyed_sources("metar", ids),
    ], set(ids))


async def fetch_taf(ids: list[str]) -> tuple[list[dict], bool]:
    return await _race_merge([
        _src_av("taf", ids, None),
        _src_noaa("taf", ids),
        _src_av_raw("taf", ids),
        *_keyed_sources("taf", ids),
    ], set(ids))


@router.get("/metar")
async def metar(ids: str = "", user: dict = Depends(require_auth)):
    icao_list = _validate_ids(ids)
    rows, _degraded = await fetch_metar(icao_list)
    return {"ok": True, "reports": _simplify(_latest_per_station(rows))}


@router.get("/taf")
async def taf(ids: str = "", user: dict = Depends(require_auth)):
    icao_list = _validate_ids(ids)
    rows, _degraded = await fetch_taf(icao_list)
    return {"ok": True, "reports": _simplify(_latest_per_station(rows))}
