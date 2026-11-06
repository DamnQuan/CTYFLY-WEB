<script setup>
/**
 * 站点状态 —— 公开页面：实时运行指标，每 60 秒自动刷新。
 * 请求失败时整页仍保持「服务异常」状态展示，绝不白屏。
 */
import { ref, onMounted, onUnmounted } from 'vue';
import { api } from '../api.js';
import Icon from '../components/Icon.vue';

const status = ref(null);      // /api/status 的 data
const failed = ref(false);     // 请求失败或 ok != true
const loading = ref(true);

const REFRESH_MS = 60 * 1000;
let timer = 0;

async function load() {
  try {
    const data = await api.get('/api/status');
    status.value = data || {};
    failed.value = data?.ok !== true;
  } catch {
    /* 保留上次成功数据，若有，仅切换整体状态，不白屏*/
    failed.value = true;
  }
  loading.value = false;
}

onMounted(() => {
  load();
  timer = setInterval(load, REFRESH_MS);
});
onUnmounted(() => clearInterval(timer));
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 56vw, 1100px)">
    <div class="page-header">
      <div class="page-title">站点状态</div>
      <div class="page-desc">实时运行指标，每分钟自动刷新</div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <template v-else>
      <!-- 整体状态大卡 -->
      <div class="glass card status-hero">
        <div class="status-hero-main">
          <span class="tag" :class="failed ? 'tag-red' : 'tag-blue'">
            {{ failed ? '服务异常' : '运行正常' }}
          </span>
          <div class="status-hero-text">
            {{ failed ? '部分服务暂时不可用，我们正在处理' : '全部服务运行正常' }}
          </div>
        </div>
        <div v-if="status && !failed" class="status-hero-sub">
          近 24h 请求 {{ (status.requests24h ?? 0).toLocaleString() }} 次 · 错误率 {{ status.errorRatePct ?? 0 }}%
        </div>
      </div>

      <!-- 指标卡网格 -->
      <div v-if="status && !failed" class="grid grid-4" style="margin-top: 16px">
        <div class="stat">
          <div class="stat-num">
            正常
            <span v-if="status.dbPingMs !== undefined" class="stat-unit">· {{ status.dbPingMs }} ms</span>
          </div>
          <div class="stat-label">API 服务（数据库延迟）</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ status.totalUsers ?? 0 }}</div>
          <div class="stat-label">注册用户</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ status.onlineUsers ?? 0 }}</div>
          <div class="stat-label">当前在线</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ status.totalAirlines ?? 0 }}</div>
          <div class="stat-label">运营中航司</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ (status.requests24h ?? 0).toLocaleString() }}</div>
          <div class="stat-label">近 24h 请求</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ status.errorRatePct ?? 0 }}%</div>
          <div class="stat-label">错误率</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ status.uptimeHours ?? 0 }}<span class="stat-unit"> h</span></div>
          <div class="stat-label">进程运行时长</div>
        </div>
      </div>

      <!-- 失败态：保留大卡状态，不白屏 -->
      <div v-if="failed" class="glass card" style="margin-top: 16px">
        <div class="empty">
          <div class="empty-icon"><Icon name="radar" :size="22" /></div>
          <div>暂时无法获取运行指标，正在自动重试</div>
        </div>
      </div>

      <div class="status-foot">
        数据由服务器每分钟聚合<template v-if="status?.serverTime"> · 当前服务器时间 {{ status.serverTime }}</template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.status-hero { padding: 26px 28px; }
.status-hero-main { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.status-hero-main .tag { font-size: 13px; padding: 4px 12px; }
.status-hero-text { font-size: 16px; font-weight: 600; color: var(--text); }
.status-hero-sub { margin-top: 10px; font-size: 12.5px; color: var(--text-2); }
.stat-unit { font-size: 13px; font-weight: 500; color: var(--text-2); }
.status-foot {
  margin-top: 18px;
  text-align: center;
  font-size: 12px;
  color: var(--gray);
}
</style>
