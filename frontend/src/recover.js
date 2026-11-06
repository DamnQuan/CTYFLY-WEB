/**
 * 部署后旧页面自恢复
 *
 * 背景：前端每次重新构建，产物文件名里的 hash 都会变化，旧文件随之被删除。
 * 如果用户的浏览器还停留在构建前的页面上，点击路由时 Vue Router 会去加载
 * 已经不存在的旧 chunk，/assets/xxx-旧 hash.js→ 404 → 动态 import 被拒，
 * 导航静默失败，界面表现为「点不动、必须刷新」。
 *
 * 这里捕获这类错误并自动整页加载目标路由：整页加载会重新取 index.html，
 * 从而拿到当前构建的 chunk 名称，用户无需手动刷新。
 */

const CHUNK_ERROR_RE = new RegExp([
  'Failed to fetch dynamically imported module',
  'Importing a module script failed',
  'error loading dynamically imported module',
  'Unable to preload CSS',
].join('|'), 'i');

const TS_KEY = 'ctyfly_recover_ts';
const THROTTLE_MS = 10000;   // 10 秒内只自动恢复一次，避免异常情况下反复整页重载

export function isChunkLoadError(error) {
  if (!error) return false;
  const message = typeof error === 'string' ? error : (error.message || String(error));
  return CHUNK_ERROR_RE.test(message);
}

function recentlyRecovered() {
  try {
    const last = Number(sessionStorage.getItem(TS_KEY) || 0);
    return Date.now() - last < THROTTLE_MS;
  } catch {
    return false;
  }
}

function markRecovered() {
  try { sessionStorage.setItem(TS_KEY, String(Date.now())); } catch { /* 忽略 */ }
}

/** 应用正常启动/导航成功后调用：允许后续的部署再次触发自恢复 */
export function markAppHealthy() {
  try { sessionStorage.removeItem(TS_KEY); } catch { /* 忽略 */ }
}

/** 恢复/更新提示条，可更新文案，已存在则复用*/
function showReloadBanner(text = '站点已更新，点此刷新以继续') {
  let el = document.getElementById('ctyfly-reload-banner');
  if (!el) {
    el = document.createElement('div');
    el.id = 'ctyfly-reload-banner';
    el.setAttribute(
      'style',
      'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:99999;'
      + 'padding:10px 20px;border-radius:980px;background:#0071e3;color:#fff;cursor:pointer;'
      + 'font:500 14px/1.4 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;'
      + 'box-shadow:0 10px 30px rgba(0,113,227,.35)',
    );
    el.addEventListener('click', () => window.location.reload());
    document.body.appendChild(el);
  }
  el.textContent = text;
}

/**
 * 恢复：整页加载 target，缺省为当前地址
 * @returns {boolean} 是否已触发自动恢复
 */
export function recoverFromStaleChunk(target) {
  if (recentlyRecovered()) {
    showReloadBanner();
    return false;
  }
  markRecovered();
  window.location.assign(target || window.location.href);
  return true;
}

/** 安装全局捕获：Vite 预加载失败 + 未处理的 import 拒绝 */
export function installRecovery() {
  const here = () => window.location.pathname + window.location.search;

  // Vite 会为 modulepreload / 动态导入的静态资源失败派发该事件
  window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault();
    recoverFromStaleChunk(here());
  });

  window.addEventListener('unhandledrejection', (event) => {
    if (isChunkLoadError(event.reason)) recoverFromStaleChunk(here());
  });
}

/* ---------- 新构建主动检测 ---------- */

let knownBuild = '';
let watched = false;
let lastInteraction = 0;
let updateApplied = false;

/** 是否适合自动刷新：不在输入、没有弹窗、且已停止操作一小会儿 */
function canAutoReload() {
  if (document.hidden || updateApplied) return false;
  const el = document.activeElement;
  const tag = el?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || el?.isContentEditable) return false;
  if (document.querySelector('.modal-mask, .sm-panel, .dp-pop')) return false;
  // 20 秒内有过操作就再等等，避免打断，例如刚填完表单切到别处查看
  return Date.now() - lastInteraction > 20000;
}

/** 发现新构建：能安全刷新就自动应用，否则给出可点击的提示条 */
function applyUpdate() {
  if (updateApplied) return;
  if (canAutoReload()) {
    updateApplied = true;
    showReloadBanner('站点已更新，正在自动刷新中，不要着急~');
    setTimeout(() => window.location.reload(), 900);
    return;
  }
  showReloadBanner('站点已更新，点此刷新以继续');
}

let lastCheck = 0;

async function checkBuild() {
  // 去抖：首次加载时「定时器 + focus + visibilitychange」会几乎同时触发，
  // 之前同一秒会打出 3~4 次 /api/version。弱网下这些都是纯浪费，5 秒内只查一次。
  const now = Date.now();
  if (now - lastCheck < 5000) return;
  lastCheck = now;

  try {
    const resp = await fetch('/api/version', { headers: { Accept: 'application/json' } });
    if (!resp.ok) return;
    const { build } = await resp.json();
    if (!build) return;
    if (!knownBuild) {
      knownBuild = build;      // 首次只记录基线
      return;
    }
    if (build !== knownBuild) {
      knownBuild = build;
      applyUpdate();
    }
  } catch { /* 网络异常忽略，不影响使用 */ }
}

/**
 * 定时/切回标签页时检查是否发布了新构建：
 * 空闲时直接自动刷新到最新版本，避免用户一直停在旧代码上，
 * 正在输入或有弹窗时改为提示条，绝不打断正在做的事。
 */
export function watchForNewBuild() {
  if (watched) return;
  watched = true;
  const markInteraction = () => { lastInteraction = Date.now(); };
  for (const ev of ['pointerdown', 'keydown', 'wheel']) {
    window.addEventListener(ev, markInteraction, { passive: true });
  }
  lastInteraction = Date.now();
  checkBuild();
  setInterval(checkBuild, 120000);                       // 2 分钟
  window.addEventListener('focus', checkBuild);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) checkBuild();
  });
}
