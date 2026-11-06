<script setup>
/**
 * ACIS 飞圈事件智能检索系统：公开检索首页，首次访问强制阅读使用须知。
 */
import { ref } from 'vue';
import { api } from '../api.js';
import { fmtMonth, showToast } from '../utils.js';
import Icon from '../components/Icon.vue';
import AcisWordmark from '../components/acis/AcisWordmark.vue';
import AcisAgreementModal from '../components/acis/AcisAgreementModal.vue';
import acisLogo from '../assets/acis-logo.png';

const q = ref('');
const sort = ref('latest');
const items = ref([]);
const total = ref(0);
const loading = ref(false);

const sortOptions = [
  { value: 'latest', label: '最新收录' },
  { value: 'hot', label: '热门事件' },
];

async function load() {
  loading.value = true;
  try {
    const params = new URLSearchParams();
    if (q.value.trim()) params.set('q', q.value.trim());
    if (sort.value !== 'latest') params.set('sort', sort.value);
    params.set('page', '1');
    const data = await api.get(`/api/archive?${params}`);
    items.value = data.items || [];
    total.value = data.total || 0;
  } catch (err) {
    showToast(err.message);
  } finally {
    loading.value = false;
  }
}

function setSort(next) {
  sort.value = next;
  load();
}

load();
</script>

<template>
  <div class="acis-page">
    <AcisAgreementModal />
    <div class="page acis-inner">
      <section class="acis-hero glass card">
        <div class="acis-brand">
          <img :src="acisLogo" alt="ACIS" class="acis-logo" />
          <div>
            <AcisWordmark />
            <div class="acis-tagline">Air Community Incident Search · 飞圈事件智能检索系统</div>
          </div>
        </div>
        <form class="acis-search" @submit.prevent="load">
          <Icon name="search" :size="17" />
          <input v-model="q" class="acis-search-input" maxlength="60" placeholder="搜索事件、社群、平台或人物 CID" />
          <button class="btn btn-primary" type="submit">检索</button>
        </form>
        <div class="acis-hero-actions">
          <router-link class="btn btn-primary btn-sm" to="/acis/submit"><Icon name="plus" :size="14" /> 投稿事件</router-link>
          <span class="acis-notice">使用、投稿与纠错全程免登录</span>
          <span class="acis-total">资料库已收录 {{ total }} 条事件</span>
        </div>
      </section>

      <div class="acis-tabs">
        <button
          v-for="option in sortOptions"
          :key="option.value"
          class="acis-tab"
          :class="{ on: sort === option.value }"
          type="button"
          @click="setSort(option.value)"
        >{{ option.label }}</button>
        <router-link class="acis-back" to="/archive">进入完整论坛</router-link>
      </div>

      <div v-if="loading" class="loading">检索中…</div>
      <div v-else-if="!items.length" class="glass card">
        <div class="empty">
          <div class="empty-icon"><Icon name="book" :size="22" /></div>
          <div>暂无匹配事件</div>
          <div class="card-sub" style="margin-top: 8px">可以换个关键词，或直接投稿补充</div>
        </div>
      </div>
      <div v-else class="acis-list">
        <router-link v-for="item in items" :key="item.id" class="glass card acis-card" :to="`/acis/${item.id}`">
          <div class="acis-card-head">
            <span v-if="item.featured" class="tag tag-orange">精选</span>
            <span class="tag tag-blue">{{ item.category }}</span>
            <span class="acis-date">{{ fmtMonth(item.occurred_at) }}</span>
          </div>
          <div class="acis-title">{{ item.title }}</div>
          <div class="acis-summary">{{ item.summary || '暂无摘要' }}</div>
          <div class="acis-meta">
            <span><Icon name="heart" :size="13" /> {{ item.like_count }}</span>
            <span><Icon name="message" :size="13" /> {{ item.comment_count }}</span>
            <span><Icon name="eye" :size="13" /> {{ item.view_count }}</span>
          </div>
        </router-link>
      </div>

      <div class="acis-footer-note">
        ACIS 资料由 CTY 人工收集与社区投稿共同完善，内容仅供参考。发现偏差请进入事件详情提交纠错。
      </div>
    </div>
  </div>
</template>

<style scoped>
.acis-page {
  min-height: calc(100vh - 56px);
  background:
    radial-gradient(circle at 50% 0%, rgba(10, 132, 255, 0.12), transparent 44%),
    radial-gradient(circle at 100% 90%, rgba(100, 210, 255, 0.1), transparent 40%);
}
.acis-inner { max-width: clamp(800px, 66vw, 1180px); }
.acis-hero { padding: 28px; margin-bottom: 16px; }
.acis-brand { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
.acis-logo { width: 76px; height: 72px; object-fit: contain; border-radius: 16px; background: rgba(255, 255, 255, 0.6); padding: 6px; }
.acis-tagline { margin-top: 8px; color: var(--text-2); font-size: 12.5px; letter-spacing: 0.3px; }
.acis-search {
  display: flex; align-items: center; gap: 10px; margin-top: 22px; padding: 8px 10px 8px 14px;
  border: 1px solid var(--border); border-radius: 999px; background: rgba(255, 255, 255, 0.66);
}
.acis-search-input { flex: 1; border: none; outline: none; background: transparent; font-size: 14px; color: var(--text); min-width: 0; }
.acis-hero-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 14px; }
.acis-notice { color: var(--gray); font-size: 12px; }
.acis-total { margin-left: auto; color: var(--gray); font-size: 12px; }
.acis-tabs { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.acis-tab {
  padding: 7px 15px; border-radius: 999px; border: 1px solid transparent; background: transparent;
  color: var(--text-2); font-size: 13px; cursor: pointer;
}
.acis-tab.on { color: #fff; background: var(--blue); border-color: var(--blue); }
.acis-back { margin-left: auto; color: var(--gray); font-size: 12px; text-decoration: none; }
.acis-back:hover { color: var(--blue); }
.acis-list { display: flex; flex-direction: column; gap: 12px; }
.acis-card { text-decoration: none; color: inherit; transition: transform 0.18s ease, border-color 0.18s ease; }
.acis-card:hover { transform: translateY(-2px); border-color: rgba(10, 132, 255, 0.4); }
.acis-card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.acis-date { color: var(--gray); font-size: 12px; }
.acis-title { margin-top: 8px; font-size: 17px; font-weight: 600; line-height: 1.45; }
.acis-summary { margin-top: 6px; color: var(--text-2); font-size: 13.5px; line-height: 1.65; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.acis-meta { display: flex; gap: 14px; margin-top: 10px; color: var(--gray); font-size: 12px; }
.acis-meta span { display: inline-flex; align-items: center; gap: 4px; }
.acis-footer-note { margin-top: 22px; padding-top: 14px; border-top: 1px dashed var(--border); color: var(--gray); font-size: 12px; line-height: 1.7; }
@media (max-width: 620px) {
  .acis-hero { padding: 18px; }
  .acis-brand { gap: 12px; }
  .acis-logo { width: 58px; height: 55px; }
  .acis-total { width: 100%; margin-left: 0; }
  .acis-search { border-radius: 16px; flex-wrap: wrap; }
}
</style>
