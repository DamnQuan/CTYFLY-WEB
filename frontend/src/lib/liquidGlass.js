/**
 * 液态玻璃引擎 v2.1 —— 分层完整材质。
 *
 * Apple HIG iOS 26：玻璃属于悬浮控制层；内容层玻璃必须克制、
 * 静止时零渲染、尊重「降低透明度」。v1，全屏 WebGL rAF 的教训：
 * 无性能护栏 + 从不验证最终状态 —— 本版逐条对冲。
 *
 * 分层，Tier：
 *   full —— 位移折射 + RGB 色散，3 通道 feDisplacementMap+ 指针追随高光。
 *            仅限悬浮导航层，顶栏/侧栏/弹层，全页 ≤ CA_CAP 个，上游
 *            liquid-glass 实测 5 个色散元素即可卡住 Chrome 合成器。
 *   lite —— 单通道位移折射 + 磨砂，无色散。内容卡片用；全页 ≤ DISP_CAP
 *            个，按可见面积取最大的若干，其余自动降级为纯 CSS 磨砂。
 *   basic —— 不注入滤镜，保持 CSS 磨砂：过小元素，标签/徽标、
 *            嵌套在玻璃内的玻璃，HIG：禁止玻璃叠玻璃、超出上限者。
 *
 * 光学：backdrop-filter: url #lg-f-N blur saturate。
 *   位移贴图按元素实际像素尺寸运行时 canvas 生成，圆角矩形 SDF +
 *   Apple Snell 边缘曲线 θI = asin 1-e/t ²，edgeFactor = -tan θT-θI，
 *   避免 feImage 拉伸方形贴图导致的非均匀折射带。
 *
 * 交互，.interactive 的对应物：指针追随高光 —— pointermove 经 rAF
 *   合流后只写两个 CSS 变量，绘制由合成器完成，无逐帧 JS 渲染。
 *
 * 回退链：CSS.supports 检测 → localStorage 开关，ctyfly-lg=off→
 *   prefers-reduced-transparency，动态挂/卸→ 任何异常 → 纯 CSS 磨砂。
 */

/* ---------- 全局参数，CSS px ----------*/
const PEAK_DISP = 12;      /* 边缘最大折射采样位移 */
const BEZEL_MIN = 12;      /* 折射带厚度下限 */
const DISP_CAP = 14;       /* 位移元素总上限，导航层 + 内容层*/
const CONTENT_CAP = 5;     /* 内容档位移元素上限，实测滚动成本 ≈ blur 半径×面积×数量*/
const MIN_SIZE = 56;       /* 小于该边长的元素不参与折射 */
const MAP_CAP_PX = 1.2e6;  /* 单张贴图光栅像素上限，超出自动降采样*/

/* 导航层。ca: true 仅给顶栏 —— 色散=3 倍位移通道，实测，无头 Edge，
   2800×1800 双元素全开 20fps vs 无色散 60fps，面积越大越贵；
   顶栏带最薄、折射最显眼，是唯一值得付色散钱的位置。
   wideMedia: 宽屏下跳过，桌面布局侧栏不与内容重叠，位移不可见还白烧帧
   minSize: 按目标覆盖全局最小尺寸，Toast 胶囊很矮也要参与*/
const CHROME = [
  /* 玻璃材质属于收拢后的内层胶囊 .topbar-shell——
     外层在页面顶部必须完全透明，与页面融合，折射/磨砂只属于收拢后的胶囊。
     顶栏滚动到 50px 阈值前壳层是透明的，此时引擎注入的 backdrop-filter 背后没有内容，观感不变。*/
  { sel: '.topbar-shell', blur: 16, saturate: 170, bezelRatio: 0.24, bezelCap: 26, k: 2, ca: true, tier: 'chrome' },
  // 顶部栏导航模式：与 .topbar 同档，保证两种布局观感一致。
  // 该元素只在用户切到顶部栏时存在，不影响侧边栏布局。
  { sel: '.topnav', blur: 16, saturate: 170, bezelRatio: 0.24, bezelCap: 26, k: 2, ca: true, tier: 'chrome' },
  { sel: '.sidebar', blur: 20, saturate: 165, bezelRatio: 0.24, bezelCap: 26, k: 1, ca: false, tier: 'chrome', wideSkip: true },
  { sel: '.modal-panel', blur: 24, saturate: 170, bezelRatio: 0.20, bezelCap: 30, k: 2, ca: false, tier: 'chrome' },
  /* 瞬态悬浮控件，HIG：菜单/通知同属玻璃层——小面积，standard 档即开*/
  { sel: '.toast', blur: 14, saturate: 170, bezelRatio: 0.5, bezelCap: 22, k: 1, ca: false, tier: 'chrome', minSize: 26 },
  { sel: '.sm-panel', blur: 22, saturate: 170, bezelRatio: 0.18, bezelCap: 24, k: 1, ca: false, tier: 'chrome', minSize: 36 },
];
/* 内容层，full 档：卡片 + 持续可见的大面积浮层。降模糊半径与贴图精度换滚动帧率*/
const CONTENT = [
  { sel: '.glass', blur: 12, saturate: 165, bezelRatio: 0.16, bezelCap: 20, k: 1, ca: false, tier: 'content' },
  { sel: '.tour-card', blur: 20, saturate: 165, bezelRatio: 0.16, bezelCap: 24, k: 1, ca: false, tier: 'content', minSize: 120 },
  { sel: '.consent-banner', blur: 22, saturate: 170, bezelRatio: 0.14, bezelCap: 22, k: 1, ca: false, tier: 'content', minSize: 120 },
];

const XLINK = 'http://www.w3.org/1999/xlink';
const SVGNS = 'http://www.w3.org/2000/svg';
/* 色散：RGB 折射率差按 UI 尺度夸张，皇冠玻璃物理差约 0.5%，v1 着色器用 0.94/1.06*/
const CA_R = 0.94;
const CA_B = 1.06;

/* Apple Snell 折射边缘曲线。e = 内距 px，thick = 折射带厚度。返回 0..1*/
function snellEdge(e, thick) {
  if (e >= thick) return 0;
  const ratio = Math.max(0, 1 - e / thick);
  const thetaI = Math.asin(ratio * ratio);
  const thetaT = Math.asin(Math.min(1, Math.sin(thetaI) / 1.4));
  return Math.max(0, -Math.tan(thetaT - thetaI));
}

/**
 * 生成位移贴图 dataURL：R = X 位移，G = Y 位移，128 = 中性。
 * feDisplacementMap scale 配为 2×PEAK_DISP ⇒ 边缘采样位移 = ±PEAK_DISP px。
 */
function buildDisplacementMap(w, h, radius, bezelRatio, bezelCap, k) {
  const thick = Math.max(BEZEL_MIN, Math.min(bezelCap, Math.min(w, h) * bezelRatio));
  const K = Math.max(1, Math.min(k || 1, w * h > MAP_CAP_PX ? 1 : 2));
  const cw = Math.max(1, Math.round(w * K));
  const ch = Math.max(1, Math.round(h * K));
  const cvs = document.createElement('canvas');
  cvs.width = cw;
  cvs.height = ch;
  const ctx = cvs.getContext('2d');
  if (!ctx) return null;
  const img = ctx.createImageData(cw, ch);
  const data = img.data;
  const r = Math.max(0, Math.min(radius, Math.min(w, h) / 2));
  const hw = w / 2;
  const hh = h / 2;

  /* 圆角矩形 SDF + 解析法线，CSS px，按 K 映射光栅坐标*/
  function sdf(px, py) {
    const dx = Math.abs(px - hw) - (hw - r);
    const dy = Math.abs(py - hh) - (hh - r);
    const sx = px >= hw ? 1 : -1;
    const sy = py >= hh ? 1 : -1;
    if (dx > 0 && dy > 0) {
      const len = Math.hypot(dx, dy);
      return { d: len - r, nx: (dx / (len || 1)) * sx, ny: (dy / (len || 1)) * sy };
    }
    if (dx > dy) return { d: dx - r, nx: sx, ny: 0 };
    return { d: dy - r, nx: 0, ny: sy };
  }

  let ptr = 0;
  for (let y = 0; y < ch; y++) {
    const py = (y + 0.5) / K;
    for (let x = 0; x < cw; x++) {
      const px = (x + 0.5) / K;
      const { d, nx, ny } = sdf(px, py);
      let br = 128;
      let bg = 128;
      if (d < 0) {
        const f = snellEdge(-d, thick);
        br = 128 + Math.round(127 * Math.max(-1, Math.min(1, f * nx)));
        bg = 128 + Math.round(127 * Math.max(-1, Math.min(1, f * ny)));
      }
      data[ptr++] = br;
      data[ptr++] = bg;
      data[ptr++] = 128;
      data[ptr++] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  try {
    return cvs.toDataURL('image/png');
  } catch {
    return null;
  }
}

/* 组装单个滤镜：feImage 贴图 + 位移，可选 RGB 三通道色散*/
function buildFilter(svg, id, withCA) {
  const filter = document.createElementNS(SVGNS, 'filter');
  filter.setAttribute('id', id);
  filter.setAttribute('filterUnits', 'userSpaceOnUse');
  filter.setAttribute('primitiveUnits', 'userSpaceOnUse');
  /* 贴图通道按 sRGB 解读：默认 linearRGB 会把中性灰 128 拉成非中性，
     导致无位移区域也发生扭曲 —— 必须显式声明 */
  filter.setAttribute('color-interpolation-filters', 'sRGB');
  const feImage = document.createElementNS(SVGNS, 'feImage');
  feImage.setAttribute('result', 'map');
  feImage.setAttribute('preserveAspectRatio', 'none');
  filter.appendChild(feImage);

  function disp(scale, result) {
    const fd = document.createElementNS(SVGNS, 'feDisplacementMap');
    fd.setAttribute('in', 'SourceGraphic');
    fd.setAttribute('in2', 'map');
    fd.setAttribute('scale', String(scale));
    fd.setAttribute('xChannelSelector', 'R');
    fd.setAttribute('yChannelSelector', 'G');
    if (result) fd.setAttribute('result', result);
    return fd;
  }
  function isolate(source, channel) {
    const m = document.createElementNS(SVGNS, 'feColorMatrix');
    m.setAttribute('in', source);
    const v = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0];
    v[0 + channel] = 1;   /* R 行 */
    v[5 + channel] = 1;   /* G 行 */
    v[10 + channel] = 1;  /* B 行 */
    m.setAttribute('type', 'matrix');
    m.setAttribute('values', v.join(' '));
    return m;
  }

  if (withCA) {
    /* 三通道各自位移后按屏幕混合，通道互斥，screen == 加法。
       每个 feDisplacementMap 都从 SourceGraphic 重新出发；
       feColorMatrix 隔离出单通道并显式命名，供 feBlend 引用。*/
    const channels = [
      { scale: 2 * PEAK_DISP * CA_R, ch: 0, name: 'chR' },
      { scale: 2 * PEAK_DISP, ch: 1, name: 'chG' },
      { scale: 2 * PEAK_DISP * CA_B, ch: 2, name: 'chB' },
    ];
    for (const c of channels) {
      filter.appendChild(disp(c.scale, 'disp_' + c.name));
      const m = isolate('disp_' + c.name, c.ch);
      m.setAttribute('result', c.name);
      filter.appendChild(m);
    }
    const blendRG = document.createElementNS(SVGNS, 'feBlend');
    blendRG.setAttribute('in', 'chR');
    blendRG.setAttribute('in2', 'chG');
    blendRG.setAttribute('mode', 'screen');
    blendRG.setAttribute('result', 'rg');
    filter.appendChild(blendRG);
    const blendB = document.createElementNS(SVGNS, 'feBlend');
    blendB.setAttribute('in', 'rg');
    blendB.setAttribute('in2', 'chB');
    blendB.setAttribute('mode', 'screen');
    filter.appendChild(blendB);
  } else {
    filter.appendChild(disp(2 * PEAK_DISP));
  }
  return filter;
}

export function initLiquidGlass() {
  /* Chromium 检测：不支持 url 混入 backdrop-filter 时整条声明无效*/
  let supported = false;
  try {
    supported = typeof CSS !== 'undefined' && CSS.supports
      && CSS.supports('backdrop-filter', 'url(#lg-probe) blur(2px) saturate(120%)');
  } catch {
    supported = false;
  }
  if (!supported) return null;

  /* 质量预设，localStorage ctyfly-lg，手动档永远优先：
     off —— 停用，低配机自救/调试
     low —— 仅导航层位移折射，无色散
     standard —— 导航层折射 + RGB 色散
     full —— 导航层 + 内容卡片位移折射
     auto 默认 —— 自适应：硬件预判起步，低配 CPU/内存 → low，触屏 → standard，
       桌面 → full，滚动时实测帧率 <45fps 自动降档，full→standard→low→css 纯 CSS 玻璃，
       降级结果缓存一周，ctyfly-lg-auto，一周后重测。降级只去掉肉眼几乎不可辨的层：
       卡片折射，背后是无特征渐变、色散，极细彩虹边、顶栏位移，磨砂/透明/高光保留。
     依据：Chromium 的 url backdrop-filter 走软件光栅路径，W3C svgwg#1142，
     每个折射元素都在滚动帧里全量重算 —— 数量必须由实测帧率约束。*/
  const DEFAULT_PREF = 'auto';
  let pref = DEFAULT_PREF;
  let manual = false;
  try {
    const p = localStorage.getItem('ctyfly-lg');
    if (p === 'off' || p === 'low' || p === 'standard' || p === 'full') { pref = p; manual = true; }
  } catch { /* 忽略 */ }
  if (pref === 'off') return null;
  const isAuto = pref === 'auto';

  function guessTier() {
    const nav = typeof navigator !== 'undefined' ? navigator : {};
    if ((nav.deviceMemory && nav.deviceMemory <= 2)
      || (nav.hardwareConcurrency && nav.hardwareConcurrency <= 2)) return 'low';
    try {
      /* 用主指针判断触屏设备，带触屏的笔记本主指针仍是鼠标，不会误降*/
      if (matchMedia('(pointer: coarse)').matches) return 'standard';
    } catch { /* 忽略 */ }
    return 'full';
  }
  function storedAutoTier() {
    try {
      const v = localStorage.getItem('ctyfly-lg-auto');
      if (!v) return null;
      const i = v.indexOf(':');
      if (i < 0) return null;
      const t = v.slice(0, i);
      const ts = Number(v.slice(i + 1));
      if (!['low', 'standard', 'full', 'css'].includes(t)) return null;
      if (!ts || Date.now() - ts > 7 * 864e5) return null;   /* 一周后重新探测 */
      return t;
    } catch {
      return null;
    }
  }
  let tier = manual ? pref : (storedAutoTier() || guessTier());
  let stopMonitor = null;

  const mqTransparency = typeof matchMedia === 'function'
    ? matchMedia('(prefers-reduced-transparency: reduce)')
    : null;
  /* 桌面布局，>860px 侧栏与内容并排、下方无滚动内容，位移折射不可见；
     窄屏侧栏变为覆盖式抽屉，才需要真玻璃。断点与 main.css 保持一致。*/
  const wideMq = typeof matchMedia === 'function' ? matchMedia('(min-width: 861px)') : null;

  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none;';
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('width', '0');
  svg.setAttribute('height', '0');
  host.appendChild(svg);
  /* 必须挂到文档上：游离树里的滤镜会让 url #id 悬空，
     整条 backdrop-filter 静默失效，浏览器不报错*/
  document.body.appendChild(host);

  const items = [];
  let resizeTimer = 0;
  let scanTimer = 0;
  let ro = null;
  let mo = null;

  function makeItem(el, opts, withCA, id) {
    const filter = buildFilter(svg, id, withCA);
    /* buildFilter 只负责组装，必须在此挂入文档内 svg —— 否则 url 悬空*/
    svg.appendChild(filter);
    el.style.webkitBackdropFilter = 'url(#' + id + ') blur(' + opts.blur + 'px) saturate(' + opts.saturate + '%)';
    el.style.backdropFilter = 'url(#' + id + ') blur(' + opts.blur + 'px) saturate(' + opts.saturate + '%)';
    el.setAttribute('data-lg', opts.tier + (withCA ? '+ca' : ''));
    el.classList.add('lg-spec');
    const item = { el, filter, feImage: filter.querySelector('feImage'), opts };
    items.push(item);
    refresh(item);
    if (ro) ro.observe(el);
    return item;
  }

  /* 候选筛选：跳过过小元素与「玻璃中的玻璃」 */
  function collect(sel, excludeSet, opts) {
    const min = (opts && opts.minSize) || MIN_SIZE;
    const out = [];
    let els;
    try {
      els = document.querySelectorAll(sel);
    } catch {
      return out;
    }
    els.forEach((el) => {
      if (excludeSet.has(el) || items.some((it) => it.el === el)) return;
      const r = el.getBoundingClientRect();
      if (r.width < min || r.height < min) return;
      const parent = el.parentElement;
      if (parent && parent.closest && parent.closest('[data-lg], .topbar-shell, .topbar, .sidebar, .modal-panel')) return;
      out.push({ el, area: r.width * r.height });
    });
    return out;
  }

  function releaseItem(it) {
    it.filter.remove();
    it.el.style.backdropFilter = '';
    it.el.style.webkitBackdropFilter = '';
    it.el.removeAttribute('data-lg');
    it.el.classList.remove('lg-spec');
    it.el.style.removeProperty('--lg-mx');
    it.el.style.removeProperty('--lg-my');
    if (ro) ro.unobserve(it.el);
  }

  function mount() {
    /* css 档：引擎完全退出，软重置已清光折射，后续补扫直接跳过，
       否则 MutationObserver 一扫又把折射挂回去，css 档永远稳不住*/
    if (tier === 'css') return;
    /* 档位随时可能被 auto 降级，每次挂载按当前 tier 决定折射范围 */
    const wantCA = tier !== 'low';
    const wantContent = tier === 'full';

    /* 先清退：已脱离文档的元素 / 宽屏下应让位给 CSS 静态模糊的侧栏。
       必须同时清掉内联样式 —— 内联 url 指向已移除的滤镜会悬空，
       让整条 backdrop-filter 静默失效，连 CSS 磨砂都一起没掉。*/
    for (let i = items.length - 1; i >= 0; i -= 1) {
      const it = items[i];
      const stale = !it.el.isConnected || (it.opts.wideSkip && wideMq && wideMq.matches);
      if (stale) {
        releaseItem(it);
        items.splice(i, 1);
      }
    }

    /* full 档：导航层，色散按目标配置，仅顶栏*/
    const claimed = new Set();
    for (const t of CHROME) {
      if (t.wideSkip && wideMq && wideMq.matches) continue;
      let els;
      try {
        els = document.querySelectorAll(t.sel);
      } catch {
        continue;
      }
      els.forEach((el) => {
        if (items.some((it) => it.el === el)) return;
        const min = t.minSize || MIN_SIZE;
        const r = el.getBoundingClientRect();
        if (r.width < min || r.height < min) return;
        claimed.add(el);
        makeItem(el, t, wantCA && t.ca, 'lg-f-' + items.length);
      });
    }

    /* 内容档：卡片与持续浮层，按面积从大到小补足，仅 full 预设；单独限量*/
    let contentLeft = wantContent
      ? Math.max(0, Math.min(CONTENT_CAP, DISP_CAP - items.length))
      : 0;
    if (contentLeft > 0) {
      const candidates = [];
      for (const t of CONTENT) {
        for (const c of collect(t.sel, claimed, t)) candidates.push({ ...c, opts: t });
      }
      candidates.sort((a, b) => b.area - a.area);
      for (const c of candidates.slice(0, contentLeft)) {
        makeItem(c.el, c.opts, false, 'lg-f-' + items.length);
      }
    }
  }

  function refresh(item) {
    const rect = item.el.getBoundingClientRect();
    const w = Math.round(rect.width);
    const h = Math.round(rect.height);
    if (w < 2 || h < 2) return;
    let radius = 0;
    try {
      radius = parseFloat(getComputedStyle(item.el).borderTopLeftRadius) || 0;
    } catch {
      radius = 0;
    }
    const url = buildDisplacementMap(w, h, radius, item.opts.bezelRatio, item.opts.bezelCap, item.opts.k);
    if (!url) return;
    item.feImage.setAttribute('x', '0');
    item.feImage.setAttribute('y', '0');
    item.feImage.setAttribute('width', String(w));
    item.feImage.setAttribute('height', String(h));
    item.feImage.setAttribute('href', url);
    item.feImage.setAttributeNS(XLINK, 'xlink:href', url);
    const m = PEAK_DISP + 4;
    item.filter.setAttribute('x', String(-m));
    item.filter.setAttribute('y', String(-m));
    item.filter.setAttribute('width', String(w + 2 * m));
    item.filter.setAttribute('height', String(h + 2 * m));
  }

  function refreshAll() {
    resizeTimer = 0;
    for (const it of items) refresh(it);
  }

  /* 指针追随高光：rAF 合流，只写 CSS 变量，合成器绘制，无逐帧渲染*/
  let specRaf = 0;
  let specEvt = null;
  function onMove(e) {
    specEvt = e;
    if (specRaf) return;
    specRaf = requestAnimationFrame(() => {
      specRaf = 0;
      const t = specEvt && specEvt.target && specEvt.target.closest
        ? specEvt.target.closest('[data-lg]')
        : null;
      if (!t) return;
      const r = t.getBoundingClientRect();
      t.style.setProperty('--lg-mx', Math.round(specEvt.clientX - r.left) + 'px');
      t.style.setProperty('--lg-my', Math.round(specEvt.clientY - r.top) + 'px');
    });
  }
  document.addEventListener('pointermove', onMove, { passive: true });

  function teardown() {
    if (resizeTimer) {
      clearTimeout(resizeTimer);
      resizeTimer = 0;
    }
    if (scanTimer) {
      clearTimeout(scanTimer);
      scanTimer = 0;
    }
    if (ro) ro.disconnect();
    if (ro0) ro0.disconnect();
    if (mo) mo.disconnect();
    if (stopMonitor) stopMonitor();
    document.removeEventListener('pointermove', onMove);
    if (specRaf) cancelAnimationFrame(specRaf);
    for (const it of items) {
      it.el.style.backdropFilter = '';
      it.el.style.webkitBackdropFilter = '';
      it.el.removeAttribute('data-lg');
      it.el.classList.remove('lg-spec');
      it.el.style.removeProperty('--lg-mx');
      it.el.style.removeProperty('--lg-my');
    }
    items.length = 0;
    host.remove();
  }

  let ro0 = null;

  /* ---------- auto 运行时自适应：滚动实测帧率，不足则降档 ---------- */
  /* 换档重挂：只清折射，内联样式+滤镜+标记，不动监听与宿主 —— CSS 玻璃材质全程保留*/
  function softReset() {
    for (const it of items) {
      it.el.style.backdropFilter = '';
      it.el.style.webkitBackdropFilter = '';
      it.el.removeAttribute('data-lg');
      it.el.classList.remove('lg-spec');
      it.el.style.removeProperty('--lg-mx');
      it.el.style.removeProperty('--lg-my');
    }
    items.length = 0;
    for (const f of Array.from(svg.querySelectorAll('filter'))) f.remove();
  }
  function applyTier() {
    softReset();
    if (tier !== 'css') mount();
    try { document.documentElement.dataset.lgTier = tier; } catch { /* 忽略 */ }
  }

  if (isAuto) {
    let frames = 0;
    let t0 = 0;
    let monRaf = 0;
    let lastScrollAt = 0;
    let lastDegradeAt = 0;
    const onScrollArm = () => {
      lastScrollAt = performance.now();
      if (!monRaf && tier !== 'css') {
        frames = 0;
        t0 = lastScrollAt;
        monRaf = requestAnimationFrame(monTick);
      }
    };
    const monTick = () => {
      monRaf = 0;
      const now = performance.now();
      /* 用户停止滚动 350ms 即出窗：静止时玻璃零渲染，测了也不代表负载 */
      if (now - lastScrollAt > 350) { evaluate(); return; }
      frames += 1;
      /* 窗口：满 3 秒或攒够 120 帧即评估 —— 弱机帧率低，窗口靠时间撑够样本 */
      if (now - t0 >= 3000 || frames >= 120) { evaluate(); return; }
      monRaf = requestAnimationFrame(monTick);
    };
    const evaluate = () => {
      if (monRaf) { cancelAnimationFrame(monRaf); monRaf = 0; }
      const span = performance.now() - t0;
      const fps = frames >= 15 && span >= 500 ? Math.round((frames / span) * 1000) : -1;
      try { document.documentElement.dataset.lgMon = `frames:${frames} span:${Math.round(span)} fps:${fps}`; } catch { /* 忽略 */ }
      /* 样本太少不评判，<8 帧或 <0.5s 的轻扫——弱机 10fps×3s 也有 30 帧，能评*/
      if (frames < 8 || span < 500) return;
      const now = performance.now();
      if (fps < 45 && now - lastDegradeAt > 5000) {
        lastDegradeAt = now;
        const ladder = { full: 'standard', standard: 'low', low: 'css' };
        const next = ladder[tier];
        if (next) {
          tier = next;
          try { localStorage.setItem('ctyfly-lg-auto', tier + ':' + Date.now()); } catch { /* 忽略 */ }
          applyTier();
        }
      }
    };
    window.addEventListener('scroll', onScrollArm, { passive: true, capture: true });
    stopMonitor = () => window.removeEventListener('scroll', onScrollArm, { passive: true, capture: true });
    /* 调试/测试钩子，仅 auto 档暴露：读取当前档位、强制降一档*/
    try {
      window.__lgDebug = {
        tier: () => tier,
        degrade: () => { const ladder = { full: 'standard', standard: 'low', low: 'css' }; if (ladder[tier]) { tier = ladder[tier]; try { localStorage.setItem('ctyfly-lg-auto', tier + ':' + Date.now()); } catch { /* 忽略 */ } applyTier(); } return tier; },
      };
    } catch { /* 忽略 */ }
  }
  try { document.documentElement.dataset.lgTier = tier; } catch { /* 忽略 */ }

  try {
    ro0 = new ResizeObserver(() => {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(refreshAll, 120);
    });
    mount();
    if (!items.length) {
      teardown();
      return null;
    }
    ro = ro0;
    /* 弹层/卡片是动态挂载的：DOM 变化后补扫，去抖*/
    mo = new MutationObserver(() => {
      if (scanTimer) clearTimeout(scanTimer);
      scanTimer = setTimeout(() => {
        scanTimer = 0;
        if (!mqTransparency || !mqTransparency.matches) mount();
      }, 200);
    });
    mo.observe(document.body, { childList: true, subtree: true });
  } catch {
    teardown();
    return null;
  }

  function onMq() {
    if (mqTransparency.matches) teardown();
    else mount();
  }
  if (mqTransparency) {
    if (mqTransparency.addEventListener) mqTransparency.addEventListener('change', onMq);
    else if (mqTransparency.addListener) mqTransparency.addListener(onMq);
  }

  /* 跨越 861px 断点：宽屏释放侧栏玻璃，CSS 接管，窄屏重新挂载*/
  let layoutTimer = 0;
  function onWide() {
    if (layoutTimer) clearTimeout(layoutTimer);
    layoutTimer = setTimeout(() => {
      layoutTimer = 0;
      mount();
    }, 150);
  }
  if (wideMq) {
    if (wideMq.addEventListener) wideMq.addEventListener('change', onWide);
    else if (wideMq.addListener) wideMq.addListener(onWide);
  }

  return function destroy() {
    if (mqTransparency) {
      if (mqTransparency.removeEventListener) mqTransparency.removeEventListener('change', onMq);
      else if (mqTransparency.removeListener) mqTransparency.removeListener(onMq);
    }
    if (wideMq) {
      if (wideMq.removeEventListener) wideMq.removeEventListener('change', onWide);
      else if (wideMq.removeListener) wideMq.removeListener(onWide);
    }
    if (layoutTimer) clearTimeout(layoutTimer);
    teardown();
  };
}
