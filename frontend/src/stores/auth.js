import { defineStore } from 'pinia';
import { api, getToken, setToken } from '../api.js';
import { reportIpv6Once } from '../ipv6Probe.js';

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    loaded: false,
    retryTimer: null,   // 网络故障后 fetchMe 的延迟重试句柄
    ipv6ProbeEnabled: false,   // 后端开关：浏览器探测公网 IPv6，WebRTC/STUN
  }),
  getters: {
    isLoggedIn: (s) => Boolean(s.user),
    isAdmin: (s) => s.user?.role === 'admin',
    isStaff: (s) => ['admin', 'sup'].includes(s.user?.role),
    /** 后端下发的有效能力，role 分支 ∪ rating 分支，ADM 恒为全部*/
    capabilities: (s) => s.user?.capabilities || [],
    /** 是否拥有某项能力。侧边栏节点与路由守卫都用它，保证与后端同一套判断 */
    can: (s) => (cap) => {
      if (s.user?.role === 'admin') return true;
      return (s.user?.capabilities || []).includes(cap);
    },
    /** 能否进入管理后台：拥有任意一个后台节点能力即可 */
    canAdmin: (s) => {
      if (s.user?.role === 'admin') return true;
      return (s.user?.capabilities || []).length > 0;
    },
  },
  actions: {
    async fetchMe(fromRetry = false) {
      if (!getToken()) {
        this.user = null;
        this.loaded = true;
        return;
      }
      try {
        const data = await api.get('/api/auth/me');
        this.user = data.user;
        this.loaded = true;
        // 站点只有 IPv4 入口时，补一次浏览器侧的公网 IPv6 探测，会话内一次，失败静默
        this.ipv6ProbeEnabled = data.ipv6ProbeEnabled !== false;
        if (this.ipv6ProbeEnabled) reportIpv6Once();
        // 网络恢复后登录态回来了：若还停在登录/注册页，整页刷新一次，守卫会自动送回仪表盘。
        // 仅在「重试恢复」路径触发，避免首屏正常加载时形成刷新循环
        if (fromRetry && this.user && /^\/(login|register|forgot)/.test(window.location.pathname)) {
          window.location.reload();
        }
      } catch (err) {
        if (err?.status === 401 || err?.status === 403) {
          // 仅当服务端明确否认身份时才清 token 并放行路由
          setToken('');
          this.user = null;
          this.loaded = true;
        } else {
          // 超时/断网等临时故障：不置 loaded、user 保持 null，不清登录态，
          // 同时安排延迟重试——waitForAuth 有 8s 超时不会死等，
          // 网络恢复后这里自动拿回登录态，只有 401/403 才真正下线
          this.scheduleMeRetry();
        }
      }
    },
    /** 网络故障后的登录态重试：成功或 token 清除后停止 */
    scheduleMeRetry() {
      if (this.retryTimer) return;
      this.retryTimer = setTimeout(async () => {
        this.retryTimer = null;
        if (!getToken() || this.loaded) return;
        await this.fetchMe(true);
      }, 5000);
    },
    loginSuccess(token, user) {
      setToken(token);
      this.user = user;
      reportIpv6Once();          // 登录后立刻探测一次，同一会话只跑一次
    },
    async logout() {
      setToken('');
      this.user = null;
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
      // 换账号登录同一标签页时允许重新探测
      try {
        sessionStorage.removeItem('ctyfly_ipv6_probed');
      } catch {
        /* storage 被禁用时忽略 */
      }
    },
  },
});
