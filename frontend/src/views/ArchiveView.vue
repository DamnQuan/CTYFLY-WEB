<script setup>
/**
 * 飞圈事件检索：公开论坛式信息流。最新、最热、精选，支持点赞与收藏。
 */
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { fmtMonth, showToast } from '../utils.js';
import { useAuthStore } from '../stores/auth.js';
import Icon from '../components/Icon.vue';
import SelectMenu from '../components/SelectMenu.vue';
import ArchiveMoyu from '../components/archive/ArchiveMoyu.vue';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const q = ref(String(route.query.q || ''));
const category = ref(String(route.query.category || ''));
const year = ref(String(route.query.year || ''));
const sort = ref(String(route.query.sort || 'latest'));
const hotWindow = ref(String(route.query.window || 'week'));
const page = ref(Number(route.query.page) || 1);
const items = ref([]);
const total = ref(0);
const categories = ref([]);
const years = ref([]);
const disclaimer = ref('');
const loading = ref(false);
const pageSize = 12;
const busy = ref(0);

const sortOptions = [
  { value: 'latest', label: '最新' },
  { value: 'hot', label: '最热' },
  { value: 'featured', label: '精选' },
];
const windowOptions = [
  { value: 'day', label: '日榜' },
  { value: 'week', label: '周榜' },
  { value: 'month', label: '月榜' },
  { value: 'all', label: '总榜' },
];

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
    if (sort.value !== 'latest') params.set('sort', sort.value);
    if (sort.value === 'hot' && hotWindow.value !== 'week') params.set('window', hotWindow.value);
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

function syncUrl() {
  const query = {};
  if (q.value.trim()) query.q = q.value.trim();
  if (category.value) query.category = category.value;
  if (year.value) query.year = year.value;
  if (sort.value !== 'latest') query.sort = sort.value;
  if (sort.value === 'hot' && hotWindow.value !== 'week') query.window = hotWindow.value;
  if (page.value > 1) query.page = String(page.value);
  router.replace({ name: 'archive', query });
}

function applyFilters() {
  page.value = 1;
  syncUrl();
}

function setSort(next) {
  sort.value = next;
  page.value = 1;
  syncUrl();
}

function setWindow(next) {
  hotWindow.value = next;
  page.value = 1;
  syncUrl();
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

function requireLogin() {
  if (auth.isLoggedIn) return true;
  router.push({ name: 'login', query: { redirect: route.fullPath } });
  return false;
}

async function toggleLike(item) {
  if (!requireLogin() || busy.value) return;
  busy.value = item.id;
  try {
    const data = await api.post(`/api/archive/${item.id}/like`);
    item.liked = data.liked;
    item.like_count = data.count;
  } catch (err) {
    showToast(err.message);
  } finally {
    busy.value = 0;
  }
}

async function toggleFavorite(item) {
  if (!requireLogin() || busy.value) return;
  busy.value = item.id;
  try {
    const data = await api.post(`/api/archive/${item.id}/favorite`);
    item.favorited = data.favorited;
    item.favorite_count = data.count;
  } catch (err) {
    showToast(err.message);
  } finally {
    busy.value = 0;
  }
}

watch(() => route.query, () => {
  q.value = String(route.query.q || '');
  category.value = String(route.query.category || '');
  year.value = String(route.query.year || '');
  sort.value = String(route.query.sort || 'latest');
  hotWindow.value = String(route.query.window || 'week');
  page.value = Number(route.query.page) || 1;
  load();
}, { immediate: true });
</script>

<template>
  <div class="page archive-page">
    <div class="page-header">
      <div>
        <div class="page-title">飞圈事件检索</div>
        <div class="page-desc">最新事件、热门讨论与编辑精选，游客可浏览，互动需登录</div>
      </div>
      <div class="header-actions">
        <router-link class="btn btn-ghost btn-sm" to="/archive/mine">
          <Icon name="bookmark" :size="14" /> 我的收藏
        </router-link>
        <router-link class="btn btn-primary btn-sm" to="/archive/submit">
          <Icon name="plus" :size="14" /> 我要投稿
        </router-link>
      </div>
    </div>

    <div class="forum-tabs">
      <button
        v-for="tab in sortOptions"
        :key="tab.value"
        class="forum-tab"
        :class="{ on: sort === tab.value }"
        type="button"
        @click="setSort(tab.value)"
      >{{ tab.label }}</button>
      <div v-if="sort === 'hot'" class="hot-window">
        <SelectMenu :model-value="hotWindow" :options="windowOptions" style="width: 110px" @update:model-value="setWindow" />
      </div>
      <div class="tab-spacer" />
      <router-link class="tab-mine" to="/archive/mine">收藏夹 <Icon name="chevron" :size="12" /></router-link>
    </div>

    <div class="glass card search-card">
      <form class="search-row" @submit.prevent="applyFilters">
        <div class="search-input-wrap">
          <Icon name="search" :size="16" />
          <input v-model="q" class="input search-input" maxlength="60" placeholder="输入事件名、平台、航司或关键词" />
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

    <div v-if="loading" class="loading">加载中…</div>

    <template v-else>
      <div class="result-meta">
        <span>共 {{ total }} 条事件</span>
        <span v-if="sort === 'hot'">按点赞、评论、收藏与浏览综合排序</span>
        <span v-else-if="sort === 'featured'">管理员精选内容</span>
        <span v-else>按发布时间倒序</span>
      </div>
      <div v-if="items.length" class="archive-list">
        <article v-for="item in items" :key="item.id" class="glass card archive-card">
          <router-link class="archive-main" :to="`/archive/${item.id}`">
            <div v-if="item.cover_url" class="archive-cover" :style="{ backgroundImage: `url(${item.cover_url})` }" />
            <div class="archive-body">
              <div class="archive-title-row">
                <span v-if="item.featured" class="tag tag-orange">精选</span>
                <div class="archive-title">{{ item.title }}</div>
              </div>
              <div class="archive-summary">{{ item.summary || '暂无摘要' }}</div>
              <div class="archive-meta">
                <span class="tag tag-blue">{{ item.category }}</span>
                <span class="archive-date">{{ fmtMonth(item.occurred_at) }}</span>
                <span class="archive-stat"><Icon name="eye" :size="13" /> {{ item.view_count }}</span>
                <span class="archive-stat"><Icon name="message" :size="13" /> {{ item.comment_count }}</span>
              </div>
              <div v-if="item.tags?.length" class="archive-tags">
                <span v-for="tag in item.tags" :key="tag" class="archive-tag">#{{ tag }}</span>
              </div>
            </div>
          </router-link>
          <div class="archive-actions">
            <button class="stat-btn" :class="{ on: item.liked }" type="button" @click="toggleLike(item)">
              <Icon name="heart" :size="15" /> {{ item.like_count }}
            </button>
            <button class="stat-btn" :class="{ on: item.favorited }" type="button" @click="toggleFavorite(item)">
              <Icon name="bookmark" :size="15" /> {{ item.favorite_count }}
            </button>
            <router-link class="stat-btn" :to="`/archive/${item.id}#comments`">
              <Icon name="message" :size="15" /> {{ item.comment_count }}
            </router-link>
          </div>
        </article>
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
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.forum-tabs { display: flex; align-items: center; gap: 6px; margin: 0 0 14px; flex-wrap: wrap; }
.forum-tab {
  padding: 8px 16px;
  border-radius: 999px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-2);
  font-size: 13.5px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.forum-tab:hover { color: var(--text); background: var(--surface); }
.forum-tab.on { color: #fff; background: var(--blue); border-color: var(--blue); }
.hot-window { margin-left: 2px; }
.tab-spacer { flex: 1; }
.tab-mine { display: inline-flex; align-items: center; gap: 4px; color: var(--gray); font-size: 12.5px; text-decoration: none; }
.search-card { margin-bottom: 18px; }
.search-row { display: flex; gap: 10px; align-items: center; }
.search-input-wrap { flex: 1; display: flex; align-items: center; gap: 8px; }
.search-input { flex: 1; }
.filter-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 12px; }
.filter-chip {
  padding: 6px 12px; border-radius: 999px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text-2); font-size: 12.5px; cursor: pointer;
  transition: all 0.18s ease;
}
.filter-chip:hover { color: var(--text); }
.filter-chip.on { color: #fff; background: var(--blue); border-color: var(--blue); }
.result-meta { display: flex; justify-content: space-between; gap: 10px; color: var(--gray); font-size: 12.5px; margin: 0 0 10px 2px; flex-wrap: wrap; }
.archive-list { display: flex; flex-direction: column; gap: 12px; }
.archive-card { padding: 0; overflow: hidden; }
.archive-main { display: flex; gap: 16px; text-decoration: none; color: inherit; padding: 16px; }
.archive-cover {
  width: 150px; min-height: 110px; flex: none; border-radius: var(--radius-sm);
  background-size: cover; background-position: center; background-color: var(--surface-solid);
}
.archive-body { flex: 1; min-width: 0; }
.archive-title-row { display: flex; align-items: center; gap: 8px; }
.archive-title { font-size: 16px; font-weight: 600; line-height: 1.4; }
.archive-summary { margin-top: 6px; color: var(--text-2); font-size: 13.5px; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.archive-meta { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 10px; font-size: 12px; color: var(--gray); }
.archive-stat { display: inline-flex; align-items: center; gap: 4px; }
.archive-tags { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.archive-tag { font-size: 12px; color: var(--blue); }
.archive-actions { display: flex; gap: 8px; padding: 0 16px 14px; border-top: 1px dashed var(--border); padding-top: 10px; flex-wrap: wrap; }
.stat-btn {
  display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border);
  background: transparent; color: var(--text-2); border-radius: 999px; padding: 5px 11px;
  font-size: 12.5px; cursor: pointer; text-decoration: none; transition: all 0.18s ease;
}
.stat-btn:hover { color: var(--text); border-color: rgba(10, 132, 255, 0.4); }
.stat-btn.on { color: var(--blue); border-color: rgba(10, 132, 255, 0.45); background: rgba(10, 132, 255, 0.08); }
.pager { display: flex; align-items: center; justify-content: center; gap: 14px; margin-top: 20px; }
.pager-text { font-size: 12.5px; color: var(--text-2); }
.archive-disclaimer { margin-top: 22px; padding-top: 14px; border-top: 1px dashed var(--border); color: var(--gray); font-size: 12px; line-height: 1.7; }
@media (max-width: 720px) {
  .search-row { flex-direction: column; align-items: stretch; }
  .archive-main { flex-direction: column; }
  .archive-cover { width: 100%; height: 150px; }
}
</style>
