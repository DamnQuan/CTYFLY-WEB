/** 我的航司成员身份，侧边栏显隐 + 签派/报告页取 airlineId*/
import { defineStore } from 'pinia';
import { api } from '../api.js';

// 并发去重：侧边栏与页面同时首次拉取时，共享同一个进行中的请求。
// 若只是「loading 时直接 return」，晚到的调用会拿到空身份提前放弃，
// 等身份真正到位后也不会再加载，整页刷新进 /va/* 页面必现的竞态。
let inflight = null;

export const useVaStore = defineStore('va', {
  state: () => ({ membership: null, loaded: false, loading: false }),
  getters: {
    joined: (s) => !!(s.membership && s.membership.airlineId),
    isCEO: (s) => s.membership?.role === 'ceo',
  },
  actions: {
    async fetch() {
      if (inflight) return inflight;
      inflight = (async () => {
        this.loading = true;
        try {
          const data = await api.get('/api/airlines/my/membership');
          this.membership = data.membership || null;
          this.loaded = true;
        } catch {
          /* 拉取失败按未加入处理，不打断界面 */
        }
        this.loading = false;
      })();
      try {
        await inflight;
      } finally {
        inflight = null;
      }
    },
    clear() {
      this.membership = null;
      this.loaded = false;
    },
  },
});
