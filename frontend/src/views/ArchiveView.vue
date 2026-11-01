<script setup>
/**
 * 飞圈事件检索：公开检索页。只查事件档案，游客可浏览，投稿需要登录。
 */
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { fmtMonth, showToast } from '../utils.js';
import Icon from '../components/Icon.vue';
import SelectMenu from '../components/SelectMenu.vue';
import ArchiveMoyu from '../components/archive/ArchiveMoyu.vue';

const route = useRoute();
const router = useRouter();

const q = ref(String(route.query.q || ''));
const category = ref(String(route.query.category || ''));
const year = ref(String(route.query.year || ''));
const page = ref(Number(route.query.page) || 1);
const items = ref([]);
const total = ref(0);
const categories = ref([]);
const years = ref([]);
const disclaimer = ref('');
const loading = ref(false);
const pageSize = 12;

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
const hasFilter = computed(() => Boolean(q.value.trim() || category.value || year.value));
const yearOptions = computed(() => [
  { value: '', label: '全部年份' },
  ...years.value.map((value) => ({ value, label: `${value} 年` })),
]);

async function load() {
  loading.value = true;
  try {
    const params = new URLSearchParams();
    if (q.value) params.set('q', q.value);
    if (category.value) params.set('category', category.value);
    if (year.value) params.set('year', year.value);
    if (page.value > 1) params.set('page', String(page.value));
    const data = await api.get(`/api/archive${params.toString() ? `?${params}` : ''}`);
    items.value = data.items || [];
    total.value = data.total || 0;
    categories.value = data.categories || [];
    years.value = data.years || [];
    disclaimer.value = data.disclaimer || '';
  } catch (err) {
    showToast(err.message);
  } finally {
    loading.value = false;
  }
}

function applyFilters() {
  page.value = 1;
  syncUrl();
}

function syncUrl() {
  const query = {};
  if (q.value.trim()) query.q = q.value.trim();
  if (category.value) query.category = category.value;
  if (year.value) query.year = year.value;
  if (page.value > 1) query.page = String(page.value);
  router.replace({ name: 'archive', query });
}

function goPage(next) {
  page.value = Math.min(pageCount.value, Math.max(1, next));
  syncUrl();
}

function clearFilters() {
  q.value = '';
  category.value = '';
  year.value = '';
  page.value = 1;
  syncUrl();
}

watch(() => route.query, () => {
  q.value = String(route.query.q || '');
  category.value = String(route.query.category || '');
  year.value = String(route.query.year || '');
  page.value = Number(route.query.page) || 1;
  load();
}, { immediate: true });
</script>

<template>
  <div class="page archive-page">
    <div class="page-header">
      <div>
        <div class="page-title">飞圈事件检索</div>
        <div class="page-desc">检索飞圈重要事件与资料，内容来自公开渠道与社区投稿</div>
      </div>
      <router-link class="btn btn-primary btn-sm" to="/archive/submit">
        <Icon name="plus" :size="14" /> 我要投稿
      </router-link>
    </div>

    <div class="glass card search-card">
      <form class="search-row" @submit.prevent="applyFilters">
        <div class="search-input-wrap">
          <Icon name="search" :size="16" />
          <input v-model="q" class="input search-input" maxlength="60" placeholder="输入关键词，例如事件名、平台、航司或标签" />
        </div>
        <button class="btn btn-primary" type="submit">检索</button>
      </form>
      <div class="filter-row">
        <button
          v-for="c in categories"
          :key="c"
          class="filter-chip"
          :class="{ on: category === c }"
          type="button"
          @click="category = category === c ? '' : c; applyFilters()"
        >{{ c }}</button>
        <SelectMenu v-model="year" :options="yearOptions" style="width: 138px" @update:model-value="applyFilters" />
        <button v-if="q || category || year" class="btn btn-ghost btn-sm" type="button" @click="clearFilters">清空</button>
      </div>
    </div>

    <div v-if="loading" class="loading">检索中…</div>

    <template v-else>
      <div class="result-meta">共 {{ total }} 条事件</div>
      <div v-if="items.length" class="archive-list">
        <router-link v-for="item in items" :key="item.id" class="glass card archive-card" :to="`/archive/${item.id}`">
          <div v-if="item.cover_url" class="archive-cover" :style="{ backgroundImage: `url(${item.cover_url})` }" />
          <div class="archive-body">
            <div class="archive-title">{{ item.title }}</div>
            <div class="archive-summary">{{ item.summary || '暂无摘要' }}</div>
            <div class="archive-meta">
              <span class="tag tag-blue">{{ item.category }}</span>
              <span class="archive-date">{{ fmtMonth(item.occurred_at) }}</span>
            </div>
            <div v-if="item.tags?.length" class="archive-tags">
              <span v-for="tag in item.tags" :key="tag" class="archive-tag">#{{ tag }}</span>
            </div>
          </div>
        </router-link>
      </div>
      <div v-else class="glass card">
        <div class="empty">
          <div class="empty-icon"><Icon name="book" :size="22" /></div>
          <div>没有找到匹配的事件</div>
          <div class="card-sub" style="margin-top: 8px">换个关键词，或清空筛选条件再试</div>
        </div>
      </div>

      <div v-if="pageCount > 1" class="pager">
        <button class="btn btn-ghost btn-sm" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span class="pager-text">{{ page }} / {{ pageCount }}</span>
        <button class="btn btn-ghost btn-sm" :disabled="page >= pageCount" @click="goPage(page + 1)">下一页</button>
      </div>
    </template>

    <div v-if="disclaimer" class="archive-disclaimer">{{ disclaimer }}</div>

    <ArchiveMoyu :prompt="!loading && !items.length && hasFilter" />
  </div>
</template>

<style scoped>
.archive-page { max-width: clamp(760px, 64vw, 1180px); }
.search-card { margin-bottom: 18px; }
.search-row { display: flex; gap: 10px; align-items: center; }
.search-input-wrap { flex: 1; display: flex; align-items: center; gap: 8px; }
.search-input { flex: 1; }
.filter-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 12px; }
.filter-chip {
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.filter-chip:hover { color: var(--text); }
.filter-chip.on { color: #fff; background: var(--blue); border-color: var(--blue); }
.filter-select { width: 130px; }
.result-meta { color: var(--gray); font-size: 12.5px; margin: 0 0 10px 2px; }
.archive-list { display: flex; flex-direction: column; gap: 12px; }
.archive-card {
  display: flex;
  gap: 16px;
  text-decoration: none;
  color: inherit;
  transition: transform 0.18s ease, border-color 0.18s ease;
}
.archive-card:hover { transform: translateY(-2px); border-color: rgba(10, 132, 255, 0.35); }
.archive-cover {
  width: 150px;
  min-height: 110px;
  flex: none;
  border-radius: var(--radius-sm);
  background-size: cover;
  background-position: center;
  background-color: var(--surface-solid);
}
.archive-body { flex: 1; min-width: 0; }
.archive-title { font-size: 16px; font-weight: 600; line-height: 1.4; }
.archive-summary { margin-top: 6px; color: var(--text-2); font-size: 13.5px; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.archive-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; font-size: 12px; color: var(--gray); }
.archive-tags { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.archive-tag { font-size: 12px; color: var(--blue); }
.pager { display: flex; align-items: center; justify-content: center; gap: 14px; margin-top: 20px; }
.pager-text { font-size: 12.5px; color: var(--text-2); }
.archive-disclaimer { margin-top: 22px; padding-top: 14px; border-top: 1px dashed var(--border); color: var(--gray); font-size: 12px; line-height: 1.7; }
@media (max-width: 720px) {
  .search-row { flex-direction: column; align-items: stretch; }
  .archive-card { flex-direction: column; }
  .archive-cover { width: 100%; height: 150px; }
}
</style>
