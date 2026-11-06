/**
 * 真实用户性能采集：LCP / CLS / INP 近似值 / TTFB。
 * 只做轻量 observe，不阻塞首屏；页面隐藏时用 sendBeacon 上报。
 */
let started = false;
let sent = false;
let lcp = 0;
let cls = 0;
let inp = 0;

function send() {
  if (sent) return;
  sent = true;
  try {
    const nav = performance.getEntriesByType('navigation')[0];
    const payload = JSON.stringify({
      path: location.pathname.slice(0, 200) || '/',
      lcp: Math.round(lcp),
      inp: Math.round(inp),
      cls: Number(cls.toFixed(4)),
      ttfb: nav ? Math.round(nav.responseStart) : 0,
      device: window.innerWidth <= 768 ? 'mobile' : 'desktop',
    });
    const blob = new Blob([payload], { type: 'application/json' });
    if (navigator.sendBeacon && navigator.sendBeacon('/api/perf', blob)) return;
    fetch('/api/perf', { method: 'POST', body: payload, headers: { 'Content-Type': 'application/json' }, keepalive: true }).catch(() => {});
  } catch { /* 性能上报不得影响页面 */ }
}

export function initPerf() {
  if (started) return;
  started = true;
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.startTime > lcp) lcp = entry.startTime;
      }
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch { /* 不支持则忽略 */ }
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) cls += entry.value;
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch { /* 不支持则忽略 */ }
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.interactionId && entry.duration > inp) inp = entry.duration;
      }
    }).observe({ type: 'event', buffered: true, durationThreshold: 16 });
  } catch { /* 不支持则忽略 */ }
  addEventListener('pagehide', send, { once: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') send();
  }, { once: true });
}
