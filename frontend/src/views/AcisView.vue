<script setup>
/**
 * ACIS 飞圈事件智能检索系统：公开检索首页，首次访问强制阅读使用须知。
 */
import { ref } from 'vue';
import { api } from '../api.js';
import { fmtMonth, showToast } from '../utils.js';
import Icon from '../components/Icon.vue';
import AcisAgreementModal from '../components/acis/AcisAgreementModal.vue';
import acisGlyph from '../assets/acis-glyph.png';

const q = ref('');
const sort = ref('pinyin');
const items = ref([]);
const total = ref(0);
const loading = ref(false);
const pinyinCollator = (() => {
  try {
    return new Intl.Collator('zh-Hans-CN', { usage: 'sort', sensitivity: 'base' });
  } catch {
    return { compare: (a, b) => String(a).localeCompare(String(b), 'zh-CN') };
  }
})();

const sortOptions = [
  { value: 'pinyin', label: '标题拼音' },
  { value: 'latest', label: '最新收录' },
  { value: 'hot', label: '热门事件' },
];

async function fetchAll(params) {
  const collected = [];
  let serverTotal = 0;
  for (let page = 1; page <= 60; page += 1) {
    params.set('page', String(page));
    const data = await api.get(`/api/archive?${params}`);
    const batch = data.items || [];
    collected.push(...batch);
    serverTotal = data.total || 0;
    if (!batch.length || collected.length >= serverTotal) break;
  }
  total.value = serverTotal;
  return collected;
}

function titleRank(title) {
  const first = String(title || '').trim().replace(/^[^\p{L}\p{N}]+/u, '').charAt(0);
  return /[A-Za-z0-9]/.test(first) ? 0 : 1;
}

function sortItems(list) {
  if (sort.value !== 'pinyin') return list;
  return [...list].sort((a, b) => {
    const rank = titleRank(a.title) - titleRank(b.title);
    if (rank) return rank;
    const diff = pinyinCollator.compare(a.title || '', b.title || '');
    return diff || a.id - b.id;
  });
}

async function load() {
  loading.value = true;
  try {
    const params = new URLSearchParams();
    if (q.value.trim()) params.set('q', q.value.trim());
    if (sort.value !== 'pinyin' && sort.value !== 'latest') params.set('sort', sort.value);
    const all = await fetchAll(params);
    items.value = sortItems(all);
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
      <section class="acis-hero">
        <img :src="acisGlyph" alt="" class="acis-watermark" aria-hidden="true" />
        <div class="acis-hero-glow" aria-hidden="true"></div>

        <div class="acis-brand">
          <div class="acis-brand-copy">
            <div class="acis-kicker">CTY · INCIDENT INTELLIGENCE</div>
            <img :src="acisGlyph" alt="ACIS" class="acis-hero-glyph" />
            <div class="acis-tagline">
              <span class="acis-tagline-en">Air Community Incident Search</span>
              <span class="acis-tagline-dot" aria-hidden="true"></span>
              <span class="acis-tagline-cn">飞圈事件智能检索系统</span>
            </div>
          </div>
        </div>

        <form class="acis-search" @submit.prevent="load">
          <span class="acis-search-icon"><Icon name="search" :size="17" /></span>
          <input v-model="q" class="acis-search-input" maxlength="60" placeholder="搜索事件、社群、平台或人物 CID" />
          <button class="acis-search-btn" type="submit">检索</button>
        </form>

        <div class="acis-hero-actions">
          <router-link class="acis-submit-btn" to="/acis/submit"><Icon name="plus" :size="14" /> 投稿事件</router-link>
          <span class="acis-notice"><span class="acis-notice-dot" aria-hidden="true"></span> 使用、投稿与纠错全程免登录</span>
          <span class="acis-total">资料库已收录 <strong>{{ total }}</strong> 条事件</span>
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
        <router-link class="acis-back" to="/archive">进入完整论坛 <Icon name="chevron" :size="12" /></router-link>
      </div>

      <div class="acis-list-head">
        <div class="acis-list-head-main">
          <span class="acis-list-title">{{ q.trim() ? '搜索结果' : '全部事件' }}</span>
          <span class="acis-list-sub">
            {{ sort === 'pinyin' ? '按标题拼音 A–Z 排列' : sort === 'hot' ? '按热度排列' : '按收录时间排列' }}
            · 共 {{ total }} 条
          </span>
        </div>
        <span class="acis-list-hint">无需搜索，向下滑动即可浏览</span>
      </div>

      <div v-if="loading" class="loading acis-loading">检索中…</div>
      <div v-else-if="!items.length" class="acis-empty">
        <div class="acis-empty-orb" aria-hidden="true">
          <Icon name="book" :size="24" />
        </div>
        <div class="acis-empty-title">暂无匹配事件</div>
        <div class="acis-empty-sub">可以换个关键词，或直接投稿补充</div>
        <router-link class="acis-empty-link" to="/acis/submit">投稿事件 <Icon name="chevron" :size="12" /></router-link>
      </div>
      <div v-else class="acis-list">
        <router-link v-for="item in items" :key="item.id" class="acis-card" :to="`/acis/${item.id}`">
          <div class="acis-card-top">
            <div class="acis-card-head">
              <span v-if="item.featured" class="tag tag-orange">精选</span>
              <span class="tag tag-blue">{{ item.category }}</span>
              <span class="acis-date">{{ fmtMonth(item.occurred_at) }}</span>
            </div>
            <span class="acis-card-arrow" aria-hidden="true"><Icon name="chevron" :size="14" /></span>
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
  position: relative;
  min-height: calc(100vh - 56px);
  overflow: hidden;
  background:
    radial-gradient(1100px 720px at 12% -8%, rgba(64, 156, 255, 0.20), transparent 62%),
    radial-gradient(900px 640px at 100% 2%, rgba(160, 225, 255, 0.24), transparent 58%),
    radial-gradient(780px 520px at 48% 104%, rgba(80, 200, 255, 0.09), transparent 62%),
    var(--bg);
}
.acis-page::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image: radial-gradient(rgba(255, 255, 255, 0.42) 0.6px, transparent 0.8px);
  background-size: 7px 7px;
  opacity: 0.28;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.8), transparent 72%);
}
[data-theme="dark"] .acis-page::before { opacity: 0.12; }
.acis-inner {
  position: relative;
  z-index: 1;
  max-width: 1280px;
  padding-left: clamp(24px, 3.5vw, 58px);
  padding-right: clamp(24px, 3.5vw, 58px);
  padding-top: 34px;
}

/* ---------- 顶部玻璃主视觉 ---------- */
.acis-hero {
  position: relative;
  overflow: hidden;
  isolation: isolate;
  padding: clamp(28px, 3.4vw, 46px);
  border-radius: 30px;
  border: 1px solid var(--glass-border);
  background:
    linear-gradient(145deg, var(--glass-strong), var(--glass) 52%, var(--glass-strong));
  backdrop-filter: blur(30px) saturate(180%);
  -webkit-backdrop-filter: blur(30px) saturate(180%);
  box-shadow:
    0 30px 80px rgba(23, 78, 140, 0.15),
    0 3px 12px rgba(21, 67, 120, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.92),
    inset 0 -1px 0 rgba(255, 255, 255, 0.24);
}
[data-theme="dark"] .acis-hero {
  box-shadow:
    0 34px 90px rgba(0, 0, 0, 0.48),
    0 2px 8px rgba(0, 0, 0, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.16),
    inset 0 -1px 0 rgba(255, 255, 255, 0.04);
}
.acis-hero::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background:
    radial-gradient(560px 260px at 18% -18%, rgba(255, 255, 255, 0.72), transparent 70%),
    radial-gradient(480px 240px at 92% 8%, rgba(92, 184, 255, 0.16), transparent 74%);
  opacity: 0.9;
}
[data-theme="dark"] .acis-hero::before {
  background:
    radial-gradient(540px 240px at 16% -20%, rgba(120, 190, 255, 0.16), transparent 70%),
    radial-gradient(460px 220px at 94% 4%, rgba(20, 100, 190, 0.28), transparent 72%);
}
.acis-hero-glow {
  position: absolute;
  right: -5%;
  bottom: -46%;
  width: 62%;
  height: 100%;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(92, 184, 255, 0.22), transparent 68%);
  filter: blur(18px);
  pointer-events: none;
  z-index: -1;
}
.acis-watermark {
  position: absolute;
  z-index: -1;
  top: -22%;
  right: -4%;
  width: min(46%, 540px);
  opacity: 0.065;
  transform: rotate(-6deg);
  pointer-events: none;
  user-select: none;
  filter: saturate(0.65);
}
[data-theme="dark"] .acis-watermark { opacity: 0.11; filter: saturate(0.5) brightness(1.6); }

/* ---------- 字标组合 ---------- */
.acis-brand {
  position: relative;
}
.acis-hero-glyph {
  display: block;
  width: min(560px, 74%);
  height: auto;
  margin: 2px 0 0;
  filter: drop-shadow(0 14px 30px rgba(10, 110, 210, 0.22));
  animation: acis-glyph-in 0.9s cubic-bezier(0.2, 0.9, 0.3, 1.15) both, acis-glyph-float 5.4s ease-in-out infinite;
}
[data-theme="dark"] .acis-hero-glyph {
  filter: drop-shadow(0 16px 36px rgba(15, 120, 230, 0.35)) brightness(1.12);
}
.acis-brand-copy { min-width: 0; }
.acis-kicker {
  margin-bottom: 4px;
  color: var(--text-2);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  opacity: 0.78;
}
.acis-brand-copy :deep(.acis-wordmark) {
  font-size: clamp(58px, 7.4vw, 104px);
  letter-spacing: 0.03em;
}
.acis-tagline {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 10px;
  color: var(--text-2);
}
.acis-tagline-en {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  opacity: 0.82;
}
.acis-tagline-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: rgba(64, 156, 255, 0.6);
}
.acis-tagline-cn {
  font-size: 12px;
  letter-spacing: 0.08em;
  opacity: 0.8;
}

/* ---------- 搜索区 ---------- */
.acis-search {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: clamp(24px, 3vw, 34px);
  padding: 8px 8px 8px 18px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.8);
  background: rgba(255, 255, 255, 0.56);
  backdrop-filter: blur(18px) saturate(180%);
  -webkit-backdrop-filter: blur(18px) saturate(180%);
  box-shadow:
    0 12px 34px rgba(30, 100, 170, 0.12),
    0 2px 6px rgba(30, 80, 140, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
  transition: border-color 0.22s ease, box-shadow 0.22s ease, background 0.22s ease;
}
.acis-search:focus-within {
  border-color: rgba(65, 160, 255, 0.62);
  background: rgba(255, 255, 255, 0.72);
  box-shadow:
    0 16px 40px rgba(30, 110, 190, 0.16),
    0 0 0 4px rgba(10, 132, 255, 0.09),
    inset 0 1px 0 rgba(255, 255, 255, 1);
}
[data-theme="dark"] .acis-search {
  border-color: rgba(155, 200, 255, 0.18);
  background: rgba(17, 31, 50, 0.62);
  box-shadow:
    0 16px 40px rgba(0, 0, 0, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
[data-theme="dark"] .acis-search:focus-within {
  border-color: rgba(90, 175, 255, 0.5);
  background: rgba(20, 36, 58, 0.8);
  box-shadow:
    0 18px 44px rgba(0, 0, 0, 0.4),
    0 0 0 4px rgba(10, 132, 255, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.16);
}
.acis-search-icon {
  display: flex;
  align-items: center;
  color: var(--text-2);
  opacity: 0.72;
}
.acis-search-input {
  flex: 1;
  min-width: 0;
  padding: 8px 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 14.5px;
  letter-spacing: 0.01em;
}
.acis-search-input::placeholder { color: var(--text-2); opacity: 0.72; }
.acis-search-btn {
  flex: none;
  height: 44px;
  padding: 0 24px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.34);
  background: linear-gradient(180deg, #62bcff 0%, #0a84ff 44%, #0065d2 100%);
  color: #fff;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  cursor: pointer;
  box-shadow:
    0 9px 20px rgba(0, 113, 227, 0.32),
    inset 0 1px 0 rgba(255, 255, 255, 0.48),
    inset 0 -2px 6px rgba(0, 70, 160, 0.28);
  transition: transform 0.18s ease, filter 0.18s ease, box-shadow 0.18s ease;
}
.acis-search-btn:hover { filter: brightness(1.06); transform: translateY(-1px); }
.acis-search-btn:active { transform: scale(0.96); box-shadow: 0 4px 12px rgba(0, 113, 227, 0.3); }

.acis-hero-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 16px;
}
.acis-submit-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 15px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.62);
  background: rgba(255, 255, 255, 0.34);
  color: var(--text);
  font-size: 12.5px;
  font-weight: 600;
  text-decoration: none;
  backdrop-filter: blur(12px);
  box-shadow: 0 6px 16px rgba(30, 90, 150, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.72);
  transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease;
}
.acis-submit-btn:hover {
  transform: translateY(-1px);
  background: rgba(255, 255, 255, 0.58);
  border-color: rgba(93, 180, 255, 0.55);
}
[data-theme="dark"] .acis-submit-btn {
  border-color: rgba(160, 205, 255, 0.18);
  background: rgba(35, 58, 88, 0.46);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
.acis-notice {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-2);
  font-size: 11.5px;
  letter-spacing: 0.02em;
}
.acis-notice-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #34c759;
  box-shadow: 0 0 0 3px rgba(52, 199, 89, 0.12);
}
.acis-total {
  margin-left: auto;
  padding: 6px 11px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.24);
  color: var(--text-2);
  font-size: 11.5px;
  backdrop-filter: blur(10px);
}
.acis-total strong { color: var(--text); font-size: 12.5px; }
[data-theme="dark"] .acis-total {
  border-color: rgba(160, 205, 255, 0.14);
  background: rgba(35, 58, 88, 0.34);
}

/* ---------- 切换与列表 ---------- */
.acis-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 18px 2px 13px;
}
.acis-tab {
  padding: 8px 16px;
  border-radius: 999px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}
.acis-tab:hover { background: rgba(255, 255, 255, 0.32); color: var(--text); }
.acis-tab.on {
  color: #0068d7;
  border-color: rgba(255, 255, 255, 0.86);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(226, 243, 255, 0.64));
  box-shadow:
    0 6px 18px rgba(30, 100, 180, 0.13),
    inset 0 1px 0 #fff;
}
[data-theme="dark"] .acis-tab:hover { background: rgba(70, 110, 160, 0.18); }
[data-theme="dark"] .acis-tab.on {
  color: #dcefff;
  border-color: rgba(160, 205, 255, 0.2);
  background: linear-gradient(180deg, rgba(55, 105, 170, 0.7), rgba(25, 55, 95, 0.55));
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.16);
}
.acis-back {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  color: var(--text-2);
  font-size: 11.5px;
  text-decoration: none;
  opacity: 0.76;
  transition: color 0.18s ease, opacity 0.18s ease;
}
.acis-back:hover { color: var(--blue); opacity: 1; }
.acis-loading { padding: 38px 0; }
.acis-list-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin: 0 2px 10px;
}
.acis-list-head-main { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.acis-list-title { color: var(--text); font-size: 14px; font-weight: 700; letter-spacing: 0.01em; }
.acis-list-sub { color: var(--text-2); font-size: 11.5px; opacity: 0.78; }
.acis-list-hint { color: var(--text-2); font-size: 11px; opacity: 0.62; letter-spacing: 0.02em; }

.acis-list { display: flex; flex-direction: column; gap: 12px; }
.acis-card {
  position: relative;
  overflow: hidden;
  display: block;
  padding: 20px 24px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.66);
  background: linear-gradient(150deg, rgba(255, 255, 255, 0.55), rgba(255, 255, 255, 0.30));
  color: inherit;
  text-decoration: none;
  backdrop-filter: blur(22px) saturate(170%);
  -webkit-backdrop-filter: blur(22px) saturate(170%);
  box-shadow:
    0 16px 42px rgba(30, 90, 150, 0.10),
    inset 0 1px 0 rgba(255, 255, 255, 0.85);
  transition: transform 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease, background 0.22s ease;
}
.acis-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 12%;
  right: 12%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.9), transparent);
  opacity: 0.8;
}
.acis-card:hover {
  transform: translateY(-3px);
  border-color: rgba(92, 180, 255, 0.5);
  background: linear-gradient(150deg, rgba(255, 255, 255, 0.7), rgba(255, 255, 255, 0.38));
  box-shadow:
    0 24px 54px rgba(30, 100, 170, 0.16),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
[data-theme="dark"] .acis-card {
  border-color: rgba(155, 200, 255, 0.13);
  background: linear-gradient(150deg, rgba(32, 52, 80, 0.58), rgba(15, 29, 47, 0.42));
  box-shadow:
    0 18px 44px rgba(0, 0, 0, 0.34),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
[data-theme="dark"] .acis-card:hover {
  border-color: rgba(95, 175, 255, 0.4);
  background: linear-gradient(150deg, rgba(40, 64, 96, 0.68), rgba(18, 34, 55, 0.5));
  box-shadow: 0 24px 56px rgba(0, 0, 0, 0.42), inset 0 1px 0 rgba(255, 255, 255, 0.16);
}
.acis-card-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.acis-card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.acis-date { color: var(--text-2); font-size: 11.5px; opacity: 0.8; }
.acis-card-arrow { display: inline-flex; color: var(--text-2); opacity: 0.45; transform: rotate(-90deg); transition: transform 0.2s ease, opacity 0.2s ease; }
.acis-card:hover .acis-card-arrow { opacity: 0.9; transform: rotate(-90deg) translateY(-2px); }
.acis-title { margin-top: 10px; font-size: 17px; font-weight: 600; line-height: 1.45; letter-spacing: -0.01em; }
.acis-summary {
  margin-top: 7px;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.68;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.acis-meta { display: flex; gap: 15px; margin-top: 12px; color: var(--text-2); font-size: 11.5px; opacity: 0.78; }
.acis-meta span { display: inline-flex; align-items: center; gap: 4px; }

/* ---------- 空状态 ---------- */
.acis-empty {
  position: relative;
  overflow: hidden;
  padding: 56px 24px 50px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  background: linear-gradient(150deg, rgba(255, 255, 255, 0.56), rgba(255, 255, 255, 0.28));
  text-align: center;
  backdrop-filter: blur(24px) saturate(170%);
  -webkit-backdrop-filter: blur(24px) saturate(170%);
  box-shadow:
    0 20px 52px rgba(30, 90, 150, 0.11),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}
.acis-empty::before {
  content: '';
  position: absolute;
  top: -40%;
  left: 50%;
  width: 340px;
  height: 240px;
  transform: translateX(-50%);
  background: radial-gradient(circle, rgba(90, 180, 255, 0.16), transparent 68%);
  filter: blur(14px);
  pointer-events: none;
}
[data-theme="dark"] .acis-empty {
  border-color: rgba(155, 200, 255, 0.14);
  background: linear-gradient(150deg, rgba(32, 52, 80, 0.55), rgba(15, 29, 47, 0.4));
  box-shadow:
    0 22px 54px rgba(0, 0, 0, 0.36),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
.acis-empty-orb {
  position: relative;
  width: 66px;
  height: 66px;
  margin: 0 auto 16px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.82);
  background:
    radial-gradient(circle at 30% 20%, rgba(255, 255, 255, 0.94), transparent 56%),
    radial-gradient(circle, rgba(166, 218, 255, 0.36), rgba(255, 255, 255, 0.12));
  color: #2a8fe8;
  box-shadow:
    0 12px 30px rgba(30, 110, 190, 0.18),
    0 0 0 8px rgba(90, 180, 255, 0.06),
    inset 0 1px 0 #fff;
  backdrop-filter: blur(12px);
  animation: acis-orb-breathe 3.4s ease-in-out infinite;
}
.acis-empty-orb::before {
  content: '';
  position: absolute;
  inset: -16px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(80, 178, 255, 0.2), transparent 66%);
  filter: blur(9px);
  z-index: -1;
}
[data-theme="dark"] .acis-empty-orb {
  border-color: rgba(165, 210, 255, 0.22);
  background:
    radial-gradient(circle at 30% 20%, rgba(190, 228, 255, 0.2), transparent 56%),
    radial-gradient(circle, rgba(30, 100, 180, 0.38), rgba(20, 38, 60, 0.2));
  color: #8fd1ff;
  box-shadow:
    0 12px 32px rgba(0, 0, 0, 0.35),
    0 0 0 8px rgba(80, 160, 255, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.16);
}
.acis-empty-title {
  position: relative;
  color: var(--text);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.01em;
}
.acis-empty-sub {
  position: relative;
  margin-top: 6px;
  color: var(--text-2);
  font-size: 11.5px;
  letter-spacing: 0.02em;
  opacity: 0.78;
}
.acis-empty-link {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-top: 16px;
  color: var(--blue);
  font-size: 11.5px;
  font-weight: 600;
  text-decoration: none;
  opacity: 0.86;
}
.acis-empty-link:hover { opacity: 1; }

.acis-footer-note {
  margin-top: 24px;
  padding-top: 15px;
  border-top: 1px dashed var(--border);
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.7;
  opacity: 0.72;
  letter-spacing: 0.015em;
}

@keyframes acis-glyph-in {
  from { opacity: 0; transform: translateY(18px) scale(0.97); filter: blur(6px); }
  to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
}
@keyframes acis-glyph-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-5px); }
}
@keyframes acis-orb-breathe {
  0%, 100% { transform: translateY(0) scale(1); box-shadow: 0 12px 30px rgba(30, 110, 190, 0.16), 0 0 0 8px rgba(90, 180, 255, 0.05), inset 0 1px 0 #fff; }
  50% { transform: translateY(-2px) scale(1.025); box-shadow: 0 18px 38px rgba(30, 120, 210, 0.24), 0 0 0 12px rgba(90, 180, 255, 0.08), inset 0 1px 0 #fff; }
}
@media (prefers-reduced-motion: reduce) {
  .acis-empty-orb, .acis-hero-glyph { animation: none; }
}
@media (max-width: 720px) {
  .acis-inner { padding-left: 18px; padding-right: 18px; padding-top: 20px; }
  .acis-hero { padding: 24px 20px; border-radius: 24px; }
  .acis-hero-glyph { width: 94%; }
  .acis-tagline { gap: 7px; }
  .acis-tagline-en { font-size: 9.5px; letter-spacing: 0.12em; }
  .acis-tagline-cn { font-size: 11px; }
  .acis-watermark { display: none; }
  .acis-total { width: 100%; margin-left: 0; margin-top: 2px; }
  .acis-search { border-radius: 20px; flex-wrap: wrap; padding: 10px 12px; }
  .acis-search-input { min-width: 60%; }
  .acis-search-btn { width: 100%; margin-top: 2px; }
  .acis-card { padding: 18px 18px; border-radius: 21px; }
  .acis-empty { padding: 44px 18px 38px; border-radius: 22px; }
}
</style>
