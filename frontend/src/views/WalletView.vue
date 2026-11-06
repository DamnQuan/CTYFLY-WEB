<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';
import { fmtTime, showToast } from '../utils.js';
import Icon from '../components/Icon.vue';

const wallet = ref(null);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await api.get('/api/wallet');
    wallet.value = data.wallet;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});
</script>

<template>
  <div class="page" style="max-width: clamp(680px, 50vw, 1020px)">
    <div class="page-header">
      <div class="page-title">我的钱包</div>
      <div class="page-desc">飞行报告通过审核后，工资自动发放到这里</div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <template v-else-if="wallet">
      <div class="grid grid-3">
        <div class="stat">
          <div class="stat-num">{{ wallet.balance }}</div>
          <div class="stat-label">钱包余额</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ wallet.total_hours }}</div>
          <div class="stat-label">累计飞行时长（小时）</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ wallet.rank }}</div>
          <div class="stat-label">飞行员等级 · 全站第 {{ wallet.siteRank }} 名</div>
        </div>
      </div>

      <div class="glass card" style="margin-top: 16px">
        <div class="card-title"><Icon name="ticket" :size="16" /> 工资发放记录</div>
        <div v-for="r in wallet.records" :key="r.id" class="list-item">
          <div class="list-main">
            <div class="list-title">{{ r.note || '飞行工资' }}</div>
            <div class="list-sub">{{ fmtTime(r.created_at) }}</div>
          </div>
          <span :class="r.amount >= 0 ? 'tag tag-green' : 'tag tag-red'">
            {{ r.amount >= 0 ? '+' : '-' }}{{ Math.abs(r.amount) }}
          </span>
        </div>
        <div v-if="!wallet.records.length" class="empty">
          <div class="empty-icon"><Icon name="ticket" :size="22" /></div>
          <div>暂无工资记录</div>
          <router-link class="btn btn-primary btn-sm" to="/airlines">去提交飞行报告</router-link>
        </div>
      </div>
    </template>
  </div>
</template>
