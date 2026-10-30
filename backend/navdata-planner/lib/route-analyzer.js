/**
 * 自定义航路分析与校验。
 * 支持格式：交替「航点 航路 航点」，可用 DCT 表示直飞，自动过滤跑道号、SID/STAR、
 * N0123F350 等速度高度字段。逐段校验航点存在性与航路方向，返回总距离。
 *
 * 容错策略，现实航路充满数据外航段：
 * - 航点不在航路图时，回退到导航库按 Ident 查坐标，同名多点就近挑选；
 * - 航路段在导航库中不存在时，降级为 DCT 直飞，标注 assumed，不中断整个航路分析。
 */
const { distanceNM } = require('./geo');

function tokenize(input) {
  return String(input || '')
    .toUpperCase()
    .split(/[\s,;]+/)
    .filter(Boolean)
    .filter((t) => {
      if (/^N\d{4,5}F\d{3,4}$/.test(t)) return false; // 速度高度 N0123F350
      if (/^(SID|STAR|NOSID|NOSTAR)$/.test(t)) return false; // 进离场关键字
      if (/^\d{1,2}[LRC]$/.test(t) || /^RW\d{1,2}[LRC]?$/.test(t)) return false; // 跑道号 36R / RW36R
      return /^[A-Z0-9]{2,7}$/.test(t);
    });
}

/** 从同名候选中挑距参考点最近的，无参考点时取第一个*/
function nearest(candidates, near) {
  if (!near || candidates.length <= 1) return candidates[0] || null;
  let best = candidates[0];
  let bestD = Infinity;
  for (const c of candidates) {
    const d = distanceNM(near.lat, near.lon, c.lat, c.lon);
    if (d < bestD) { bestD = d; best = c; }
  }
  return best;
}

/** 从同名候选中挑距参考点最近的，无参考点时取第一个*/
function nearest(candidates, near) {
  if (!near || candidates.length <= 1) return candidates[0] || null;
  let best = candidates[0];
  let bestD = Infinity;
  for (const c of candidates) {
    const d = distanceNM(near.lat, near.lon, c.lat, c.lon);
    if (d < bestD) { bestD = d; best = c; }
  }
  return best;
}

function analyzeRoute(repository, graph, cycle, input) {
  const tokens = tokenize(input);
  if (tokens.length < 2) {
    return { ok: false, error: '你的航路有问题', detail: '航路至少需要「起点 航路 航点」三段', legIndex: 0 };
  }

  const airwaySet = new Set(['DCT']);
  for (const edges of graph.adj.values()) {
    for (const edge of edges) airwaySet.add(edge.airway);
  }

  const parts = [];
  let index = 0;
  // 开头的程序名，如离场程序 ANDZ 只保留显示，不作起点
  while (index < tokens.length && repository.isProcedureName?.(tokens[index])) {
    parts.push(tokens[index]);
    index += 1;
  }
  if (index >= tokens.length) {
    return { ok: false, error: '你的航路有问题', detail: '缺少可分析的航路点', legIndex: 0 };
  }

  const start = resolveStart(repository, graph, tokens[index]);
  if (!start) {
    return { ok: false, error: '你的航路有问题', detail: `起点 ${tokens[index]} 不在导航数据中`, legIndex: index };
  }

  let prev = start;
  let total = 0;
  const legs = [];
  const points = [start];
  const warnings = [];
  if (!start.airport) parts.push(start.ident);
  index += 1;

  while (index < tokens.length) {
    const token = tokens[index];
    // 程序名，SID/STAR：跳过航路校验，仅保留显示
    if (repository.isProcedureName?.(token)) {
      parts.push(token);
      index += 1;
      continue;
    }
    // 航路 token：需要下一航点，校验有向航段
    if (airwaySet.has(token) && token !== 'DCT') {
      const nextToken = tokens[index + 1];
      if (nextToken == null) {
        // 尾部悬挂的航路名，真实航路常见：忽略即可，不判错误
        index += 1;
        continue;
      }
      let next = resolveWaypoint(graph, nextToken, prev, repository);
      let isAirport = false;
      if (!next) {
        const airport = resolveAirport(repository, nextToken);
        if (airport) { next = airport; isAirport = true; }
      }
      if (!next) {
        return { ok: false, error: '你的航路有问题', detail: `航点 ${nextToken} 不在导航数据中`, legIndex: index + 1 };
      }
      if (isAirport) {
        // 终点机场：直线接入，无航路段校验
        const distance = distanceNM(prev.lat, prev.lon, next.lat, next.lon);
        legs.push({ airway: token, from: prev.ident, to: next.ident, distance });
        total += distance;
      } else {
        const edge = findEdge(graph, prev, token, next);
        if (edge) {
          legs.push({ airway: token, from: prev.ident, to: next.ident, distance: edge.distance });
          total += edge.distance;
        } else {
          // 无单段时沿同名航路多段寻路，如 W34 VYK ANRAT 中间可能经过 LADIX 等未列出航点
          const path = findAirwayPath(graph, prev, token, next);
          if (path) {
            legs.push({ airway: token, from: prev.ident, to: next.ident, distance: path.distance, via: path.edges.map((e) => e.toIdent) });
            total += path.distance;
          } else {
            // 导航库缺失该航段：降级为 DCT 直飞，现实工具同款容错，标注 assumed
            const distance = distanceNM(prev.lat, prev.lon, next.lat, next.lon);
            legs.push({ airway: token, from: prev.ident, to: next.ident, distance, assumed: true });
            total += distance;
          }
        }
      }
      parts.push(token);
      if (!next.airport) parts.push(next.ident);
      points.push(next);
      prev = next;
      index += 2;
      continue;
    }

    // 直飞关键字
    if (token === 'DCT') {
      const nextToken = tokens[index + 1];
      if (nextToken == null) {
        // 尾部悬挂的 DCT：真实航路常见写法，直接忽略
        index += 1;
        continue;
      }
      const next = resolveWaypoint(graph, nextToken, prev, repository);
      if (!next) {
        if (index + 1 >= tokens.length - 1) {
          warnings.push(`航点 ${nextToken} 不在导航数据中，已忽略该段`);
          break;   // 尾部未知点：分析到此为止，前面的有效航段照常返回
        }
        return { ok: false, error: '你的航路有问题', detail: `航点 ${nextToken} 不在导航数据中`, legIndex: index + 1 };
      }
      const distance = distanceNM(prev.lat, prev.lon, next.lat, next.lon);
      legs.push({ airway: 'DCT', from: prev.ident, to: next.ident, distance });
      total += distance;
      parts.push('DCT');
      if (!next.airport) parts.push(next.ident);
      points.push(next);
      prev = next;
      index += 2;
      continue;
    }

    // 航点 token：与前一点直连，如机场 → 离场点、终点机场
    const next = resolveWaypoint(graph, token, prev, repository) || resolveAirport(repository, token);
    if (!next) {
      if (index + 1 >= tokens.length - 1) {
        warnings.push(`航点 ${token} 不在导航数据中，已忽略该点`);
        break;   // 末尾未知点：保留已分析部分
      }
      return { ok: false, error: '你的航路有问题', detail: `航路或航点 ${token} 不在导航数据中`, legIndex: index };
    }
    const distance = distanceNM(prev.lat, prev.lon, next.lat, next.lon);
    legs.push({ airway: null, from: prev.ident, to: next.ident, distance });
    total += distance;
    if (!next.airport) parts.push(next.ident);
    points.push(next);
    prev = next;
    index += 1;
  }

  return {
    ok: true,
    cycle,
    warnings,
    totalDistance: total,
    legs,
    points: points.map((p) => ({ ident: p.ident, lat: p.lat, lon: p.lon, airport: Boolean(p.airport) })),
    routeString: parts.join(' '),
    geometry: legs.map((leg) => ({ ...leg }))
  };
}

function resolveStart(repository, graph, token) {
  const airport = resolveAirport(repository, token);
  if (airport) return airport;
  return resolveWaypoint(graph, token, null, repository);
}

function resolveAirport(repository, token) {
  if (!/^[A-Z]{4}$/.test(token)) return null;
  try {
    const airport = repository.getAirport(token);
    return { ident: airport.ICAO, lat: airport.Latitude, lon: airport.Longtitude, airport: true };
  } catch {
    return null;
  }
}

/** 航点解析：先查航路图，同名多点就近，再回退导航库 Waypoints 表按名字查，就近挑选*/
function resolveWaypoint(graph, token, near, repository) {
  const candidates = [];
  for (const node of graph.nodes.values()) {
    if (node.ident === token) candidates.push({ ident: node.ident, lat: node.lat, lon: node.lon, id: node.id });
  }
  const best = nearest(candidates, near);
  if (best) return best;
  // 回退：导航库 Waypoints 表，覆盖仅 DCT 可达的 ENR 航点
  if (repository?.getWaypointsByIdent) {
    const dbCandidates = (repository.getWaypointsByIdent(token) || []).map((w) => ({
      ident: w.Ident, lat: w.Latitude, lon: w.Longtitude,
    }));
    return nearest(dbCandidates, near);
  }
  return null;
}

function findEdge(graph, prev, airway, next) {
  if (prev.id == null || next.id == null) return null;
  const edges = graph.adj.get(prev.id) || [];
  return edges.find((e) => e.airway === airway && e.to === next.id) || null;
}

/** 沿同名航路从 prev 到 next 多段寻路，BFS，返回边序列与总距离*/
function findAirwayPath(graph, prev, airway, next) {
  if (prev.id == null || next.id == null) return null;
  const queue = [{ id: prev.id, edges: [], dist: 0 }];
  const seen = new Set([prev.id]);
  while (queue.length > 0) {
    const current = queue.shift();
    if (current.id === next.id) return { edges: current.edges, distance: current.dist };
    for (const edge of graph.adj.get(current.id) || []) {
      if (edge.airway !== airway || seen.has(edge.to)) continue;
      seen.add(edge.to);
      queue.push({ id: edge.to, edges: [...current.edges, edge], dist: current.dist + edge.distance });
    }
  }
  return null;
}

module.exports = { analyzeRoute, tokenize };
