/** 存储同意状态：all = 全部接受；essential = 仅必需项 */
const KEY = 'ctyfly_consent';

export function getConsent() {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'all' || v === 'essential' ? v : '';
  } catch {
    return '';
  }
}

export function setConsent(v) {
  try { localStorage.setItem(KEY, v); } catch { /* 忽略 */ }
}

/** 清除偏好类存储项，仅必需模式下不应保留*/
export function clearPreferenceStorage() {
  try {
    localStorage.removeItem('ctyfly_theme');
    localStorage.removeItem('ctyfly_tz');
  } catch { /* 忽略 */ }
}

export function resetConsent() {
  try { localStorage.removeItem(KEY); } catch { /* 忽略 */ }
}
