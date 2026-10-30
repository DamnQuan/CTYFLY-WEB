#!/usr/bin/env node

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const {
  PlannerService,
  RouteInputError,
  RouteNotFoundError
} = require('./lib/planner-service');
const { MetarService } = require('./lib/metar-service');

const HOST = process.env.HOST || '127.0.0.1';
const PORT = Number(process.env.PORT) || 4173;
const ROOT = global.__APP_ROOT || __dirname;

const STATIC_FILES = new Map([
  ['/', ['public/index.html', 'text/html; charset=utf-8']],
  ['/index.html', ['public/index.html', 'text/html; charset=utf-8']],
  ['/app.js', ['public/app.js', 'text/javascript; charset=utf-8']],
  ['/styles.css', ['public/styles.css', 'text/css; charset=utf-8']],
  ['/vendor/leaflet/leaflet.js', ['node_modules/leaflet/dist/leaflet.js', 'text/javascript; charset=utf-8']],
  ['/vendor/leaflet/leaflet.css', ['node_modules/leaflet/dist/leaflet.css', 'text/css; charset=utf-8']],
  ['/vendor/leaflet/images/layers.png', ['node_modules/leaflet/dist/images/layers.png', 'image/png']],
  ['/vendor/leaflet/images/layers-2x.png', ['node_modules/leaflet/dist/images/layers-2x.png', 'image/png']],
  ['/vendor/leaflet/images/marker-icon.png', ['node_modules/leaflet/dist/images/marker-icon.png', 'image/png']],
  ['/vendor/leaflet/images/marker-icon-2x.png', ['node_modules/leaflet/dist/images/marker-icon-2x.png', 'image/png']],
  ['/vendor/leaflet/images/marker-shadow.png', ['node_modules/leaflet/dist/images/marker-shadow.png', 'image/png']]
]);

function createAppServer(service = new PlannerService(), metarService = new MetarService()) {
  return http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url, 'http://localhost');

      if (request.method === 'GET' && url.pathname === '/api/status') {
        return sendJson(response, 200, service.getStatus());
      }

      if (request.method === 'GET' && url.pathname === '/api/airports') {
        const query = url.searchParams.get('q') || '';
        const airports = query.trim() ? service.searchAirports(query, 8) : [];
        return sendJson(response, 200, { airports });
      }

      const metarMatch = url.pathname.match(/^\/api\/airports\/([A-Z0-9]{3,4})\/metar$/i);
      if (request.method === 'GET' && metarMatch) {
        return sendJson(response, 200, await metarService.get(metarMatch[1]));
      }

      const detailsMatch = url.pathname.match(/^\/api\/airports\/([A-Z0-9]{3,4})\/details$/i);
      if (request.method === 'GET' && detailsMatch) {
        return sendJson(response, 200, service.getAirportDetails(detailsMatch[1]));
      }

      const windMatch = url.pathname.match(/^\/api\/airports\/([A-Z0-9]{3,4})\/wind$/i);
      if (request.method === 'GET' && windMatch) {
        const metar = await metarService.get(windMatch[1]);
        return sendJson(response, 200, service.getRunwayWind(windMatch[1], metar));
      }

      const recommendMatch = url.pathname.match(/^\/api\/airports\/([A-Z0-9]{3,4})\/recommend$/i);
      if (request.method === 'GET' && recommendMatch) {
        const metar = await metarService.get(recommendMatch[1]);
        const dest = (url.searchParams.get('dest') || '').trim().toUpperCase();
        return sendJson(response, 200, service.recommendOrigin(recommendMatch[1], dest || null, metar));
      }

      const recommendDestMatch = url.pathname.match(/^\/api\/airports\/([A-Z0-9]{3,4})\/recommendDest$/i);
      if (request.method === 'GET' && recommendDestMatch) {
        const metar = await metarService.get(recommendDestMatch[1]);
        const origin = (url.searchParams.get('origin') || '').trim().toUpperCase();
        return sendJson(response, 200, service.recommendDestination(recommendDestMatch[1], origin || null, metar));
      }

      if (request.method === 'POST' && url.pathname === '/api/routes/analyze') {
        const body = await readJsonBody(request);
        return sendJson(response, 200, service.analyzeRoute(body.route || '', {
          origin: normalizeIcao(body.origin),
          destination: normalizeIcao(body.destination)
        }));
      }

      if (request.method === 'POST' && url.pathname === '/api/routes') {
        const body = await readJsonBody(request);
        const origin = normalizeIcao(body.origin);
        const destination = normalizeIcao(body.destination);
        if (!origin || !destination) {
          return sendJson(response, 400, { error: '请输入有效的起飞和到达机场代码' });
        }
        const options = {
          originRunway: body.originRunway || null,
          destinationRunway: body.destinationRunway || null,
          sid: body.sid || null,
          star: body.star || null
        };
        return sendJson(response, 200, service.plan(origin, destination, options));
      }

      if (request.method === 'GET' || request.method === 'HEAD') {
        const staticFile = STATIC_FILES.get(url.pathname);
        if (staticFile) return sendFile(response, staticFile, request.method === 'HEAD');
      }

      sendJson(response, 404, { error: '资源不存在' });
    } catch (error) {
      if (error instanceof SyntaxError || error.code === 'INVALID_BODY') {
        return sendJson(response, 400, { error: '请求内容不是有效的 JSON' });
      }
      if (error instanceof RouteInputError) {
        return sendJson(response, 400, { error: error.message });
      }
      if (error instanceof RouteNotFoundError) {
        return sendJson(response, 422, { error: error.message });
      }
      if (error.message?.startsWith('Airport not found:')) {
        return sendJson(response, 404, { error: `导航数据中没有机场 ${error.message.split(': ')[1]}` });
      }
      console.error(error);
      sendJson(response, 500, { error: '航路计算失败，请查看服务端日志' });
    }
  });
}

function normalizeIcao(value) {
  const result = String(value || '').trim().toUpperCase();
  return /^[A-Z0-9]{3,4}$/.test(result) ? result : null;
}

async function readJsonBody(request) {
  let body = '';
  for await (const chunk of request) {
    body += chunk;
    if (Buffer.byteLength(body) > 16 * 1024) {
      const error = new Error('Request body is too large');
      error.code = 'INVALID_BODY';
      throw error;
    }
  }
  return JSON.parse(body || '{}');
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-store'
  });
  response.end(body);
}

function sendFile(response, file, headOnly) {
  const [relativePath, contentType] = file;
  const embedded = global.__EMBEDDED_ASSETS?.[relativePath];
  if (embedded) {
    const content = Buffer.from(embedded, 'base64');
    response.writeHead(200, {
      'Content-Type': contentType,
      'Content-Length': content.length,
      'Cache-Control': relativePath.startsWith('node_modules') ? 'public, max-age=86400' : 'no-cache'
    });
    response.end(headOnly ? undefined : content);
    return;
  }
  fs.readFile(path.join(ROOT, relativePath), (error, content) => {
    if (error) return sendJson(response, 404, { error: '资源不存在' });
    response.writeHead(200, {
      'Content-Type': contentType,
      'Content-Length': content.length,
      'Cache-Control': relativePath.startsWith('node_modules') ? 'public, max-age=86400' : 'no-cache'
    });
    response.end(headOnly ? undefined : content);
  });
}

function startApp(options = {}) {
  const host = options.host || HOST;
  const port = Number(options.port) || PORT;
  const service = new PlannerService({ dbPath: options.dbPath || process.env.NAVDATA_DB });
  const status = service.initialize();
  const server = createAppServer(service);
  server.listen(port, host, () => {
    const url = `http://${host}:${port}`;
    console.log(`AIRAC ${status.cycle}: ${status.waypointCount} waypoints, ${status.airwayLegCount} directed airway legs`);
    console.log(`Navdata: ${status.database}`);
    console.log(`Web planner: ${url}`);
    if (options.openBrowser) openBrowser(url);
  });

  const shutdown = () => server.close(() => {
    service.close();
    process.exit(0);
  });
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
  return { server, service, status };
}

function openBrowser(url) {
  if (process.platform === 'win32') {
    const child = spawn('cmd.exe', ['/d', '/s', '/c', `start "" "${url}"`], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true
    });
    child.unref();
  }
}

if (require.main === module) {
  startApp();
}

module.exports = { createAppServer, normalizeIcao, startApp };