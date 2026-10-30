const TOKEN_KEY = 'ctyfly_token';

/** 默认超时：没有超时的 fetch 一旦遇到服务端重启/半开连接会永久挂起，
 *  配合路由守卫里的 await 会让整个界面「点不动」，只能刷新恢复。 */
const DEFAULT_TIMEOUT = 12000;

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';   // 存储被禁用/配额异常时按未登录处理，绝不能抛错中断导航
  }
}
export function setToken(t) {
  try {
    t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);
  } catch { /* 忽略：仅影响下次登录态持久化 */ }
}

/** 请求选项归一化：兼容历史调用里直接传超时数字的写法，也支持 { timeout, headers } */
function normalizeOptions(opts) {
  if (typeof opts === 'number') return { timeout: opts, headers: {} };
  if (!opts || typeof opts !== 'object') return { timeout: DEFAULT_TIMEOUT, headers: {} };
  return {
    timeout: typeof opts.timeout === 'number' ? opts.timeout : DEFAULT_TIMEOUT,
    headers: opts.headers && typeof opts.headers === 'object' ? opts.headers : {},
  };
}

async function request(method, url, body, opts) {
  const conf = normalizeOptions(opts);
  const headers = { 'Content-Type': 'application/json', ...conf.headers };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), conf.timeout);

  let resp;
  try {
    resp = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    if (err?.name === 'AbortError') {
      const e = new Error('请求超时，请检查网络后重试');
      e.timeout = true;
      throw e;
    }
    const e = new Error('网络连接失败，请稍后重试');
    e.network = true;
    throw e;
  } finally {
    clearTimeout(timer);
  }

  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = {};
  }
  if (!resp.ok) {
    const err = new Error(data.error || `请求失败 ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return data;
}

/**
 * 带鉴权取二进制内容，图片 / 附件下载等。
 * 浏览器直接请求无法携带 Authorization 头，所以先 fetch 成 Blob 再用：
 * 预览用 URL.createObjectURL blob，下载用 a[download]，用完记得 revoke。
 */
async function requestBlob(url, timeout = 60000) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  let resp;
  try {
    resp = await fetch(url, { headers, signal: controller.signal });
  } catch (err) {
    if (err?.name === 'AbortError') {
      const e = new Error('下载超时，请稍后重试');
      e.timeout = true;
      throw e;
    }
    throw new Error('网络连接失败，请稍后重试');
  } finally {
    clearTimeout(timer);
  }
  if (!resp.ok) {
    let msg = `下载失败 ${resp.status}`;
    try { msg = (await resp.json()).error || msg; } catch { /* 忽略 */ }
    const e = new Error(msg);
    e.status = resp.status;
    throw e;
  }
  return resp.blob();
}

export const api = {
  get: (url, opts) => request('GET', url, undefined, opts),
  post: (url, body, opts) => request('POST', url, body ?? {}, opts),
  put: (url, body, opts) => request('PUT', url, body ?? {}, opts),
  patch: (url, body, opts) => request('PATCH', url, body ?? {}, opts),
  delete: (url, opts) => request('DELETE', url, undefined, opts),
  blob: (url, timeout) => requestBlob(url, timeout),
  /** multipart 文件上传，body 为 FormData，勿设 Content-Type，让浏览器自带 boundary*/
  async upload(url, formData, timeout = 120000) {
    const headers = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    let resp;
    try {
      resp = await fetch(url, { method: 'POST', headers, body: formData, signal: controller.signal });
    } catch (err) {
      if (err?.name === 'AbortError') {
        const e = new Error('上传超时，请稍后重试');
        e.timeout = true;
        throw e;
      }
      throw new Error('网络连接失败，请稍后重试');
    } finally {
      clearTimeout(timer);
    }
    let data = null;
    try { data = await resp.json(); } catch { data = {}; }
    if (!resp.ok) {
      const err = new Error(data.error || `上传失败 ${resp.status}`);
      err.status = resp.status;
      throw err;
    }
    return data;
  },
};
