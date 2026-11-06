/**
 * 长驻标签页的「站点已更新」提醒
 *
 * 为什么要有这个：SPA 的 JS 在页面加载后就固定了，部署新版本后，开着的旧标签页
 * 依旧跑旧代码，正常点击导航不会重新加载，用户看到的永远是旧版。
 *
 * 做法，零依赖、无轮询压力：
 *   - 记住自己这次加载的入口文件名，assets/index-<hash>.js
 *   - 页面重新可见 / 每 10 分钟，fetch 一次首页，no-store，比对入口文件名
 *   - 不一致 → toast 提示刷新；同一新版本在本次会话内只提醒一次，sessionStorage 去重
 */
import { showToast } from './utils.js';

const CHECK_INTERVAL_MS = 10 * 60 * 1000;
const STORAGE_KEY = 'ctyfly_stale_build';

let started = false;

function currentEntryFile() {
  const el = document.querySelector('script[src*="assets/index-"]');
  const m = el && /assets\/(index-[^/]+\.js)/.exec(el.src || '');
  return m ? m[1] : '';
}

export function initVersionCheck() {
  if (started) return;
  started = true;
  const self = currentEntryFile();
  if (!self) return; // 非常规加载方式，如测试环境注入时跳过
  let notified = '';
  try {
    notified = sessionStorage.getItem(STORAGE_KEY) || '';
  } catch {
    /* 无存储则每次变化都提醒 */
  }

  const check = async () => {
    if (document.hidden) return;
    let latest = '';
    try {
      const res = await fetch('/', { cache: 'no-store' });
      if (!res.ok) return;
      latest = (/assets\/(index-[^/]+\.js)/.exec(await res.text()) || [''])[1] || '';
    } catch {
      return; // 断网/后端重启窗口：静默，下个周期再试
    }
    if (!latest || latest === self || latest === notified) return;
    notified = latest;
    try {
      sessionStorage.setItem(STORAGE_KEY, latest);
    } catch {
      /* 忽略 */
    }
    showToast('站点已更新，建议刷新页面哦~', 8000);
  };

  check();
  setInterval(check, CHECK_INTERVAL_MS);
  window.addEventListener('visibilitychange', () => {
    if (!document.hidden) check();
  });
}
