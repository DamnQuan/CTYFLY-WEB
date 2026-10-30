/**
 * 路由模块预取：把懒加载页面的 JS/CSS 提前下载好，进入页面时不再现等
 * - 侧边栏悬停 / 键盘聚焦时预取目标页
 * - 空闲时批量预热常用页面
 */
import { router } from './router/index.js';

const loaded = new Set();

/** 预取指定路径对应的路由组件模块 */
export function prefetchRoute(path) {
  if (!path || loaded.has(path)) return;
  loaded.add(path);
  try {
    const matched = router.resolve(path)?.matched || [];
    for (const record of matched) {
      const loader = record.components?.default;
      if (typeof loader === 'function') {
        // 触发动态 import，浏览器缓存住 chunk 与其中的 CSS
        loader().catch(() => loaded.delete(path));
      }
    }
  } catch {
    loaded.delete(path);
  }
}

/** 空闲时批量预热，不阻塞首屏*/
export function prefetchRoutesOnIdle(paths) {
  const run = () => {
    // 弱网/省流量模式直接不预热：这些是「用户还没要看」的页面，
    // 在慢速链路上会实实在在挤占首屏带宽，得不偿失。
    if (!prefetchAllowed()) return;
    paths.forEach((p, i) => {
      setTimeout(() => prefetchRoute(p), i * 120);
    });
  };
  if ('requestIdleCallback' in window) {
    window.requestIdleCallback(run, { timeout: 3000 });
  } else {
    setTimeout(run, 1200);
  }
}

/**
 * 是否值得后台预热。
 * 慢速链路，2G/3G 或用户开了「节省流量」时不预热 —— 优先保证当前页面能快点出来。
 */
export function prefetchAllowed() {
  try {
    const c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (!c) return true;
    if (c.saveData) return false;
    const t = c.effectiveType || '';
    return !(t === 'slow-2g' || t === '2g' || t === '3g');
  } catch {
    return true;
  }
}
