/**
 * 公网 IPv6 探测，WebRTC / STUN——站点目前只有 IPv4 入口时的补充手段
 *
 * 背景：服务器没有全局 IPv6、域名也没有 AAAA，浏览器访问本站时 TCP 走的是 IPv4，
 * 服务端在连接层永远只能看到 IPv4；用户自己的 IPv6 不会随请求上报。唯一能拿到的办法
 * 是让浏览器在本机发起一次 STUN 查询：如果用户网络本身有公网 IPv6，STUN 服务器
 * Cloudflare，AAAA 已就绪会把它看到的本机地址作为 srflx 候选返回。
 *
 * 边界，务必如实理解，不要当成必得：
 * - 只对「本机确有公网 IPv6」的用户有效；IPv4-only 网络探不到，属正常；
 * - 浏览器隐私设置，如屏蔽 ICE、企业网络、STUN 不可达时同样拿不到；
 * - 拿到的是「探测时 STUN 看到的公网地址」，不是访问本站的连接地址，
 *   因此与 IP 日志里的 IPv4 是两条独立线索，后端存 users.last_ip_v6；
 * - 只在会话内探测一次，sessionStorage 去重，失败静默，不影响任何页面功能。
 *
 * 隐私：该探测会让浏览器访问一次 Cloudflare STUN，
 * 已在《隐私政策》第三方服务清单中披露；后端可用 IPV6_PROBE_ENABLED=false 关闭。
 */
import { api } from './api.js';

const STUN_URLS = ['stun:stun.cloudflare.com:3478'];
const PROBE_TIMEOUT_MS = 5000;
const SESSION_KEY = 'ctyfly_ipv6_probed';

/** 从 ICE candidate 里取出公网 IPv6，2000::/3 全局单播，取不到返回 ''*/
function pickGlobalV6FromCandidate(line) {
  // 格式：candidate:foundation component protocol priority address port typ type ...
  const parts = String(line || '').split(' ');
  const address = parts[4] || '';
  if (!address.includes(':') || address.length < 6) return '';   // 不是 v6
  if (!/^[23][0-9a-f]{0,3}:/i.test(address)) return '';          // 排除 fe80/fc/fd/::1 等
  return address.toLowerCase();
}

/** 本机公网 IPv6；无 IPv6 / 被拦截 / 超时都返回 ''，绝不抛错*/
export function probePublicIpv6() {
  if (typeof RTCPeerConnection !== 'function') return Promise.resolve('');

  let pc = null;
  try {
    pc = new RTCPeerConnection({ iceServers: [{ urls: STUN_URLS }] });
  } catch {
    return Promise.resolve('');
  }

  return new Promise((resolve) => {
    let done = false;
    const finish = (ip) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      try {
        pc.close();
      } catch {
        /* 已关闭 */
      }
      resolve(ip || '');
    };
    const timer = setTimeout(() => finish(''), PROBE_TIMEOUT_MS);

    pc.onicecandidate = (ev) => {
      const line = ev?.candidate?.candidate;
      if (!line) return;
      const ip = pickGlobalV6FromCandidate(line);
      if (ip) finish(ip);
    };

    try {
      pc.createDataChannel('ipv6-probe');
      pc.createOffer()
        .then((offer) => pc.setLocalDescription(offer))
        .catch(() => finish(''));
    } catch {
      finish('');
    }
  });
}

/**
 * 会话内只探测并上报一次，登录后/刷新时调用。
 * 无论探测成功与否都写入 sessionStorage 标记，避免每次路由切换都重试。
 */
export async function reportIpv6Once() {
  try {
    if (sessionStorage.getItem(SESSION_KEY)) return '';
  } catch {
    /* 隐私模式禁用 storage：本次仍然探测，但不做会话去重 */
  }

  const ip = await probePublicIpv6();
  try {
    sessionStorage.setItem(SESSION_KEY, '1');
  } catch {
    /* 忽略 */
  }
  if (!ip) return '';

  try {
    const data = await api.post('/api/auth/ip-probe', { ipv6: ip });
    return data?.ok ? (data.ipv6 || ip) : '';
  } catch {
    return '';   // 后端关闭/限流/校验失败都不影响前台
  }
}
