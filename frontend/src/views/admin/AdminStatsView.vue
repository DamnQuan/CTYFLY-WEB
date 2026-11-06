<script setup>
import { onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { showToast } from '../../utils.js';
import Icon from '../../components/Icon.vue';
import TrendLine from '../../components/TrendLine.vue';
// 仪表盘的模块化内容，可拖拽换位/主次切换
import ModularDash from '../../components/ModularDash.vue';

const stats = ref(null);
const trend = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await api.get('/api/admin/stats');
    stats.value = data.stats;
    trend.value = data.trend;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">数据概览</div>
      <div class="page-desc">站点运行状态、待办事项与风险概览</div>
    </div>

    <!-- 模块化仪表盘：主模块可拖拽换位-->
    <ModularDash />

    <div v-if="loading" class="loading">加载中…</div>
    <template v-else-if="stats">
      <div class="grid grid-4">
        <div class="stat"><div class="stat-num">{{ stats.total }}</div><div class="stat-label">注册用户</div></div>
        <div class="stat"><div class="stat-num">{{ stats.today }}</div><div class="stat-label">今日新增</div></div>
        <div class="stat"><div class="stat-num">{{ stats.controllers }}</div><div class="stat-label">在职管制员</div></div>
        <div class="stat"><div class="stat-num">{{ stats.pendingApps }}</div><div class="stat-label">待审申请</div></div>
        <div class="stat"><div class="stat-num">{{ stats.pendingApprovals }}</div><div class="stat-label">待审批（双人复核）</div></div>
        <div class="stat"><div class="stat-num">{{ stats.openTickets }}</div><div class="stat-label">未关工单</div></div>
        <div class="stat"><div class="stat-num">{{ stats.events }}</div><div class="stat-label">进行中活动</div></div>
        <div class="stat"><div class="stat-num">{{ stats.airlines }}</div><div class="stat-label">在营虚拟航司</div></div>
      </div>

      <div class="grid grid-3" style="margin-top: 16px">
        <div class="stat"><div class="stat-num">{{ stats.todayLogins }}</div><div class="stat-label">今日成功登录</div></div>
        <div class="stat"><div class="stat-num">{{ stats.failedLogins }}</div><div class="stat-label">24h 登录失败</div></div>
        <div class="stat"><div class="stat-num">{{ stats.riskEvents }}</div><div class="stat-label">24h 风险事件</div></div>
      </div>

      <div class="glass card" style="margin-top: 16px">
        <div class="card-title">近 7 天注册趋势</div>
        <div v-if="!trend.length" class="empty">暂无数据</div>
        <TrendLine v-else :points="trend" />
      </div>

      <div class="glass card" style="margin-top: 16px">
        <div class="card-title">快捷入口</div>
        <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px">
          <router-link class="btn btn-ghost btn-sm" to="/admin/approvals"><Icon name="shield" :size="14" /> 待审批 {{ stats.pendingApprovals }}</router-link>
          <router-link class="btn btn-ghost btn-sm" to="/admin/users"><Icon name="users" :size="14" /> 用户管理</router-link>
          <router-link class="btn btn-ghost btn-sm" to="/admin/logs-audit">审计日志</router-link>
          <router-link class="btn btn-ghost btn-sm" to="/admin/logs-network">网络流量</router-link>
        </div>
      </div>
    </template>
  </div>
</template>
