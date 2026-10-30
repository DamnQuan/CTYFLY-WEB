/** 主题，AUTO 跟随系统 / light / dark，持久化到 localStorage，尊重存储同意*/
import { getConsent } from './consent.js';

const KEY = 'ctyfly_theme';

export function getTheme() {
  try {
    const t = localStorage.getItem(KEY);
    return ['auto', 'light', 'dark'].includes(t) ? t : 'auto';
  } catch {
    return 'auto';
  }
}

export function applyTheme(t) {
  document.documentElement.dataset.theme = t;
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
}
