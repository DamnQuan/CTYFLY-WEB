/**
 * 终端区程序路径构建，SID / STAR
 * 严格按 TerminalLegs 逐段绘制：TF/DF/IF/CF 直线、RF 圆弧插值、矢量段沿航向延伸。
 */
const { distanceNM } = require('./geo');

const VECTOR_EXTEND_NM = 10; // 矢量航段无距离时的名义延伸
const EARTH_RADIUS_NM = 3440.065;

function airportPoint(airport) {
  return { id: null, ident: airport.ICAO, lat: airport.Latitude, lon: airport.Longtitude, airport: true };
}

/**
 * 按所选跑道过滤过渡段：保留 RW<跑道> 过渡 + ALL 公共段，记忆：不过滤会导致路径乱跳。
 * 无跑道时：保留 ALL 公共段 + 第一条含实质路径，≥2 航点的过渡段，
 * 保证选程序时能绘制完整的进离场路径，而不是只剩直线
 * 如 RKSI 部分 STAR 的完整路径都在跑道过渡段里，ALL 段只有入口一点。
 */
function filterTransitionLegs(legs, runway) {
  if (runway) {
    const wanted = new Set(['ALL', `RW${runway}`]);
    return legs.filter((leg) => leg.Transition && wanted.has(leg.Transition));
  }
  const groups = new Map();
  for (const leg of legs) {
    if (!leg.Transition) continue;
    if (!groups.has(leg.Transition)) groups.set(leg.Transition, []);
    groups.get(leg.Transition).push(leg);
  }
  const wanted = new Set(['ALL']);
  for (const [transition, group] of groups) {
    if (transition === 'ALL') continue;
    if (group.filter((leg) => leg.WptID).length >= 2) {
      wanted.add(transition);
      break;
    }
  }
  return legs.filter((leg) => leg.Transition && wanted.has(leg.Transition));
}

function isVectorLeg(leg) {
  return !leg.WptID && (leg.NavBear != null || leg.Course != null);
}

function endpointFrom(pt, courseDeg, distNm) {
  const d = distNm / EARTH_RADIUS_NM;
  const crs = courseDeg * Math.PI / 180;
  const lat1 = pt.lat * Math.PI / 180;
  const lon1 = pt.lon * Math.PI / 180;
  const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(crs));
  const lon2 = lon1 + Math.atan2(Math.sin(crs) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));
  return { id: null, ident: null, lat: lat2 * 180 / Math.PI, lon: lon2 * 180 / Math.PI };
}

function interpolateArc(from, to, center) {
  const N = 12;
  const pts = [];
  const v1 = { x: from.lat - center.lat, y: from.lon - center.lon };
  const v2 = { x: to.lat - center.lat, y: to.lon - center.lon };
  let a1 = Math.atan2(v1.y, v1.x);
  let a2 = Math.atan2(v2.y, v2.x);
  let d = a2 - a1;
  while (d > Math.PI) d -= 2 * Math.PI;
  while (d < -Math.PI) d += 2 * Math.PI;
  const r = Math.hypot(v1.x, v1.y) || 1;
  for (let i = 1; i < N; i++) {
    const a = a1 + d * i / N;
    pts.push({ id: null, ident: null, lat: center.lat + r * Math.cos(a), lon: center.lon + r * Math.sin(a) });
  }
  return pts;
}

/**
 * 解析航段为逻辑航点序列，waypoints，用于出口/入口与距离与完整折线，line，用于绘制
 */
function buildPath(legs, graph = null) {
  const waypoints = [];
  const line = [];
  let prev = null;
  for (const leg of legs) {
    if (leg.WptID && leg.WptLat != null && leg.WptLon != null) {
      const node = graph?.nodes.get(leg.WptID);
      const wp = {
        id: leg.WptID,
        ident: leg.Ident || node?.ident || null,
        lat: Number(leg.WptLat),
        lon: Number(leg.WptLon)
      };
      if (leg.TrackCode === 'RF' && leg.CenterLat != null && leg.CenterLon != null && prev) {
        line.push(...interpolateArc(prev, wp, { lat: Number(leg.CenterLat), lon: Number(leg.CenterLon) }));
      }
      waypoints.push(wp);
      line.push({ ...wp });
      prev = wp;
    } else if (isVectorLeg(leg) && prev) {
      const dist = Number(leg.NavDist ?? leg.Distance) || VECTOR_EXTEND_NM;
      const course = leg.NavBear ?? leg.Course;
      const pt = endpointFrom(prev, Number(course), dist);
      line.push(pt);
    }
  }
  return { waypoints, line };
}

function lineCut(line, waypointId) {
  for (let i = line.length - 1; i >= 0; i--) {
    if (line[i].id === waypointId) return i;
  }
  return -1;
}

/**
 * 构建所选程序的候选：固定出口/入口，程序实际路径距离，完整折线几何。
 * 返回 null 表示程序无法连接高空航路网。
 */
function buildProcedureCandidate(repository, airport, procedureName, runway, direction, graphNodeIds, runwayPoint = null, graph = null) {
  const proc = direction === 'sid' ? '2' : '1';
  const terminals = repository.getTerminalProcedures(airport, proc);
  const terminal = terminals.find((t) => t.fullName === procedureName || t.name === procedureName);
  if (!terminal) return null;

  const legs = filterTransitionLegs(repository.getTerminalLegs(terminal.terminalId), runway);
  const { waypoints, line } = buildPath(legs, graph);
  if (waypoints.length === 0) return null;

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
  if (index === -1) return null;

  const start = runwayPoint || airportPoint(airport);
  const anchor = waypoints[index];
  let path;
  let distance;

  if (direction === 'sid') {
    const cut = lineCut(line, anchor.id);
    path = [start, ...line.slice(0, cut === -1 ? line.length : cut + 1)];
    distance = distanceNM(start.lat, start.lon, waypoints[0].lat, waypoints[0].lon);
    for (let i = 1; i <= index; i++) {
      distance += distanceNM(waypoints[i - 1].lat, waypoints[i - 1].lon, waypoints[i].lat, waypoints[i].lon);
    }
  } else {
    const cut = lineCut(line, anchor.id);
    path = [...line.slice(cut === -1 ? 0 : cut), start];
    distance = 0;
    for (let i = index; i < waypoints.length - 1; i++) {
      distance += distanceNM(waypoints[i].lat, waypoints[i].lon, waypoints[i + 1].lat, waypoints[i + 1].lon);
    }
    const last = waypoints[waypoints.length - 1];
    distance += distanceNM(last.lat, last.lon, start.lat, start.lon);
  }

  return {
    terminalId: terminal.terminalId,
    procedure: terminal.fullName,
    runway: runway || null,
    waypointId: anchor.id,
    waypointIdent: anchor.ident,
    distance,
    path,
    direct: false
  };
}

module.exports = { buildProcedureCandidate, filterTransitionLegs, airportPoint };
