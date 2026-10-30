/**
 * CTYFLY 全站冒烟：逐个路由检查
 *   - 页面无 JS 异常、无 5xx 响应、不被踢回 /login
 *   - 页面确实渲染出内容，正文长度低于阈值判失败
 *   - 需要登录的页面顺带验证桌宠图片能加载，naturalWidth 必须大于 0
 *
 * 环境变量：
 *   SMOKE_BASE        站点根地址，默认 https://test.ccflysim.cn
 *   SMOKE_TOKEN_FILE  包含管理员令牌的文件，二选一
 *   SMOKE_TOKEN       直接传管理员令牌，二选一
 *   SMOKE_BROWSER     浏览器可执行文件路径；不传时自动探测本机 Edge 或 Chrome
 *   SMOKE_OUT         截图与报告输出目录，默认系统临时目录下的 ctyfly-smoke
 *   SMOKE_TIMEOUT     单页超时毫秒，默认 30000
 */
const { chromium } = require('playwright-core');
const fs = require('fs');
const os = require('os');
const path = require('path');

function resolveBrowser() {
  if (process.env.SMOKE_BROWSER) return process.env.SMOKE_BROWSER;
  const candidates = [
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ];
  const found = candidates.find((p) => fs.existsSync(p));
  if (!found) {
    throw new Error('未找到浏览器，请用 SMOKE_BROWSER 指定 Chromium 内核浏览器路径');
  }
  return found;
}

function resolveToken() {
  if (process.env.SMOKE_TOKEN) return process.env.SMOKE_TOKEN.trim();
  if (process.env.SMOKE_TOKEN_FILE) {
    return fs.readFileSync(process.env.SMOKE_TOKEN_FILE, 'utf8').trim();
  }
  throw new Error('缺少令牌：请设置 SMOKE_TOKEN_FILE 或 SMOKE_TOKEN');
}

const BROWSER = resolveBrowser();
const TOKEN = resolveToken();
const BASE = process.env.SMOKE_BASE || 'https://test.ccflysim.cn';
const OUT = process.env.SMOKE_OUT || path.join(os.tmpdir(), 'ctyfly-smoke');
const TIMEOUT = Number(process.env.SMOKE_TIMEOUT || 30000);

/**
 * 静态路由清单。带参数的详情页不在冒烟范围，需要真实数据，容易误报。
 * 新增页面时同步把路径加到这里，这是冒烟覆盖面的唯一来源。
 */
const ROUTES = [
  '/', '/partners', '/cookies', '/privacy', '/terms', '/about', '/docs', '/status', '/changelog',
  '/login', '/register', '/forgot',
  '/home', '/weather/metar', '/weather/taf', '/weather/routes', '/nav/airport-map',
  '/events', '/events/history', '/airlines', '/airlines/leaderboard',
  '/va/routes', '/va/fleet', '/va/shop', '/va/dispatch', '/va/pirep',
  '/wallet', '/shop', '/bids', '/market', '/achievements', '/incidents',
  '/apply/controller', '/apply/staff', '/tickets', '/tickets/new', '/profile',
  '/admin/stats', '/admin/users', '/admin/permissions', '/admin/approvals',
  '/admin/applications/controller', '/admin/applications/staff',
  '/admin/airlines', '/admin/events', '/admin/tickets', '/admin/notices',
  '/admin/partners', '/admin/shop', '/admin/surveys', '/admin/banned-ips', '/admin/airline-funds',
  '/admin/logs-login', '/admin/logs-register', '/admin/logs-network', '/admin/logs-audit',
];
const GUEST_PAGES = ['/login', '/register', '/forgot'];

(async () => {
  const browser = await chromium.launch({ executablePath: BROWSER, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
  await ctx.addInitScript((token) => {
    localStorage.setItem('ctyfly_token', token);
    localStorage.setItem('ctyfly_tour_v1', '1');
    localStorage.setItem('ctyfly_cookie_ok', '1');
  }, TOKEN);
  const page = await ctx.newPage();

  let errs = [];
  let bad5xx = [];
  page.on('pageerror', (e) => errs.push(String(e).slice(0, 140)));
  page.on('response', (r) => { if (r.status() >= 500) bad5xx.push(`${r.status()} ${r.url().slice(0, 90)}`); });

  const rows = [];
  let failed = 0;
  for (const route of ROUTES) {
    errs = [];
    bad5xx = [];
    let ok = true;
    const notes = [];
    try {
      await page.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: TIMEOUT });
      await page.waitForTimeout(1500);
      const info = await page.evaluate(() => {
        const app = document.querySelector('#app') || document.body;
        const text = (app.innerText || '').trim();
        const petImg = document.querySelector('.deskpet-img');
        return {
          url: location.pathname,
          len: text.length,
          snippet: text.slice(0, 40).replace(/\s+/g, ' '),
          pet: petImg ? (petImg.getAttribute('src') || '') : '',
          petOk: petImg ? (petImg.complete && petImg.naturalWidth > 0) : null,
        };
      });
      const isGuestPage = GUEST_PAGES.includes(route);
      if (!isGuestPage && info.url === '/login') { ok = false; notes.push('被踢回登录页'); }
      if (info.len < 60) { ok = false; notes.push(`正文仅 ${info.len} 字`); }
      if (errs.length) { ok = false; notes.push(`JS异常 ${errs.length}: ${errs[0]}`); }
      if (bad5xx.length) { ok = false; notes.push(`5xx ${bad5xx[0]}`); }
      if (info.pet && !info.petOk) { ok = false; notes.push('桌宠图片未加载'); }
      notes.push(`正文${info.len}字${info.pet ? ' 宠物✓' : ''}`);
      rows.push({ route, ok, note: notes.join(' | '), snippet: info.snippet });
    } catch (e) {
      rows.push({ route, ok: false, note: '导航异常: ' + String(e).slice(0, 90), snippet: '' });
    }
    if (!rows[rows.length - 1].ok) failed++;
    console.log(`  ${rows[rows.length - 1].ok ? '✓' : '✗'} ${route.padEnd(30)} ${rows[rows.length - 1].note}`);
  }

  // 代表性截图留档，便于翻看布局是否整体错乱
  fs.mkdirSync(OUT, { recursive: true });
  for (const [route, name] of [['/home', 'home'], ['/admin/stats', 'admin-stats']]) {
    await page.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: TIMEOUT });
    await page.waitForTimeout(2200);
    await page.screenshot({ path: path.join(OUT, `smoke-${name}.png`) });
  }

  console.log('\n=== 结论 ===');
  console.log(failed ? `✗ ${failed}/${ROUTES.length} 页有问题` : `✓ 全部 ${ROUTES.length} 页通过`);
  fs.writeFileSync(path.join(OUT, 'smoke-report.json'), JSON.stringify(rows, null, 2));
  console.log(`报告目录: ${OUT}`);
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch((e) => {
  console.error('脚本异常:', e);
  process.exit(2);
});
