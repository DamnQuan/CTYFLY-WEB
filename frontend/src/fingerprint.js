/**
 * 设备指纹：浏览器特征摘要哈希，仅用于安全审计与异常登录识别
 * 不上传原始特征，只提交不可逆哈希；不采集任何个人身份信息。
 */
let cached = null;

async function sha256Hex(text) {
  try {
    if (window.crypto?.subtle) {
      const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
      return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
    }
  } catch { /* 降级 */ }
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0').repeat(4);
}

function canvasSignature() {
  try {
    const c = document.createElement('canvas');
    c.width = 200;
    c.height = 40;
    const ctx = c.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = '14px Arial';
    ctx.fillStyle = '#f60';
    ctx.fillRect(0, 0, 100, 20);
    ctx.fillStyle = '#069';
    ctx.fillText('CTYFLY-fp', 2, 4);
    return c.toDataURL().slice(-64);
  } catch {
    return '';
  }
}

export async function getFingerprint() {
  if (cached !== null) return cached;
  try {
    const parts = [
      navigator.userAgent,
      navigator.language,
      (navigator.languages || []).join(','),
      navigator.platform,
      navigator.hardwareConcurrency,
      navigator.deviceMemory,
      screen.width, screen.height, screen.colorDepth, screen.pixelDepth,
      new Date().getTimezoneOffset(),
      Intl.DateTimeFormat().resolvedOptions().timeZone,
      canvasSignature(),
    ];
    cached = (await sha256Hex(parts.join('|'))).slice(0, 32);
  } catch {
    cached = '';
  }
  return cached;
}
