/** 主题，AUTO 跟随系统 / light / dark，持久化到 localStorage，尊重存储同意*/
import { getConsent } from './consent.js';

const KEY = 'ctyfly_theme';
const MQ = '(prefers-color-scheme: dark)';

let pref = 'auto';
let mq = null;

export function getTheme() {
  try {
    const t = localStorage.getItem(KEY);
    return ['auto', 'light', 'dark'].includes(t) ? t : 'auto';
  } catch {
    return 'auto';
  }
}

/* data-theme 永远写解析后的实际值（light/dark），
   CSS 因此只需一份深色分支；AUTO 的判断收敛在这里。*/
function resolvedTheme() {
  if (pref !== 'auto') return pref;
  return mq && mq.matches ? 'dark' : 'light';
}

export function applyTheme(t) {
  pref = t;
  document.documentElement.dataset.theme = resolvedTheme();
}

export function setTheme(t) {
  // 用户选择"仅必需"时：本次会话内生效但不持久化
  if (getConsent() !== 'essential') {
    try { localStorage.setItem(KEY, t); } catch { /* 忽略 */ }
  }
  applyTheme(t);
}

export function initTheme() {
  applyTheme(getTheme());
  // AUTO 模式下跟随系统切换实时生效
  if (typeof window.matchMedia === 'function') {
    mq = window.matchMedia(MQ);
    const onChange = () => { if (pref === 'auto') applyTheme(pref); };
    if (typeof mq.addEventListener === 'function') mq.addEventListener('change', onChange);
    else if (typeof mq.addListener === 'function') mq.addListener(onChange);
  }
}
