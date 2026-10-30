const { NavdataRepository } = require('./navdata');
const { planHighIfrRoutes } = require('./router');
const { distanceNM } = require('./geo');
const { computeWindComponents } = require('./metar-service');
const { buildProcedureCandidate, airportPoint } = require('./procedure');
const { analyzeRoute, tokenize } = require('./route-analyzer');

const NO_SID = 'NOSID';
const NO_STAR = 'NOSTAR';

class PlannerService {
  constructor(repositoryOrOptions = {}) {
    this.repository = isRepository(repositoryOrOptions)
      ? repositoryOrOptions
      : new NavdataRepository(repositoryOrOptions.dbPath);
    this.graph = null;
    this.graphNodeIds = null;
    this.cycle = null;
    this.initializedSignature = null;
  }

  initialize() {
    if (this.graph && !this.repository.hasDatabaseChanged?.()) return this.buildStatus();
    if (this.graph && this.repository.hasDatabaseChanged?.()) this.repository.reload();
    this.cycle = this.repository.getCycleInfo();
    this.graph = this.repository.loadHighAirwayGraph();
    this.graphNodeIds = new Set(this.graph.nodes.keys());
    this.initializedSignature = this.repository.fileSignature || null;
    return this.buildStatus();
  }

  getStatus() {
    this.initialize();
    return this.buildStatus();
  }

  buildStatus() {
    return {
      cycle: this.cycle?.CycleName || this.cycle?.cycle || 'Unknown',
      cycleStartDate: this.cycle?.CycleStartDate || null,
      cycleEndDate: this.cycle?.CycleEndDate || null,
      waypointCount: this.graph?.nodes.size || 0,
      airwayLegCount: this.graph?.edgeCount || 0,
      directed: Boolean(this.graph?.directed),
      database: this.repository.dbPath || null
    };
  }

  searchAirports(query, limit) {
    this.initialize();
    return this.repository.searchAirports(query, limit);
  }

  /**
   * 自定义航路分析：额外识别输入开头/结尾的进离场程序名，
   * 并结合界面已选的起降机场构建程序几何，用于前端绘制完整程序路径。
   */
  analyzeRoute(routeString, options = {}) {
    this.initialize();
    const cycle = this.cycle?.CycleName || this.cycle?.cycle || 'Unknown';
    const result = analyzeRoute(this.repository, this.graph, cycle, routeString);
    if (!result.ok) return result;
    const tokens = tokenize(routeString);
    return {
      ...result,
      sidGeometry: this.buildSideGeometry(tokens, options.origin, 'sid'),
      starGeometry: this.buildSideGeometry(tokens, options.destination, 'star')
    };
  }

  /** 识别开头/结尾程序名并构建其完整折线几何，SID 从起飞机场到出口，STAR 从入口到到达机场*/
  buildSideGeometry(tokens, icao, direction) {
    if (!icao) return null;
    let name;
    if (direction === 'sid') {
      name = tokens[0];
      // 输入可能以机场代码开头，如 ZSJN EXUV1D ...，跳过机场再取程序名
      if (name && /^[A-Z]{4}$/.test(name)) name = tokens[1];
    } else {
      name = tokens[tokens.length - 1];
      // 输入可能以机场代码结尾，如 ... VINE1J ZUCK
      if (name && /^[A-Z]{4}$/.test(name)) name = tokens[tokens.length - 2];
    }
    if (!name || !this.repository.isProcedureName?.(name)) return null;
    try {
      const airport = this.repository.getAirport(icao);
      const candidate = buildProcedureCandidate(this.repository, airport, name, null, direction, this.graphNodeIds, null, this.graph);
      return candidate ? candidate.path : null;
    } catch {
      return null;
    }
  }

  plan(originIcao, destinationIcao, options = {}) {
    this.initialize();
    const origin = this.repository.getAirport(originIcao);
    const destination = this.repository.getAirport(destinationIcao);
    if (origin.ICAO === destination.ICAO) {
      return buildLocalRoute(origin, this.buildStatus());
    }

    const sidFallback = { triggered: false, message: null };
    const starFallback = { triggered: false, message: null };
    const sidCandidates = this.buildSideCandidates(origin, options.sid, options.originRunway, 'sid', sidFallback);
    const starCandidates = this.buildSideCandidates(destination, options.star, options.destinationRunway, 'star', starFallback);

    const results = planHighIfrRoutes(origin, destination, this.graph, sidCandidates, starCandidates, {
      limit: 5
    });
    if (results.length === 0) {
      throw new RouteNotFoundError('未找到可用的高空航路或允许范围内的直飞连接');
    }

    const routes = results.map((result, index) => ({
      ...serializeRoute(result, origin, destination, this.graph, this.buildStatus()),
      optionIndex: index,
      costDelta: result.costs.total - results[0].costs.total,
      sidFallback: sidFallback.triggered,
      starFallback: starFallback.triggered,
      fallbackMessage: [sidFallback.message, starFallback.message].filter(Boolean).join(' ')
    }));
    return { ...routes[0], alternatives: routes.slice(1) };
  }

  buildSideCandidates(airport, procedureName, runway, direction, fallback) {
    const proc = direction === 'sid' ? '2' : '1';
    const none = direction === 'sid' ? NO_SID : NO_STAR;
    const runwayPoint = runway ? this.getRunwayPoint(airport, runway) : null;
    if (procedureName && procedureName !== none) {
      const candidate = buildProcedureCandidate(
        this.repository, airport, procedureName, runway, direction, this.graphNodeIds, runwayPoint, this.graph
      );
      if (candidate) return [candidate];
      fallback.triggered = true;
      fallback.message = direction === 'sid'
        ? `所选离场程序 ${procedureName} 无法连接高空航路网，已自动回退为自动离场`
        : `所选进场程序 ${procedureName} 无法连接高空航路网，已自动回退为自动进场`;
    }
    return buildAutomaticCandidates(this.repository, airport, proc, direction, this.graphNodeIds, this.graph, runwayPoint);
  }

  getRunwayPoint(airport, runway) {
    const found = this.repository.getRunways(airport.ID).find((r) => r.Ident === runway);
    if (!found) return null;
    return { id: null, ident: found.Ident, lat: found.Latitude, lon: found.Longtitude };
  }

  /**
   * 自动推荐离场跑道与程序：按 METAR 风况选逆风最大、侧风最小的跑道，
   * 再从该跑道支持的程序中用 A* 选最优，需目的地有效。
   */
  recommendOrigin(originIcao, destinationIcao, metar = {}) {
    this.initialize();
    const origin = this.repository.getAirport(originIcao);
    const runways = this.repository.getRunways(origin.ID).map(metricRunway);
    const procs = this.annotateProcedures(this.repository.getTerminalProcedures(origin, '2'));

    const wind = metar.available !== false && metar.windDirection != null && metar.windSpeed != null
      ? {
          direction: metar.windDirection,
          speed: metar.windSpeed,
          gust: metar.windGust ?? null,
          unit: metar.windUnit || 'kt'
        }
      : null;

    let scoredRunways;
    if (wind) {
      scoredRunways = runways.map((r) => {
        const comp = computeWindComponents(wind.direction, wind.speed, r.TrueHeading);
        return { ...r, headwind: comp.headwind, crosswind: comp.crosswind, score: comp.headwind - Math.abs(comp.crosswind) };
      }).sort((a, b) => b.score - a.score);
    } else {
      scoredRunways = runways;
    }

    let destination = null;
    try { destination = this.repository.getAirport(destinationIcao); } catch { /* 目的地无效 */ }

    for (const rw of scoredRunways) {
      const supported = procs.filter((p) => supportsRunway(p, rw.Ident));
      if (supported.length === 0) continue;
      const chosen = {
        runway: rw.Ident,
        lengthM: rw.lengthM,
        widthM: rw.widthM,
        hasWind: !!wind,
        headwind: wind ? rw.headwind : null,
        crosswind: wind ? rw.crosswind : null
      };
      const runwayPoint = this.getRunwayPoint(origin, rw.Ident);
      const sids = supported
        .map((p) => buildProcedureCandidate(this.repository, origin, p.fullName, rw.Ident, 'sid', this.graphNodeIds, runwayPoint, this.graph))
        .filter(Boolean);
      if (destination && sids.length > 0) {
        const stars = buildAutomaticCandidates(this.repository, destination, '1', 'star', this.graphNodeIds, this.graph, null);
        const best = stars.length > 0
          ? planHighIfrRoutes(origin, destination, this.graph, sids, stars, { limit: 1 })[0]
          : null;
        const picked = best ? best.sid : sids[0];
        chosen.sid = picked.procedure;
        chosen.exit = picked.waypointIdent;
        chosen.distance = picked.distance;
      } else {
        const first = sids[0] || buildProcedureCandidate(this.repository, origin, supported[0].fullName, rw.Ident, 'sid', this.graphNodeIds, runwayPoint, this.graph);
        if (first) {
          chosen.sid = first.procedure;
          chosen.exit = first.waypointIdent;
          chosen.distance = first.distance;
        }
      }
      return chosen;
    }
    return { runway: null, sid: null, hasWind: !!wind };
  }

  /**
   * 自动推荐进场跑道与程序：按 METAR 风况选逆风最大、侧风最小的跑道，
   * 再从该跑道支持的程序中用 A* 选最优，需起飞机场有效。
   */
  recommendDestination(destinationIcao, originIcao, metar = {}) {
    this.initialize();
    const destination = this.repository.getAirport(destinationIcao);
    const runways = this.repository.getRunways(destination.ID).map(metricRunway);
    const procs = this.annotateProcedures(this.repository.getTerminalProcedures(destination, '1'));

    const wind = metar.available !== false && metar.windDirection != null && metar.windSpeed != null
      ? {
          direction: metar.windDirection,
          speed: metar.windSpeed,
          gust: metar.windGust ?? null,
          unit: metar.windUnit || 'kt'
        }
      : null;

    let scoredRunways;
    if (wind) {
      scoredRunways = runways.map((r) => {
        const comp = computeWindComponents(wind.direction, wind.speed, r.TrueHeading);
        return { ...r, headwind: comp.headwind, crosswind: comp.crosswind, score: comp.headwind - Math.abs(comp.crosswind) };
      }).sort((a, b) => b.score - a.score);
    } else {
      scoredRunways = runways;
    }

    let origin = null;
    try { origin = this.repository.getAirport(originIcao); } catch { /* 起飞机场无效 */ }

    for (const rw of scoredRunways) {
      const supported = procs.filter((p) => supportsRunway(p, rw.Ident));
      if (supported.length === 0) continue;
      const chosen = {
        runway: rw.Ident,
        lengthM: rw.lengthM,
        widthM: rw.widthM,
        hasWind: !!wind,
        headwind: wind ? rw.headwind : null,
        crosswind: wind ? rw.crosswind : null
      };
      const runwayPoint = this.getRunwayPoint(destination, rw.Ident);
      const stars = supported
        .map((p) => buildProcedureCandidate(this.repository, destination, p.fullName, rw.Ident, 'star', this.graphNodeIds, runwayPoint, this.graph))
        .filter(Boolean);
      if (origin && stars.length > 0) {
        const sids = buildAutomaticCandidates(this.repository, origin, '2', 'sid', this.graphNodeIds, this.graph, null);
        const best = sids.length > 0
          ? planHighIfrRoutes(origin, destination, this.graph, sids, stars, { limit: 1 })[0]
          : null;
        const picked = best ? best.star : stars[0];
        chosen.star = picked.procedure;
        chosen.entry = picked.waypointIdent;
        chosen.distance = picked.distance;
      } else {
        const first = stars[0] || buildProcedureCandidate(this.repository, destination, supported[0].fullName, rw.Ident, 'star', this.graphNodeIds, runwayPoint, this.graph);
        if (first) {
          chosen.star = first.procedure;
          chosen.entry = first.waypointIdent;
          chosen.distance = first.distance;
        }
      }
      return chosen;
    }
    return { runway: null, star: null, hasWind: !!wind };
  }

  getAirportDetails(icao) {
    this.initialize();
    const airport = this.repository.getAirport(icao);
    const runways = this.repository.getRunways(airport.ID).map(metricRunway);
    return {
      airport: {
        icao: airport.ICAO,
        name: airport.Name,
        lat: airport.Latitude,
        lon: airport.Longtitude,
        elevation: airport.Elevation,
        transitionAltitude: airport.TransitionAltitude,
        transitionLevel: airport.TransitionLevel
      },
      runways,
      sids: this.annotateProcedures(this.repository.getTerminalProcedures(airport, '2')),
      stars: this.annotateProcedures(this.repository.getTerminalProcedures(airport, '1'))
    };
  }

  annotateProcedures(procedures) {
    return procedures.map((p) => {
      const legs = this.repository.getTerminalLegs(p.terminalId);
      return { ...p, support: procedureSupport(legs) };
    });
  }

  getRunwayWind(icao, metar = {}) {
    this.initialize();
    const airport = this.repository.getAirport(icao);
    const runways = this.repository.getRunways(airport.ID).map(metricRunway);
    const available = metar.available !== false && (metar.windDirection != null || metar.windSpeed != null);
    if (!available) return { airport: { icao }, wind: null, runways };
    const wind = {
      direction: metar.windDirection ?? null,
      speed: metar.windSpeed ?? null,
      gust: metar.windGust ?? null,
      unit: metar.windUnit || 'kt',
      available: true
    };
    if (wind.direction == null) return { airport: { icao }, wind, runways }; // VRB 不定风
    return {
      airport: { icao },
      wind,
      runways: runways.map((r) => {
        const comp = computeWindComponents(wind.direction, wind.speed, r.TrueHeading);
        return { ...r, headwind: comp.headwind, tailwind: -comp.headwind, crosswind: comp.crosswind, crossFrom: comp.crossFrom };
      })
    };
  }

  close() {
    this.repository.close();
  }
}

class RouteInputError extends Error {}
class RouteNotFoundError extends Error {}

function buildLocalRoute(airport, status) {
  return {
    method: 'LOCAL',
    origin: airportSummary(airport),
    destination: airportSummary(airport),
    cycle: status.cycle,
    routeString: 'LOCAL',
    message: '本场飞行的航路就是LOCAL',
    sid: null,
    star: null,
    segments: [],
    costs: {
      sidDistance: 0,
      airwayDistance: 0,
      switchCount: 0,
      switchPenalty: 0,
      starDistance: 0,
      total: 0
    },
    geometry: { sid: [], airway: [], star: [] },
    optionIndex: 0,
    costDelta: 0,
    alternatives: []
  };
}

function isRepository(value) {
  return value && typeof value.loadHighAirwayGraph === 'function' && typeof value.getAirport === 'function';
}

function metricRunway(r) {
  return { ...r, lengthM: Math.round(r.Length * 0.3048), widthM: Math.round(r.Width * 0.3048) };
}

/** 程序是否支持该跑道，与前端一致*/
function supportsRunway(proc, runway) {
  if (!runway) return true;
  if (proc.rwy) return proc.rwy === runway;
  if (!proc.support || proc.support.length === 0) return true;
  return proc.support.includes(runway);
}

/**
 * 程序支持的跑道集合：从 TerminalLegs 的过渡段解析，RW16L -> '16L'；
 * 无任何跑道过渡段，仅 ALL 时返回空数组，表示所有跑道通用。
 */
function procedureSupport(legs) {
  const set = new Set();
  let hasRw = false;
  for (const leg of legs) {
    if (leg.Transition && leg.Transition.startsWith('RW')) {
      hasRw = true;
      set.add(leg.Transition.slice(2));
    }
  }
  return hasRw ? [...set] : [];
}

function serializeRoute(result, origin, destination, graph, status) {
  const point = (ident, lat, lon, type = 'waypoint') => ({ ident, lat, lon, type });
  const airportPoint = (airport) => point(airport.ICAO, airport.Latitude, airport.Longtitude, 'airport');
  const sid = result.sid;
  const star = result.star;
  const sidNode = graph.nodes.get(sid.waypointId);
  const starNode = graph.nodes.get(star.waypointId);

  const sidGeometry = sid.path && sid.path.length > 1
    ? sid.path
    : [airportPoint(origin), point(sidNode.ident, sidNode.lat, sidNode.lon)];
  const starGeometry = star.path && star.path.length > 1
    ? star.path
    : [point(starNode.ident, starNode.lat, starNode.lon), airportPoint(destination)];

  const airwayGeometry = [];
  if (result.airwayEdges.length > 0) {
    const first = graph.nodes.get(result.airwayEdges[0].from);
    airwayGeometry.push(point(first.ident, first.lat, first.lon));
    for (const edge of result.airwayEdges) {
      const node = graph.nodes.get(edge.to);
      airwayGeometry.push(point(node.ident, node.lat, node.lon));
    }
  }

  return {
    method: result.method,
    origin: airportSummary(origin),
    destination: airportSummary(destination),
    cycle: status.cycle,
    routeString: buildRouteString(origin, destination, result, graph),
    sid: {
      procedure: sid.procedure || null,
      runway: sid.runway || null,
      exit: sid.waypointIdent,
      distance: result.costs.sidDistance,
      mode: sid.procedure ? 'PROCEDURE' : 'DIRECT'
    },
    star: {
      procedure: star.procedure || null,
      runway: star.runway || null,
      entry: star.waypointIdent,
      distance: result.costs.starDistance,
      mode: star.procedure ? 'PROCEDURE' : 'DIRECT'
    },
    segments: result.segments.map((segment) => ({
      airway: segment.airway,
      level: segment.level,
      from: graph.nodes.get(segment.from)?.ident || `WPT${segment.from}`,
      to: graph.nodes.get(segment.to)?.ident || `WPT${segment.to}`,
      distance: segment.distance
    })),
    costs: result.costs,
    geometry: {
      sid: dedupeAdjacent(sidGeometry),
      airway: dedupeAdjacent(airwayGeometry),
      star: dedupeAdjacent(starGeometry)
    }
  };
}

/**
 * 含程序名的航路字符串：ELKU2G ELKUR ... SASAN SASAN1，不含起降机场代码
 */
function buildRouteString(origin, destination, result, graph) {
  const sid = result.sid;
  const star = result.star;
  const parts = [];
  if (sid.procedure) parts.push(sid.procedure);
  parts.push(sid.waypointIdent);
  for (const segment of result.segments) {
    parts.push(segment.airway, graph.nodes.get(segment.to)?.ident || `WPT${segment.to}`);
  }
  if (parts[parts.length - 1] !== star.waypointIdent) parts.push(star.waypointIdent);
  if (star.procedure) parts.push(star.procedure);
  return parts.join(' ');
}

/**
 * 自动，NO SID/NO STAR 候选：遍历全部程序找出口/入口，按出口去重，距离为直线。
 */
function buildAutomaticCandidates(repository, airport, proc, direction, graphNodeIds, graph, startPoint = null) {
  const terminals = repository.getTerminalProcedures(airport, proc);
  const byWaypoint = new Map();
  const start = startPoint || airportPoint(airport);
  for (const terminal of terminals) {
    const legs = repository.getTerminalLegs(terminal.terminalId);
    const waypoints = [];
    for (const leg of legs) {
      if (!leg.WptID || leg.WptLat == null || leg.WptLon == null) continue;
      const node = graph.nodes.get(leg.WptID);
      waypoints.push({
        id: leg.WptID,
        ident: leg.Ident || node?.ident || `WPT${leg.WptID}`,
        lat: Number(leg.WptLat),
        lon: Number(leg.WptLon)
      });
    }
    let index = -1;
    if (direction === 'sid') {
      for (let i = waypoints.length - 1; i >= 0; i--) {
        if (graphNodeIds.has(waypoints[i].id)) { index = i; break; }
      }
    } else {
      for (let i = 0; i < waypoints.length; i++) {
        if (graphNodeIds.has(waypoints[i].id)) { index = i; break; }
      }
    }
    if (index === -1) continue;
    const wp = waypoints[index];
    if (byWaypoint.has(wp.id)) continue;
    const end = { id: wp.id, ident: wp.ident, lat: wp.lat, lon: wp.lon };
    byWaypoint.set(wp.id, {
      terminalId: terminal.terminalId,
      procedure: null,
      runway: null,
      waypointId: wp.id,
      waypointIdent: wp.ident,
      distance: distanceNM(start.lat, start.lon, wp.lat, wp.lon),
      path: direction === 'sid' ? [start, end] : [end, start],
      direct: true
    });
  }
  return [...byWaypoint.values()].sort((a, b) => a.distance - b.distance);
}

function airportSummary(airport) {
  return {
    icao: airport.ICAO,
    name: airport.Name,
    lat: airport.Latitude,
    lon: airport.Longtitude,
    elevation: airport.Elevation
  };
}

function dedupeAdjacent(points) {
  return points.filter((item, index) => {
    const previous = points[index - 1];
    return !previous || item.lat !== previous.lat || item.lon !== previous.lon;
  });
}

module.exports = {
  PlannerService,
  RouteInputError,
  RouteNotFoundError,
  serializeRoute
};