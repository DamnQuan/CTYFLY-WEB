<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';
import { fmtTime, EVENT_STATUS, showToast } from '../utils.js';
import Icon from '../components/Icon.vue';

const signups = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await api.get('/api/events/signups/mine');
    signups.value = data.signups;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">历史报名</div>
      <div class="page-desc">您报名过的全部活动记录，含已结束与已取消的活动</div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!signups.length" class="glass card empty">
      <div class="empty-icon"><Icon name="calendar" :size="22" /></div>
      <div>暂无报名记录</div>
      <router-link class="btn btn-primary btn-sm" to="/events">去看看连飞活动</router-link>
    </div>

    <div v-else class="glass card">
      <div v-for="s in signups" :key="s.event_id" class="list-item">
        <div class="list-main">
          <div class="list-title">{{ s.title }}</div>
          <div class="list-sub">
            {{ s.dep }} → {{ s.arr }} · {{ fmtTime(s.start_time) }} ~ {{ fmtTime(s.end_time) }}
          </div>
          <div class="list-sub">
            <span class="tag" style="margin-right: 6px">呼号 {{ s.callsign }}</span>
            <span :class="s.role === 'atc' ? 'tag tag-purple' : 'tag'">
              {{ s.role === 'atc' ? '管制席位' : '飞行员' }}
            </span>
            <span style="margin-left: 6px">报名于 {{ fmtTime(s.signed_at) }}</span>
          </div>
        </div>
        <span :class="['tag', EVENT_STATUS[s.status]?.cls]">{{ EVENT_STATUS[s.status]?.text }}</span>
      </div>
    </div>
  </div>
</template>
