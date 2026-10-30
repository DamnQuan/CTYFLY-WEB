const { distanceNM } = require('./geo');
const { MinHeap } = require('./priority-queue');

const SWITCH_PENALTY_NM = 5;
const DCT_LIMIT_NM = 400;

function planHighIfrRoute(origin, destination, graph, sidCandidates, starCandidates, options = {}) {
  const switchPenalty = options.switchPenalty ?? SWITCH_PENALTY_NM;
  const maxDct = options.maxDct ?? DCT_LIMIT_NM;

  if (sidCandidates.length === 0) {
    throw new Error(`No SID candidates from ${origin.ICAO} connect to the H/B airway graph`);
  }
  if (starCandidates.length === 0) {
    throw new Error(`No STAR candidates into ${destination.ICAO} connect to the H/B airway graph`);
  }

  const starByWaypoint = new Map();
  for (const star of starCandidates) {
    const previous = starByWaypoint.get(star.waypointId);
    if (!previous || star.distance < previous.distance) starByWaypoint.set(star.waypointId, star);
  }

  const result = searchAirways(graph, sidCandidates, starCandidates, starByWaypoint, switchPenalty, options.excludedLegs);
  if (result) return formatResult('AIRWAY', origin, destination, result, switchPenalty);

  const dct = findDctBridge(sidCandidates, starCandidates, graph, maxDct);
  if (dct) return formatResult('DCT', origin, destination, dct, switchPenalty);

  return null;
}

function planHighIfrRoutes(origin, destination, graph, sidCandidates, starCandidates, options = {}) {
  const limit = Math.max(1, Math.min(Number(options.limit) || 5, 8));
  const primary = planHighIfrRoute(origin, destination, graph, sidCandidates, starCandidates, options);
  if (!primary || limit === 1 || primary.method !== 'AIRWAY') return primary ? [primary] : [];

  const routes = [primary];
  const signatures = new Set([routeSignature(primary)]);
  const pivots = evenlySpaced(primary.airwayEdges, Math.min(8, primary.airwayEdges.length));

  for (const edge of pivots) {
    if (routes.length >= limit) break;
    const alternative = planHighIfrRoute(origin, destination, graph, sidCandidates, starCandidates, {
      ...options,
      maxDct: -1,
      excludedLegs: new Set([edgeKey(edge)])
    });
    if (!alternative || alternative.method !== 'AIRWAY') continue;
    const signature = routeSignature(alternative);
    if (signatures.has(signature)) continue;
    signatures.add(signature);
    routes.push(alternative);
  }

  const maximumCost = primary.costs.total * (options.maxCostFactor ?? 1.5);
  return routes
    .filter((route, index) => index === 0 || route.costs.total <= maximumCost)
    .sort((left, right) => left.costs.total - right.costs.total)
    .slice(0, limit);
}

function searchAirways(graph, sidCandidates, starCandidates, starByWaypoint, switchPenalty, excludedLegs = new Set()) {
  const queue = new MinHeap((a, b) => a.f - b.f || a.g - b.g);
  const bestG = new Map();
  const parents = new Map();
  let bestComplete = null;

  for (const sid of sidCandidates) {
    const node = graph.nodes.get(sid.waypointId);
    if (!node) continue;
    const key = stateKey(sid.waypointId, null);
    const g = sid.distance;
    if ((bestG.get(key) ?? Infinity) <= g) continue;
    bestG.set(key, g);
    parents.set(key, { parent: null, nodeId: sid.waypointId, airway: null, sid, edge: null });
    queue.push({ nodeId: sid.waypointId, airway: null, g, f: g + heuristic(node, starCandidates, graph) });
  }

  while (queue.size > 0) {
    const current = queue.pop();
    const currentKey = stateKey(current.nodeId, current.airway);
    if (current.g !== bestG.get(currentKey)) continue;

    if (bestComplete && current.f > bestComplete.totalCost) break;

    const star = starByWaypoint.get(current.nodeId);
    if (star) {
      const totalCost = current.g + star.distance;
      if (!bestComplete || totalCost < bestComplete.totalCost) {
        bestComplete = buildCompleteRoute(parents, currentKey, star, totalCost);
      }
    }

    const edges = graph.adj.get(current.nodeId) || [];
    for (const edge of edges) {
      if (excludedLegs?.has(edgeKey(edge))) continue;
      const nextAirway = edge.airway;
      const switchCost = current.airway && current.airway !== nextAirway ? switchPenalty : 0;
      const nextG = current.g + edge.distance + switchCost;
      const nextKey = stateKey(edge.to, nextAirway);

      if ((bestG.get(nextKey) ?? Infinity) <= nextG) continue;

      const nextNode = graph.nodes.get(edge.to);
      bestG.set(nextKey, nextG);
      parents.set(nextKey, { parent: currentKey, nodeId: edge.to, airway: nextAirway, edge });
      queue.push({ nodeId: edge.to, airway: nextAirway, g: nextG, f: nextG + heuristic(nextNode, starCandidates, graph) });
    }
  }

  return bestComplete;
}

function edgeKey(edge) {
  return edge.legId !== undefined ? `leg:${edge.legId}` : `${edge.from}>${edge.to}:${edge.airway}`;
}

function routeSignature(route) {
  return `${route.sid.waypointId}|${route.airwayEdges.map(edgeKey).join(',')}|${route.star.waypointId}`;
}

function evenlySpaced(items, limit) {
  if (items.length <= limit) return items;
  const selected = [];
  for (let index = 0; index < limit; index++) {
    selected.push(items[Math.round(index * (items.length - 1) / (limit - 1))]);
  }
  return selected;
}

function heuristic(node, starCandidates, graph) {
  let best = Infinity;
  for (const star of starCandidates) {
    const starNode = graph.nodes.get(star.waypointId);
    if (!starNode) continue;
    // Great-circle distance is a lower bound for any airway path. STAR cost is exact
    // for the candidate, so their sum remains admissible.
    const estimate = distanceNM(node.lat, node.lon, starNode.lat, starNode.lon) + star.distance;
    if (estimate < best) best = estimate;
  }
  return best;
}

function buildCompleteRoute(parents, key, star, totalCost) {
  const states = [];
  let cursor = key;
  while (cursor) {
    const entry = parents.get(cursor);
    states.push(entry);
    cursor = entry.parent;
  }
  states.reverse();

  const sid = states[0].sid;
  const airwayEdges = [];
  for (const state of states.slice(1)) {
    if (state.edge) airwayEdges.push(state.edge);
  }

  return {
    sid,
    star,
    airwayEdges,
    airwayDistance: sum(airwayEdges.map((e) => e.distance)),
    switchCount: countSwitches(airwayEdges),
    totalCost
  };
}

function findDctBridge(sidCandidates, starCandidates, graph, maxDct) {
  let best = null;
  for (const sid of sidCandidates) {
    const sidNode = graph.nodes.get(sid.waypointId);
    if (!sidNode) continue;
    for (const star of starCandidates) {
      const starNode = graph.nodes.get(star.waypointId);
      if (!starNode) continue;
      const dctDistance = distanceNM(sidNode.lat, sidNode.lon, starNode.lat, starNode.lon);
      if (dctDistance > maxDct) continue;
      const totalCost = sid.distance + dctDistance + star.distance;
      if (!best || totalCost < best.totalCost) {
        best = {
          sid,
          star,
          airwayEdges: [{
            from: sid.waypointId,
            to: star.waypointId,
            fromIdent: sid.waypointIdent,
            toIdent: star.waypointIdent,
            airway: 'DCT',
            level: 'DCT',
            distance: dctDistance
          }],
          airwayDistance: dctDistance,
          switchCount: 0,
          totalCost
        };
      }
    }
  }
  return best;
}

function formatResult(method, origin, destination, route, switchPenaltyPerChange) {
  const sidDistance = route.sid.distance;
  const starDistance = route.star.distance;
  const switchPenalty = route.switchCount * switchPenaltyPerChange;
  return {
    method,
    origin: origin.ICAO,
    destination: destination.ICAO,
    sid: route.sid,
    star: route.star,
    airwayEdges: route.airwayEdges,
    segments: mergeAirwaySegments(route.airwayEdges),
    costs: {
      sidDistance,
      airwayDistance: route.airwayDistance,
      switchCount: route.switchCount,
      switchPenalty,
      starDistance,
      total: route.totalCost
    },
    routeString: buildRouteString(origin, destination, route)
  };
}

function mergeAirwaySegments(edges) {
  if (edges.length === 0) return [];
  const segments = [];
  let current = { airway: edges[0].airway, level: edges[0].level, from: edges[0].from, to: edges[0].to, distance: 0, edges: [] };

  for (const edge of edges) {
    if (edge.airway !== current.airway) {
      segments.push(current);
      current = { airway: edge.airway, level: edge.level, from: edge.from, to: edge.to, distance: 0, edges: [] };
    }
    current.to = edge.to;
    current.distance += edge.distance;
    current.edges.push(edge);
  }
  segments.push(current);
  return segments;
}

function buildRouteString(origin, destination, route) {
  const parts = [origin.ICAO, 'SID', route.sid.waypointIdent];
  for (const segment of mergeAirwaySegments(route.airwayEdges)) {
    const lastEdge = segment.edges[segment.edges.length - 1];
    parts.push(segment.airway, lastEdge.toIdent || `WPT${lastEdge.to}`);
  }
  if (parts[parts.length - 1] !== route.star.waypointIdent) parts.push(route.star.waypointIdent);
  parts.push('STAR', destination.ICAO);
  return parts.join(' ');
}

function stateKey(nodeId, airway) {
  return `${nodeId}|${airway || ''}`;
}

function countSwitches(edges) {
  let count = 0;
  for (let i = 1; i < edges.length; i++) {
    if (edges[i - 1].airway !== edges[i].airway) count++;
  }
  return count;
}

function sum(values) {
  return values.reduce((acc, value) => acc + value, 0);
}

module.exports = {
  planHighIfrRoute,
  planHighIfrRoutes,
  SWITCH_PENALTY_NM,
  DCT_LIMIT_NM
};