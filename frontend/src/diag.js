/**
 * 运行时自检
 *
 * 显示策略：只有「崩溃级」问题才主动弹出 iOS 风格毛玻璃提示
 * 未捕获异常、异步异常、导航失败、视图未跟随路由。
 * 卡顿、后台节流、点击落点等只静默记录到 localStorage，
 * 需要时按 Ctrl+Shift+D 主动查看，平时绝不打扰用户。
 *
 * 记录来源：
 * - 心跳间隔，setInterval 300ms 实测间隔，超过阈值说明主线程被占死
 * - window error / unhandledrejection
 * - PerformanceObserver longtask，支持的浏览器上更精确
 */
import { showToast } from './utils.js';

const STORE_KEY = 'ctyfly_diag_v1';
const HEARTBEAT_MS = 300;
const STALL_MS = 1200;        // 超过此时长视为一次卡顿
const MAX_ENTRIES = 30;

/** 构建标识由 vite.config.js 注入，面板上会显示，用于确认浏览器跑的是哪一版 */
const BUILD_ID = typeof __BUILD_ID__ === 'string' ? __BUILD_ID__ : 'dev';

/** 崩溃级问题类型：只有这些才会主动弹出提示，其余一律静默记录 */
const CRASH_KINDS = new Set([
  'JS 错误',
  '未处理的异步异常',
  '导航失败',
  '视图未跟随路由',
]);

/** 已弹过的错误，同一错误只弹一次，避免刷屏*/
const shownErrors = new Set();

let entries = [];
let started = false;

function load() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function save() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(entries.slice(-MAX_ENTRIES)));
  } catch { /* 存储不可用时放弃持久化 */ }
}

function nowText() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function record(kind, detail) {
  const entry = { t: nowText(), kind, detail: String(detail).slice(0, 300) };
  entries.push(entry);
  save();
  return entry;
}

/** 供外部，如路由错误处理写入一条可见的诊断记录*/
export function recordDiagEvent(kind, detail) {
  return record(kind, detail);
}

/* ---------- 诊断弹层，iOS 风格毛玻璃，纯 DOM，不依赖框架 ----------
 * 只在「崩溃级」问题出现时才弹出：未捕获异常、导航失败、视图与路由失同步。
 * 卡顿、后台节流、点击拦截等只静默记录，需要时按 Ctrl+Shift+D 主动查看。*/

const WARN_SVG = '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor"'
  + ' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/>'
  + '<path d="M12 9v4"/><path d="M12 17h.01"/></svg>';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** 关闭当前诊断弹层 */
export function closeDiagSheet() {
  document.getElementById('ctyfly-diag-sheet')?.remove();
}

/**
 * 展示诊断弹层
 * @param {string} title  标题
 * @param {string[]} lines 正文行
 * @param {{sub?: string, warn?: boolean, actions?: Array<{label:string, primary?:boolean, onClick:Function}>}} opts
 */
function sheet(title, lines, opts = {}) {
  closeDiagSheet();

  const mask = el('div', 'diag-mask');
  mask.id = 'ctyfly-diag-sheet';
  const card = el('div', 'diag-sheet');

  const badge = el('div', `diag-badge${opts.warn ? ' is-warn' : ''}`);
  badge.innerHTML = WARN_SVG;

  const body = el('div', 'diag-body', lines.join('\n'));
  const meta = el('div', 'diag-meta', `构建版本 ${BUILD_ID}`);
  const actions = el('div', 'diag-actions');

  const copyText = `${title}\n${lines.join('\n')}\n 构建版本 ${BUILD_ID}`;
  const copyBtn = el('button', 'btn btn-ghost', '复制信息');
  copyBtn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(copyText);
      copyBtn.textContent = '已复制';
    } catch {
      copyBtn.textContent = '请手动复制';
      body.style.userSelect = 'text';
      window.getSelection()?.selectAllChildren(body);
    }
  });

  const closeBtn = el('button', 'btn btn-primary', '知道了');
  closeBtn.addEventListener('click', closeDiagSheet);

  actions.append(copyBtn, closeBtn);
  if (opts.actions?.length) {
    for (const a of opts.actions) {
      const btn = el('button', `btn ${a.primary ? 'btn-primary' : 'btn-ghost'}`, a.label);
      btn.addEventListener('click', a.onClick);
      actions.append(btn);
    }
  }

  card.append(badge, el('div', 'diag-title', title));
  if (opts.sub) card.append(el('div', 'diag-sub', opts.sub));
  card.append(body, meta, actions);
  mask.append(card);
  // 点遮罩空白处也可关闭
  mask.addEventListener('mousedown', (e) => { if (e.target === mask) closeDiagSheet(); });
  document.body.appendChild(mask);
}

/** 保持旧调用名兼容：仅供崩溃级场景使用 */
export function showDiagPanel(title, lines, opts) {
  sheet(title, lines, opts);
}

/** 主动查看：汇总本次会话记录，Ctrl+Shift+D*/
export function showDiagReport() {
  const stalls = entries.filter((x) => x.kind === '界面卡顿' || x.kind === '长任务');
  const lines = [
    `本次会话记录 ${entries.length} 条`,
    stalls.length ? `其中前台卡顿 ${stalls.length} 次` : '无前台卡顿',
    '',
    ...(entries.length ? entries.slice(-14).map((x) => `${x.t} ${x.kind}：${x.detail}`) : ['暂无记录']),
  ];
  sheet('运行诊断信息', lines, { warn: true, sub: '仅在需要排查时使用，可复制后发给开发者' });
}

/* ---------- 采集 ---------- */

function captureGlobalErrors() {
  window.addEventListener('error', (e) => {
    const target = e.target;
    // 资源，图片/脚本加载失败也会走这里，单独标注便于区分
    if (target && target !== window && (target.src || target.href)) {
      record('资源加载失败', `${target.tagName} ${target.src || target.href}`.slice(0, 220));
      return;
    }
    const message = e.message || '未知错误';
    record('JS 错误', message);
    // 崩溃级：首次出现即弹出，同一错误只弹一次，避免刷屏
    if (!shownErrors.has(message)) {
      shownErrors.add(message);
      sheet('页面出错了', [
        message,
        e.filename ? `${e.filename}:${e.lineno ?? ''}` : '',
      ].filter(Boolean), { sub: '该错误已被记录，可复制后反馈给开发者' });
    }
  }, true);

  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason;
    const message = (r && (r.stack || r.message)) || String(r);
    record('未处理的异步异常', message);
    const key = message.slice(0, 120);
    if (!shownErrors.has(key)) {
      shownErrors.add(key);
      sheet('异步操作出错', [message], { sub: '该错误已被记录，可复制后反馈给开发者' });
    }
  });
}

function captureLongTasks() {
  try {
    if (!('PerformanceObserver' in window)) return;
    const obs = new PerformanceObserver((list) => {
      for (const item of list.getEntries()) {
        if (item.duration >= STALL_MS) {
          record('长任务', `${Math.round(item.duration)}ms`);
        }
      }
    });
    obs.observe({ type: 'longtask', buffered: false });
  } catch { /* 不支持 longtask 的环境忽略 */ }
}

/* ---------- 点击拦截探测器 ----------
 * 症状「时钟还在走、但整页点不动」的典型原因：
 * 1 一个看不见的全屏遮罩挡在最上层吞掉点击，如未卸载的弹窗蒙层；
 * 2 路由卡在半路，内容区空白，点击全部落在布局容器上；
 * 3 某段同步 JS 把主线程占死，此时时钟也会停，且本探测器无法触发。
 * 用捕获阶段监听：哪怕点击被吞掉，也能记录到点击实际落在哪个元素上。*/
function watchClickInterception() {
  let recent = [];

  window.addEventListener('click', (e) => {
    if (!(e.target instanceof Element)) return;
    const node = e.target;
    const rect = node.getBoundingClientRect();
    const covers =
      rect.width >= window.innerWidth * 0.6 && rect.height >= window.innerHeight * 0.5;
    const name = `<${node.tagName.toLowerCase()}`
      + `${node.id ? '#' + node.id : ''}`
      + ` class="${String(node.className).slice(0, 80)}">`;

    recent.push(name);
    recent = recent.slice(-6);

    // 连续 4 次点击落在同一个元素上：只静默记录，不弹窗，避免误报打扰用户
    if (recent.length >= 4 && recent.every((x) => x === recent[0])) {
      record('点击落在同一元素', recent[0] + (covers ? '全屏遮挡' : ''));
      recent = [];
    }
  }, true);
}

function startHeartbeat() {
  let last = Date.now();
  let hiddenSince = null;      // 标签页何时离开前台
  let hiddenTotal = 0;         // 本次间隔内处于后台的累计时长

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      hiddenSince = Date.now();
    } else {
      if (hiddenSince) hiddenTotal += Date.now() - hiddenSince;
      hiddenSince = null;
    }
  });

  setInterval(() => {
    const now = Date.now();
    const gap = now - last;
    last = now;
    if (gap < STALL_MS) return;

    // 标签页在后台时，Chrome 会把定时器降频到约每分钟一次，
    // 心跳间隔会假性拉长到几十秒——这不是卡顿，单独归类、不报警
    const inBackground = document.hidden || hiddenTotal > gap * 0.5;
    if (inBackground) {
      hiddenTotal = 0;
      record('后台标签页节流', `${(gap / 1000).toFixed(1)}s，浏览器对后台页降频，非卡顿`);
      return;
    }
    hiddenTotal = 0;

    // 前台卡顿只静默记录，不弹窗，按 Ctrl+Shift+D 可主动查看
    record('界面卡顿', `${(gap / 1000).toFixed(1)}s`);
  }, HEARTBEAT_MS);
}

/* ---------- 对外接口 ---------- */

/** 开始采集，应用启动时调用一次*/
export function installDiag() {
  if (started) return;
  started = true;
  // 读取的是上一次会话留下的记录，随后清空，避免跨会话重复累计
  entries = load();
  try { localStorage.removeItem(STORE_KEY); } catch { /* 忽略 */ }
  captureGlobalErrors();
  captureLongTasks();
  watchClickInterception();
  startHeartbeat();
  // Ctrl+Shift+D：主动查看本次会话的诊断记录，平时不打扰
  window.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'd') {
      e.preventDefault();
      showDiagReport();
    }
  });
}

/** 汇报上一次会话的崩溃级问题，仅有真实的错误/异常时才弹出，否则保持安静*/
export function reportPreviousSession() {
  const prev = entries.filter((x) => CRASH_KINDS.has(x.kind));
  if (!prev.length) return false;
  const lines = [
    ...prev.slice(-10).map((x) => `${x.t} ${x.kind}：${x.detail}`),
  ];
  sheet('上次会话出现过问题', lines, {
    sub: '页面已恢复正常；按 Ctrl+Shift+D 可随时查看本次会话诊断',
  });
  return true;
}

/* ---------- 视图/路由同步看门狗 ----------
 * 路由已经切到新页面、但页面上仍显示旧内容时，视图切换被某个动画或异常卡住，
 * 这里在数秒内发现并自动恢复，同时留下记录。
 * 由 AppShell 调用，避免与 router 形成循环依赖。*/
export function installViewSync(router) {
  let mismatch = 0;
  setInterval(() => {
    const host = document.querySelector('[data-view-route]');
    if (!host || !router?.currentRoute?.value) return;
    const expected = router.currentRoute.value.fullPath;
    const actual = host.getAttribute('data-view-route');
    if (actual === expected) {
      mismatch = 0;
      return;
    }
    mismatch += 1;
    if (mismatch < 2) return;      // 连续两次不一致，约 6 秒才判定
    mismatch = 0;
    record('视图未跟随路由', `路由=${expected} 视图=${actual}`);
    sheet('页面未能跟随跳转', [
      `路由已切到：${expected}`,
      `页面仍显示：${actual}`,
      '',
      '正在自动重新加载该地址…',
    ], { sub: '页面出现异常，已自动恢复并记录' });
    window.setTimeout(() => window.location.assign(expected), 1400);
  }, 3000);
}

/* ---------- 站内导航兜底 ----------
 * 症状：点击侧边栏/按钮里的站内链接，点击事件确实派发了，主线程正常、时钟照走、
 * 无任何报错，但 Vue Router 毫无反应，页面停在原处，只能刷新。
 *
 * 这里在 window 层，不依赖任何 Vue 组件，路由失灵也依然有效做兜底：
 * 点了站内链接后若 2 秒内地址未变化，就绕过 SPA 路由，用整页加载直达目标地址，
 * 保证「点了就一定去得了」，而不是卡死在原页面。*/

let linkWatchInstalled = false;

export function watchLinkClicks() {
  if (linkWatchInstalled) return;
  linkWatchInstalled = true;

  window.addEventListener('click', (e) => {
    if (document.hidden) return;
    if (!(e.target instanceof Element)) return;
    const link = e.target.closest('a[href]');
    if (!link) return;
    if (link.target === '_blank') return;                       // 新标签打开，交由浏览器处理
    let url;
    try {
      url = new URL(link.href, window.location.href);
    } catch {
      return;
    }
    if (url.origin !== window.location.origin) return;          // 外链不管

    const before = window.location.pathname + window.location.search;
    if (url.pathname + url.search === before) return;           // 指向当前页，本就不需要跳转

    const target = url.pathname + url.search;
    setTimeout(() => {
      if (document.hidden) return;
      const after = window.location.pathname + window.location.search;
      if (after !== before) return;                             // SPA 路由已正常跳转

      // 路由没反应：记录 + 轻量提示 + 整页兜底跳转，不弹大弹层，避免打扰
      record('导航无响应，已整页跳转', `${link.getAttribute('href')}，原停留 ${before}`);
      showToast('当前页面响应异常，正在直接打开目标页面');
      window.location.assign(target);
    }, 2000);
  }, true);
}
