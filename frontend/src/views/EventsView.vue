<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';
import { fmtTime, EVENT_STATUS, showToast } from '../utils.js';
import Icon from '../components/Icon.vue';

const events = ref([]);
const loading = ref(true);

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/events');
    events.value = data.events;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);
</script>

<template>
  <div class="page">
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
      <div>
        <div class="page-title">连飞活动</div>
        <div class="page-desc">报名参加每周连飞活动，与大家一起翱翔蓝天</div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center">

      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!events.length" class="glass card empty">暂无活动</div>

    <div v-else class="grid grid-2">
      <div v-for="e in events" :key="e.id" class="glass card">
        <div style="display: flex; justify-content: space-between; align-items: flex-start">
          <div>
            <div class="card-title" style="margin-bottom: 2px">{{ e.title }}</div>
            <div class="card-sub" style="margin-bottom: 10px">
              {{ e.dep }} → {{ e.arr }} · {{ fmtTime(e.start_time) }} ~ {{ fmtTime(e.end_time) }}
            </div>
          </div>
          <span :class="['tag', EVENT_STATUS[e.status]?.cls]">{{ EVENT_STATUS[e.status]?.text }}</span>
        </div>
        <p style="font-size: 13.5px; color: var(--text-2); white-space: pre-wrap; margin-bottom: 14px">{{ e.description }}</p>
        <div style="display: flex; align-items: center; justify-content: space-between">
          <div style="font-size: 13px; color: var(--gray)">
            <Icon name="users" :size="14" /> {{ e.signup_count }} 人报名 · 发起人 {{ e.creator || '官方' }}
          </div>
          <router-link
            class="btn btn-primary btn-sm"
            :to="`/events/${e.id}/briefing`"
          >进入简报</router-link>
        </div>
      </div>
    </div>
  </div>
</template>
