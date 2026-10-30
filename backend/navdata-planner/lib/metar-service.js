const METAR_ENDPOINT = 'https://weather.api.skylitefly.com/api/icao';
const METAR_FALLBACK = 'https://aviationweather.gov/api/data/metar';
const CACHE_TTL_MS = 5 * 60 * 1000; // 成功结果缓存 5 分钟
const FAIL_CACHE_TTL_MS = 30 * 1000; // 失败结果只缓存 30 秒，允许快速重试
const REQUEST_TIMEOUT_MS = 7000;

class MetarService {
  constructor(options = {}) {
    this.fetch = options.fetch || globalThis.fetch;
    this.endpoint = options.endpoint || METAR_ENDPOINT;
    this.fallbackEndpoint = options.fallbackEndpoint || METAR_FALLBACK;
    this.cache = new Map();
  }

  async get(icao) {
    const station = String(icao || '').trim().toUpperCase();
    const cached = this.cache.get(station);
    if (cached) {
      const ttl = cached.value?.available ? CACHE_TTL_MS : FAIL_CACHE_TTL_MS;
      if (Date.now() - cached.time < ttl) return cached.value;
    }

    let value = null;
    let noReport = false;
    try {
      value = await this.fetchPrimary(station);
      if (!value) noReport = true;
    } catch {
      /* 主源不可用，尝试备选 */
    }
    if (!value) {
      try {
        value = await this.fetchFallback(station);
        if (!value) noReport = true;
      } catch {
        /* 备选也不可用 */
      }
    }
    if (!value) value = unavailable(station, noReport ? '当前没有可用的 METAR 报文' : 'METAR 服务暂时不可用');
    this.cache.set(station, { time: Date.now(), value });
    return value;
  }

  async fetchPrimary(station) {
    const url = `${this.endpoint}/${encodeURIComponent(station)}/`;
    const response = await this.fetch(url, {
      headers: { 'User-Agent': 'IFR-Route-Planner/0.1' },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    });
    if (!response.ok) throw new Error(`Weather provider returned ${response.status}`);
    const payload = await response.json();
    if (payload?.success && payload?.data?.metar) return normalizeReport(station, payload.data);
    return null; // 服务正常但无报文
  }

  async fetchFallback(station) {
    const url = `${this.fallbackEndpoint}?ids=${encodeURIComponent(station)}&format=json&taf=false`;
    const response = await this.fetch(url, {
      headers: { 'User-Agent': 'IFR-Route-Planner/0.1' },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    });
    if (!response.ok) throw new Error(`Fallback weather provider returned ${response.status}`);
    const payload = await response.json();
    const item = Array.isArray(payload) ? payload[0] : null;
    if (item?.rawOb) return normalizeReport(station, item);
    return null;
  }
}

function normalizeReport(station, report) {
  const raw = report.metar || report.rawOb || report.raw || '';
  const wind = raw.match(/\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(MPS|KT)\b/);
  const temperature = raw.match(/\b(M?\d{2})\/(M?\d{2})\b/);
  const altimeter = raw.match(/\bQ(\d{4})\b/);
  const multiplier = wind?.[4] === 'MPS' ? 1.94384 : 1;
  return {
    station,
    available: true,
    raw,
    taf: report.taf || null,
    observedAt: report.reportTime || report.obsTime || null,
    flightCategory: report.fltCat || null,
    windDirection: wind ? (wind[1] === 'VRB' ? null : Number(wind[1])) : numberOrNull(report.wdir),
    windSpeed: wind ? Math.round(Number(wind[2]) * multiplier) : numberOrNull(report.wspd),
    windGust: wind?.[3] ? Math.round(Number(wind[3]) * multiplier) : numberOrNull(report.wgst),
    windUnit: wind ? (wind[4] === 'MPS' ? 'm/s' : 'kt') : null,
    windSpeedRaw: wind ? Number(wind[2]) : null,
    windGustRaw: wind?.[3] ? Number(wind[3]) : null,
    visibility: report.visib ?? null,
    temperature: temperature ? parseSignedMetarNumber(temperature[1]) : numberOrNull(report.temp),
    dewpoint: temperature ? parseSignedMetarNumber(temperature[2]) : numberOrNull(report.dewp),
    altimeter: altimeter ? Number(altimeter[1]) : numberOrNull(report.altim)
  };
}

function parseSignedMetarNumber(value) {
  return value.startsWith('M') ? -Number(value.slice(1)) : Number(value);
}

function unavailable(station, message) {
  return { station, available: false, message };
}

function numberOrNull(value) {
  return value === null || value === undefined || value === '' ? null : Number(value);
}

/**
 * 计算相对跑道航向的顺/逆风与侧风分量。
 * 风向与跑道航向均为真角；headwind>0 为逆风，<0 为顺风；crossFrom R=右侧风，L=左侧风。
 */
function computeWindComponents(windDirection, windSpeed, runwayHeading) {
  if (windDirection == null || windSpeed == null || windDirection === 'VRB') return null;
  const rad = ((Number(windDirection) - Number(runwayHeading)) * Math.PI) / 180;
  const headwind = Number(windSpeed) * Math.cos(rad);
  const crosswind = Number(windSpeed) * Math.sin(rad);
  return { headwind, crosswind, crossFrom: crosswind >= 0 ? 'R' : 'L' };
}

module.exports = { MetarService, normalizeReport, computeWindComponents };