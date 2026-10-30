import { reactive } from 'vue';

export const toast = reactive({
  message: '',
  visible: false,
  duration: 2600,
  timer: null,
});

export function showToast(message, duration = 2600) {
  toast.message = message;
  toast.duration = duration;
  toast.visible = true;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    toast.visible = false;
  }, duration);
}

export function fmtTime(s) {
  if (!s) return '';
  return String(s).replace('T', ' ').slice(0, 16);
}

/** 本地时区日期，YYYY-MM-DD：toISOString 按 UTC 会差一天，日期一律用它*/
export function localDate(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 本地时区月份，YYYY-MM：工资单导出等按月场景用*/
export function localMonth(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}`;
}

/** 外链协议白名单：仅 http/https 可渲染为链接，javascript: 等一律返回空串，降级纯文本*/
export function safeHttpUrl(url) {
  if (!url || typeof url !== 'string') return '';
  try {
    const u = new URL(url);
    return u.protocol === 'http:' || u.protocol === 'https:' ? url : '';
  } catch {
    return '';
  }
}

export function avatarUrl(user) {
  if (user?.avatar_url) return user.avatar_url;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" rx="32" fill="#c7c7cc"/><text x="32" y="41" font-size="26" text-anchor="middle" fill="#fff" font-family="sans-serif">${(user?.username || 'C')[0].toUpperCase()}</text></svg>`
  )}`;
}

export const EVENT_STATUS = {
  upcoming: { text: '报名中', cls: 'tag-blue' },
  ongoing: { text: '进行中', cls: 'tag-green' },
  ended: { text: '已结束', cls: 'tag' },
  cancelled: { text: '已取消', cls: 'tag-red' },
};

export const APP_STATUS = {
  pending: { text: '待审核', cls: 'tag-orange' },
  approved: { text: '已通过', cls: 'tag-green' },
  rejected: { text: '未通过', cls: 'tag-red' },
};

export const TICKET_STATUS = {
  open: { text: '待回复', cls: 'tag-orange' },
  replied: { text: '已回复', cls: 'tag-blue' },
  closed: { text: '已关闭', cls: 'tag' },
};
