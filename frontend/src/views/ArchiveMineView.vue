<script setup>
/**
 * 我的收藏：登录用户收藏的飞圈事件。
 */
import { ref } from 'vue';
import { api } from '../api.js';
import { fmtMonth, showToast } from '../utils.js';
import Icon from '../components/Icon.vue';

const items = ref([]);
const loading = ref(true);

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/archive/mine/favorites');
    items.value = data.items || [];
  } catch (err) {
    showToast(err.message);
  } finally {
    loading.value = false;
  }
}

async function removeFavorite(item) {
  try {
    const data = await api.post(`/api/archive/${item.id}/favorite`);
    if (!data.favorited) {
      items.value = items.value.filter((row) => row.id !== item.id);
      showToast('已取消收藏');
    }
  } catch (err) {
    showToast(err.message);
  }
}

load();
</script>

<template>
  <div class="page archive-mine-page">
    <div class="page-header">
      <div>
        <div class="page-title">我的收藏</div>
        <div class="page-desc">收藏的飞圈事件，方便之后回看</div>
      </div>
      <div class="header-actions">
        <router-link class="btn btn-ghost btn-sm" to="/acis">返回检索</router-link>
        <router-link class="btn btn-primary btn-sm" to="/acis/submit">我要投稿</router-link>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!items.length" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="bookmark" :size="22" /></div>
        <div>还没有收藏任何事件</div>
        <router-link class="btn btn-ghost btn-sm" to="/acis" style="margin-top: 12px">去逛逛</router-link>
      </div>
    </div>
    <div v-else class="favorite-list">
      <article v-for="item in items" :key="item.id" class="glass card favorite-card">
        <router-link class="favorite-main" :to="`/acis/${item.id}`">
          <div class="favorite-title">{{ item.title }}</div>
          <div class="favorite-summary">{{ item.summary || '暂无摘要' }}</div>
          <div class="favorite-meta">
            <span class="tag tag-blue">{{ item.category }}</span>
            <span>{{ fmtMonth(item.occurred_at) }}</span>
            <span>{{ item.like_count }} 赞</span>
            <span>{{ item.comment_count }} 评论</span>
          </div>
        </router-link>
        <button class="btn btn-ghost btn-sm" type="button" @click="removeFavorite(item)">取消收藏</button>
      </article>
    </div>
  </div>
</template>

<style scoped>
.archive-mine-page { max-width: clamp(760px, 60vw, 1080px); }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.favorite-list { display: flex; flex-direction: column; gap: 12px; }
.favorite-card { display: flex; align-items: center; gap: 16px; }
.favorite-main { flex: 1; min-width: 0; text-decoration: none; color: inherit; }
.favorite-title { font-size: 16px; font-weight: 600; line-height: 1.45; }
.favorite-summary { margin-top: 5px; color: var(--text-2); font-size: 13px; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.favorite-meta { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-top: 8px; color: var(--gray); font-size: 12px; }
@media (max-width: 720px) {
  .favorite-card { flex-direction: column; align-items: stretch; }
}
</style>
