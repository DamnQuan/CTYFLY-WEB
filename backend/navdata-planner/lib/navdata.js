const { DatabaseSync } = require('node:sqlite');
const fs = require('node:fs');
const path = require('node:path');
const { distanceNM } = require('./geo');

const DEFAULT_DB_PATH = global.__APP_ROOT
  ? path.join(global.__APP_ROOT, 'Navdata', 'nd.db3')
  : path.join(__dirname, '..', 'Navdata', 'nd.db3');

function resolveNavdataPath(dbPath = process.env.NAVDATA_DB || DEFAULT_DB_PATH) {
  return path.resolve(dbPath);
}

class NavdataRepository {
  constructor(dbPath) {
    this.dbPath = resolveNavdataPath(dbPath);
    this.open();
  }

  open() {
    if (!fs.existsSync(this.dbPath)) {
      throw new Error(`Navigation database not found: ${this.dbPath}`);
    }
    this.db = new DatabaseSync(this.dbPath, { readOnly: true });
    this.statements = {
      airportByIcao: this.db.prepare('SELECT ID, ICAO, Name, Latitude, Longtitude, Elevation, TransitionAltitude, TransitionLevel FROM Airports WHERE ICAO=?'),
      airportSearch: this.db.prepare(`
        SELECT ICAO, Name, Latitude, Longtitude, Elevation
        FROM Airports
        WHERE ICAO LIKE ? OR Name LIKE ?
        ORDER BY
          CASE
            WHEN ICAO = ? THEN 0
            WHEN ICAO LIKE ? THEN 1
            ELSE 2
          END,
          ICAO
        LIMIT ?
      `),
      waypointById: this.db.prepare('SELECT ID, Ident, Latitude, Longtitude FROM Waypoints WHERE ID=?'),
      waypointsByIdent: this.db.prepare('SELECT ID, Ident, Latitude, Longtitude FROM Waypoints WHERE Ident=?'),
      termLegs: this.db.prepare(`
        SELECT l.ID, l.WptID, w.Ident, w.Latitude, w.Longtitude
        FROM TerminalLegs l
        LEFT JOIN Waypoints w ON w.ID = l.WptID
        WHERE l.TerminalID=?
        ORDER BY l.ID
      `),
      terminalsByAirportProc: this.db.prepare(`
        SELECT ID, Proc, FullName, Name, Rwy
        FROM Terminals
        WHERE AirportID=? AND Proc=?
        ORDER BY FullName, ID
      `),
      runwaysByAirport: this.db.prepare(`
        SELECT ID, Ident, TrueHeading, Length, Width, Surface, Latitude, Longtitude, Elevation
        FROM Runways
        WHERE AirportID=?
        ORDER BY Ident
      `),
      terminalsDetailed: this.db.prepare(`
        SELECT ID AS terminalId, Proc, FullName AS fullName, Name AS name, Rwy AS rwy, RwyID AS rwyId, IlsID AS ilsId
        FROM Terminals
        WHERE AirportID=? AND Proc=?
        ORDER BY FullName, ID
      `),
      termLegsDetailed: this.db.prepare(`
        SELECT l.ID, l.Type, l.Transition, l.TrackCode, l.WptID, l.WptLat, l.WptLon,
               l.NavID, l.NavLat, l.NavLon, l.NavBear, l.NavDist, l.Course, l.Distance,
               l.Alt, l.CenterID, l.CenterLat, l.CenterLon, l.TurnDir, w.Ident
        FROM TerminalLegs l
        LEFT JOIN Waypoints w ON w.ID = l.WptID
        WHERE l.TerminalID=?
        ORDER BY l.ID
      `)
    };
    this.fileSignature = this.getFileSignature();
  }

  close() {
    if (this.db) this.db.close();
    this.db = null;
    this.statements = null;
  }

  reload() {
    this.close();
    this.open();
  }

  getFileSignature() {
    const stat = fs.statSync(this.dbPath);
    return `${stat.size}:${stat.mtimeMs}`;
  }

  hasDatabaseChanged() {
    try {
      return this.getFileSignature() !== this.fileSignature;
    } catch {
      return true;
    }
  }

  getAirport(icao) {
    const airport = this.statements.airportByIcao.get(String(icao).toUpperCase());
    if (!airport) throw new Error(`Airport not found: ${icao}`);
    return airport;
  }

  getWaypoint(id) {
    return this.statements.waypointById.get(id);
  }

  /** 按名字查航点，同名可能 worldwide 多个，全部返回，由调用方就近挑选*/
  getWaypointsByIdent(ident) {
    return this.statements.waypointsByIdent.all(String(ident).toUpperCase());
  }

  getRunways(airportId) {
    return this.statements.runwaysByAirport.all(airportId);
  }

  getTerminalProcedures(airport, proc) {
    return this.statements.terminalsDetailed.all(airport.ID, proc);
  }

  getTerminalLegs(terminalId) {
    return this.statements.termLegsDetailed.all(terminalId);
  }

  /** 判断名称是否为某机场的进离场程序名，用于自定义航路分析时跳过程序 token*/
  isProcedureName(name) {
    return Boolean(this.db.prepare('SELECT ID FROM Terminals WHERE FullName=? OR Name=? LIMIT 1').get(name, name));
  }

  getAirportDetails(icao) {
    const airport = this.getAirport(icao);
    return {
      airport,
      runways: this.getRunways(airport.ID),
      sids: this.getTerminalProcedures(airport, '2'),
      stars: this.getTerminalProcedures(airport, '1')
    };
  }

  searchAirports(query, limit = 8) {
    const normalized = String(query).trim().toUpperCase();
    if (!normalized) return [];
    const boundedLimit = Math.max(1, Math.min(Number(limit) || 8, 20));
    return this.statements.airportSearch.all(
      `%${normalized}%`,
      `%${normalized}%`,
      normalized,
      `${normalized}%`,
      boundedLimit
    );
  }

  getCycleInfo() {
    const rows = this.db.prepare('SELECT key, val FROM config').all();
    return Object.fromEntries(rows.map((r) => [r.key, r.val]));
  }

  loadHighAirwayGraph() {
    const rows = this.db.prepare(`
      SELECT
        l.ID AS legId,
        l.AirwayID AS airwayId,
        a.Ident AS airwayIdent,
        l.Level AS level,
        l.IsStart AS isStart,
        l.IsEnd AS isEnd,
        w1.ID AS fromId,
        w1.Ident AS fromIdent,
        w1.Latitude AS fromLat,
        w1.Longtitude AS fromLon,
        w2.ID AS toId,
        w2.Ident AS toIdent,
        w2.Latitude AS toLat,
        w2.Longtitude AS toLon
      FROM AirwayLegs l
      JOIN Airways a ON a.ID = l.AirwayID
      JOIN Waypoints w1 ON w1.ID = l.Waypoint1ID
      JOIN Waypoints w2 ON w2.ID = l.Waypoint2ID
      WHERE l.Level IN ('H', 'B')
        AND w1.Latitude IS NOT NULL AND w1.Longtitude IS NOT NULL
        AND w2.Latitude IS NOT NULL AND w2.Longtitude IS NOT NULL
    `).all();

    const nodes = new Map();
    const adj = new Map();

    const addNode = (id, ident, lat, lon) => {
      if (!nodes.has(id)) {
        nodes.set(id, { id, ident, lat, lon });
        adj.set(id, []);
      }
    };

    for (const r of rows) {
      addNode(r.fromId, r.fromIdent, r.fromLat, r.fromLon);
      addNode(r.toId, r.toIdent, r.toLat, r.toLon);
      const distance = distanceNM(r.fromLat, r.fromLon, r.toLat, r.toLon);
      const base = {
        legId: r.legId,
        airwayId: r.airwayId,
        airway: r.airwayIdent,
        level: r.level,
        isStart: Boolean(r.isStart),
        isEnd: Boolean(r.isEnd),
        direction: 'forward',
        distance,
        fromIdent: r.fromIdent,
        toIdent: r.toIdent
      };
      adj.get(r.fromId).push({ ...base, from: r.fromId, to: r.toId });
    }

    return { nodes, adj, edgeCount: rows.length, directed: true };
  }

  getProcedureCandidates(airport, proc, graphNodeIds, direction) {
    const terminals = this.statements.terminalsByAirportProc.all(airport.ID, proc);
    const candidates = [];
    const seen = new Map();

    for (const terminal of terminals) {
      const legs = this.statements.termLegs.all(terminal.ID).filter((leg) => leg.WptID && leg.Latitude !== null && leg.Longtitude !== null);
      if (legs.length === 0) continue;

      const graphIndexes = [];
      for (let i = 0; i < legs.length; i++) {
        if (graphNodeIds.has(legs[i].WptID)) graphIndexes.push(i);
      }
      if (graphIndexes.length === 0) continue;

      const index = direction === 'sid' ? graphIndexes[graphIndexes.length - 1] : graphIndexes[0];
      const waypoint = legs[index];
      const path = direction === 'sid' ? legs.slice(0, index + 1) : legs.slice(index);
      const distance = procedureDistanceNM(airport, path, direction);
      const candidate = {
        terminalId: terminal.ID,
        procedure: terminal.FullName,
        runway: terminal.Rwy,
        waypointId: waypoint.WptID,
        waypointIdent: waypoint.Ident,
        distance,
        path: path.map((p) => ({ id: p.WptID, ident: p.Ident, lat: p.Latitude, lon: p.Longtitude }))
      };

      const key = `${candidate.waypointId}`;
      const prev = seen.get(key);
      if (!prev || candidate.distance < prev.distance) seen.set(key, candidate);
    }

    for (const candidate of seen.values()) candidates.push(candidate);
    candidates.sort((a, b) => a.distance - b.distance);
    return candidates;
  }
}

function procedureDistanceNM(airport, path, direction) {
  let total = 0;
  if (path.length === 0) return total;

  if (direction === 'sid') {
    total += distanceNM(airport.Latitude, airport.Longtitude, path[0].Latitude, path[0].Longtitude);
  }

  for (let i = 1; i < path.length; i++) {
    total += distanceNM(path[i - 1].Latitude, path[i - 1].Longtitude, path[i].Latitude, path[i].Longtitude);
  }

  if (direction === 'star') {
    const last = path[path.length - 1];
    total += distanceNM(last.Latitude, last.Longtitude, airport.Latitude, airport.Longtitude);
  }

  return total;
}

module.exports = { NavdataRepository, resolveNavdataPath, DEFAULT_DB_PATH };