<script setup>
import { provide } from 'vue';
import Icon from '../components/Icon.vue';
import VaAirlineHero from '../components/va/VaAirlineHero.vue';
import VaManagePanel from '../components/va/VaManagePanel.vue';
import VaReportsPanel from '../components/va/VaReportsPanel.vue';
import VaMembersPanel from '../components/va/VaMembersPanel.vue';
import VaRoutesPanel from '../components/va/VaRoutesPanel.vue';
import VaExamsPanel from '../components/va/VaExamsPanel.vue';
import VaPublicPanel from '../components/va/VaPublicPanel.vue';
import VaPostsPanel from '../components/va/VaPostsPanel.vue';
import { useAirlineDetailPage } from '../composables/useAirlineDetailPage.js';

const page = useAirlineDetailPage();
provide('airlinePage', page);

const {
  loading, error, airline, tab, canManage, isMember,
} = page;
</script>

<template>
  <div class="page">
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="error" class="glass card">
      <div class="alert alert-err" style="margin-bottom: 14px">{{ error }}</div>
      <router-link class="btn btn-ghost btn-sm" to="/airlines">
        <Icon name="chevron" :size="14" style="transform: rotate(90deg)" /> 返回航司列表
      </router-link>
    </div>

    <template v-else-if="airline">
      <VaAirlineHero />
      <VaManagePanel v-if="tab === 'manage' && canManage" />
      <VaReportsPanel v-if="tab === 'reports' && isMember" />
      <VaMembersPanel v-if="tab === 'members'" />
      <VaRoutesPanel v-if="tab === 'routes'" />
      <VaExamsPanel v-if="tab === 'exams' && isMember" />
      <VaPublicPanel v-if="tab === 'public' && isMember" />
      <VaPostsPanel v-if="tab === 'posts' && isMember" />
    </template>
  </div>
</template>

<style scoped>
.va-badge {
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: var(--blue);
  background-size: cover;
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0.5px;
}

/* 动态条目 */
.post-item {
  padding: 16px 12px;
  margin: 0 -8px;
  border-radius: 12px;
  border-bottom: 1px solid var(--border);
  transition: background 0.16s ease;
}
.post-item:hover { background: var(--surface); }
.post-item:last-child { border-bottom: none; }
.post-comments {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface);
}
/* 点赞后心形变红填充 */
.btn-ghost.liked { color: #ff3b30; }
.btn-ghost.liked :deep(svg) { fill: currentColor; }

/* ---------- 考核页晋升进度 ---------- */
.exam-progress {
  margin-top: 14px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--surface);
}
.exam-progress-title { font-size: 13.5px; font-weight: 500; }
.exam-progress-bar {
  margin-top: 9px;
  height: 6px;
  border-radius: 999px;
  background: var(--border);
  overflow: hidden;
}
.exam-progress-bar i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--blue);
  transition: width 0.3s ease;
}

/* ---------- 对外主页页内预览 ---------- */
.pub-preview {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px dashed var(--border);
}
/* 预览内的卡片用轻量底色：外层已是毛玻璃，内层再叠 backdrop-filter 会成倍放大采样开销 */
.pub-preview-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}
.pub-preview-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-2);
}
.pub-preview-bar code {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--blue);
  background: rgba(0, 113, 227, 0.1);
}
.pub-preview-hint {
  font-size: 12px;
  font-weight: 400;
  color: var(--gray);
}
.pub-preview-slogan {
  margin-top: 4px;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--blue);
}
.pub-preview-desc {
  margin-top: 10px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}
.pub-preview-welcome { border-left: 3px solid var(--blue); }
.hourly-hint { font-size: 12px; color: var(--gray); }
.pub-preview-welcome-text {
  font-size: 13.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  margin-top: 6px;
}
</style>
