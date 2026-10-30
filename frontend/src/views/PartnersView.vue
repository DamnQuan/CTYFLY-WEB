<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';
import { safeHttpUrl, showToast } from '../utils.js';
import Icon from '../components/Icon.vue';

const partners = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await api.get('/api/partners');
    partners.value = data.partners || [];
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 56vw, 1100px)">
    <div class="page-header">
      <div class="page-title">合作伙伴</div>
      <div class="page-desc">与我们携手同行的平台与社区</div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!partners.length" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="link" :size="22" /></div>
        <div>暂无合作伙伴</div>
      </div>
    </div>

    <div v-else class="grid grid-2">
      <!-- href 协议白名单：仅 http/https 渲染为链接，其余降级为纯文本卡片 -->
      <component
        v-for="p in partners" :key="p.id"
        :is="safeHttpUrl(p.url) ? 'a' : 'div'"
        class="glass card partner-card"
        :href="safeHttpUrl(p.url) || undefined"
        :target="safeHttpUrl(p.url) ? '_blank' : undefined"
        rel="noopener nofollow"
      >
        <div class="partner-logo-wrap">
          <img v-if="p.logo" :src="p.logo" :alt="p.name" class="partner-logo" />
          <span v-else class="partner-name-fallback">{{ p.name }}</span>
        </div>
        <div class="partner-info">
          <div class="partner-name">{{ p.name }}</div>
          <div class="partner-url">{{ p.url.replace(/^https?:\/\//, '') }}</div>
          <div v-if="p.description" class="partner-desc">{{ p.description }}</div>
        </div>
        <span v-if="safeHttpUrl(p.url)" class="partner-visit">访问 <Icon name="external" :size="13" /></span>
      </component>
    </div>

    <div class="glass card" style="margin-top: 16px">
      <div class="card-sub" style="line-height: 1.9">
        合作伙伴与 CTYFLY 互相导流、联合举办活动。想成为我们的合作伙伴？
        通过 <router-link to="/tickets/new" class="link">工单中心</router-link> 联系我们。
      </div>
    </div>
  </div>
</template>

<style scoped>
.partner-card {
  display: flex;
  align-items: center;
  gap: 16px;
  text-decoration: none;
  transition: transform 0.18s cubic-bezier(0.34, 1.4, 0.64, 1), box-shadow 0.18s ease, border-color 0.18s ease;
}
.partner-card:hover {
  transform: translateY(-3px);
  border-color: rgba(10, 132, 255, 0.4);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.12);
}
.partner-logo-wrap {
  width: 92px;
  height: 72px;
  border-radius: 12px;
  background: var(--surface-solid);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}
.partner-logo {
  max-width: 84px;
  max-height: 60px;
  object-fit: contain;
}
.partner-name-fallback { font-size: 13px; font-weight: 700; color: var(--text); }
.partner-info { min-width: 0; flex: 1; }
.partner-name { font-size: 16px; font-weight: 700; color: var(--text); }
.partner-url { font-size: 12.5px; color: var(--text-2); margin-top: 4px; }
.partner-desc {
  font-size: 12.5px;
  color: var(--text-2);
  margin-top: 6px;
  line-height: 1.55;
  word-break: break-word;
}
.partner-visit {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
  color: var(--blue);
  flex-shrink: 0;
}
.grid-2 .partner-card { margin: 0; }
</style>
