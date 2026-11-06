<script setup>
import { ref } from 'vue';
import { api } from '../api.js';
import AirportInput from '../components/AirportInput.vue';

const ids = ref('');
const loading = ref(false);
const error = ref('');
const reports = ref([]);

async function query() {
  error.value = '';
  reports.value = [];
  if (!ids.value.trim()) return (error.value = '请输入 ICAO 机场代码');
  loading.value = true;
  try {
    // 上游是多源竞速，最坏 6s 超时叠加，默认 12s 会把慢一点的查询掐死在半路 —— 表现为「查不到」
    const data = await api.get(`/api/weather/taf?ids=${encodeURIComponent(ids.value.trim().toUpperCase())}`, 25000);
    reports.value = data.reports;
    if (!reports.value.length) error.value = '未查询到该机场的预报，请检查 ICAO 代码';
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">TAF 报文查询</div>
      <div class="page-desc">全球机场天气预报，数据来源 aviationweather.gov</div>
    </div>

    <div class="glass card" style="max-width: 720px">
      <div class="input-row" style="max-width: 560px">
        <AirportInput v-model="ids" multiple placeholder="ICAO 代码，多个用逗号分隔，如 ZSPD,ZBAA" />
        <button class="btn btn-primary" :disabled="loading" @click="query">
          {{ loading ? '查询中…' : '查询' }}
        </button>
      </div>
      <div class="hint">支持同时查询多个机场，英文逗号分隔</div>

      <div v-if="error" class="alert alert-err" style="margin-top: 16px; margin-bottom: 0">{{ error }}</div>

      <div v-for="r in reports" :key="r.icaoId + r.reportTime" style="margin-top: 20px">
        <div style="display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; flex-wrap: wrap">
          <strong style="font-size: 16px">{{ r.icaoId }}</strong>
          <span class="tag tag-blue">{{ r.reportTime }}</span>
          <span style="font-size: 12.5px; color: var(--gray)">{{ r.name }}</span>
        </div>
        <div class="code-block">{{ r.rawOb || '无报文内容' }}</div>
      </div>
    </div>
  </div>
</template>
