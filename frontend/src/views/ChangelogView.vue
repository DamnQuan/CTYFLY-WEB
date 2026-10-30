<script setup>
/**
 * 更新日志 —— 公开页面：时间线式版本列表，按接口返回顺序，时间倒序展示。
 */
import { ref, onMounted } from 'vue';
import { api } from '../api.js';
import Icon from '../components/Icon.vue';

const changelogs = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await api.get('/api/changelogs');
    changelogs.value = data.changelogs || [];
  } catch {
    changelogs.value = [];
  }
  loading.value = false;
});
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 56vw, 1100px)">
    <div class="page-header">
      <div class="page-title">更新日志</div>
      <div class="page-desc">平台功能迭代与修复记录</div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!changelogs.length" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="megaphone" :size="22" /></div>
        <div>暂无更新记录</div>
      </div>
    </div>

    <div v-else class="timeline">
      <div v-for="c in changelogs" :key="c.id" class="timeline-item">
        <div class="timeline-dot"></div>
        <div class="glass card timeline-card">
          <div class="timeline-head">
            <span class="tag tag-blue">{{ c.version }}</span>
            <span class="timeline-title">{{ c.title }}</span>
            <span class="timeline-date">{{ c.released_at }}</span>
          </div>
          <div class="timeline-body">{{ c.body }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.timeline { position: relative; padding-left: 18px; }
/* 时间线竖线：用变量色，不引入新底色 */
.timeline::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 6px;
  bottom: 6px;
  width: 1px;
  background: var(--border);
}
.timeline-item { position: relative; margin-bottom: 14px; }
.timeline-item:last-child { margin-bottom: 0; }
.timeline-dot {
  position: absolute;
  left: -18px;
  top: 20px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--blue);
}
.timeline-card { padding: 16px 18px; }
.timeline-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.timeline-head .tag { flex-shrink: 0; }
.timeline-title { font-weight: 700; font-size: 15px; color: var(--text); }
.timeline-date { font-size: 12.5px; color: var(--gray); margin-left: auto; }
.timeline-body {
  margin-top: 8px;
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
