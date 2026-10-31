<script setup>
/**
 * 飞圈事件详情：公开可读，登录用户可提交纠错；纠错由管理员审核后生效。
 */
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { fmtMonth, safeHttpUrl, showToast } from '../utils.js';
import { useAuthStore } from '../stores/auth.js';
import Icon from '../components/Icon.vue';
import SelectMenu from '../components/SelectMenu.vue';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const item = ref(null);
const loading = ref(true);
const notFound = ref(false);
const showCorrection = ref(false);
const submitting = ref(false);
const correction = ref({ field: 'title', proposed_value: '', reason: '', source_url: '' });
const correctionOptions = [
  { value: 'title', label: '标题' },
  { value: 'summary', label: '摘要' },
  { value: 'occurred_at', label: '发生月份' },
  { value: 'category', label: '分类' },
  { value: 'other', label: '其他内容' },
];

async function load() {
  loading.value = true;
  notFound.value = false;
  try {
    item.value = await api.get(`/api/archive/${route.params.id}`);
  } catch (err) {
    if (err.status === 404) notFound.value = true;
    else showToast(err.message);
  } finally {
    loading.value = false;
  }
}

function openCorrection() {
  if (!auth.isLoggedIn) {
    router.push({ name: 'login', query: { redirect: route.fullPath } });
    return;
  }
  showCorrection.value = true;
}

function closeCorrection() {
  showCorrection.value = false;
  correction.value = { field: 'title', proposed_value: '', reason: '', source_url: '' };
}

async function submitCorrection() {
  if (!correction.value.proposed_value.trim()) {
    showToast('请填写需要更正的内容');
    return;
  }
  submitting.value = true;
  try {
    const data = await api.post(`/api/archive/${route.params.id}/corrections`, correction.value);
    showToast(data.message || '纠错已提交');
    closeCorrection();
  } catch (err) {
    showToast(err.message);
  } finally {
    submitting.value = false;
  }
}

load();
</script>

<template>
  <div class="page archive-detail-page">
    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="notFound" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="book" :size="22" /></div>
        <div>事件不存在或已下线</div>
        <router-link class="btn btn-ghost btn-sm" to="/archive" style="margin-top: 12px">返回检索</router-link>
      </div>
    </div>
    <template v-else-if="item">
      <div class="detail-top">
        <router-link class="back-link" to="/archive"><Icon name="chevron" :size="14" style="transform: rotate(90deg)" /> 返回检索</router-link>
        <button class="btn btn-ghost btn-sm" type="button" @click="openCorrection"><Icon name="file" :size="14" /> 纠错</button>
      </div>

      <div class="glass card detail-card">
        <div class="detail-meta">
          <span class="tag tag-blue">{{ item.category }}</span>
          <span>{{ fmtMonth(item.occurred_at) }}</span>
          <span v-if="item.source_count">{{ item.source_count }} 个来源</span>
        </div>
        <h1 class="detail-title">{{ item.title }}</h1>
        <div v-if="item.summary" class="detail-summary">{{ item.summary }}</div>
        <div v-if="item.tags?.length" class="detail-tags">
          <span v-for="tag in item.tags" :key="tag" class="archive-tag">#{{ tag }}</span>
        </div>

        <div class="detail-blocks">
          <template v-for="(block, index) in item.blocks" :key="index">
            <p v-if="block.type === 'text'" class="detail-text">{{ block.text }}</p>
            <figure v-else class="detail-figure">
              <img :src="block.url" :alt="block.caption || item.title" loading="lazy" />
              <figcaption v-if="block.caption">{{ block.caption }}</figcaption>
            </figure>
          </template>
        </div>

        <div class="detail-sources">
          <div class="card-title" style="font-size: 15px">资料来源</div>
          <div v-for="(source, index) in item.sources" :key="index" class="source-item">
            <a
              v-if="safeHttpUrl(source.url)"
              :href="safeHttpUrl(source.url)"
              target="_blank"
              rel="noopener noreferrer nofollow"
              class="source-link"
            >{{ source.title }} <Icon name="external" :size="12" /></a>
            <span v-else>{{ source.title }}</span>
            <span class="source-sub">{{ source.publisher }}<template v-if="source.published_at"> · {{ source.published_at }}</template></span>
          </div>
        </div>

        <div class="detail-footer">
          <span>最后更新：{{ item.updated_at }}</span>
          <span>{{ item.disclaimer }}</span>
        </div>
      </div>

      <div v-if="showCorrection" class="glass card correction-card">
        <div class="card-title" style="font-size: 15px">提交纠错</div>
        <div class="card-sub" style="margin-bottom: 12px">管理员审核后会更新事件，并保留修订记录。</div>
        <div class="grid grid-2">
          <div>
            <div class="label">需要更正的部分</div>
            <SelectMenu v-model="correction.field" :options="correctionOptions" />
          </div>
          <div>
            <div class="label">来源链接</div>
            <input v-model="correction.source_url" class="input" maxlength="800" placeholder="https:// 选填" />
          </div>
        </div>
        <div style="margin-top: 12px">
          <div class="label">建议更正为</div>
          <textarea v-model="correction.proposed_value" class="input" rows="4" maxlength="8000" placeholder="写清楚正确内容，便于管理员核对" />
        </div>
        <div style="margin-top: 12px">
          <div class="label">理由</div>
          <input v-model="correction.reason" class="input" maxlength="500" placeholder="为什么需要更正，选填" />
        </div>
        <div class="correction-actions">
          <button class="btn btn-primary" type="button" :disabled="submitting" @click="submitCorrection">提交纠错</button>
          <button class="btn btn-ghost" type="button" @click="closeCorrection">取消</button>
        </div>
      </div>

      <div class="archive-disclaimer">{{ item.correction_notice }}</div>
    </template>
  </div>
</template>

<style scoped>
.archive-detail-page { max-width: clamp(760px, 62vw, 1040px); }
.detail-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.back-link { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); font-size: 13px; text-decoration: none; }
.detail-meta { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; color: var(--gray); font-size: 12.5px; }
.detail-title { font-size: 26px; line-height: 1.35; margin: 12px 0 10px; }
.detail-summary { color: var(--text-2); font-size: 14.5px; line-height: 1.8; padding: 12px 14px; border-radius: var(--radius-sm); background: var(--surface); }
.detail-tags { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
.archive-tag { color: var(--blue); font-size: 12px; }
.detail-blocks { margin-top: 22px; }
.detail-text { white-space: pre-wrap; line-height: 1.9; font-size: 14.5px; color: var(--text); margin: 0 0 16px; }
.detail-figure { margin: 18px 0; }
.detail-figure img { width: 100%; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--surface-solid); }
.detail-figure figcaption { margin-top: 6px; text-align: center; color: var(--gray); font-size: 12px; }
.detail-sources { margin-top: 26px; padding-top: 18px; border-top: 1px solid var(--border); }
.source-item { display: flex; flex-direction: column; gap: 3px; padding: 8px 0; border-bottom: 1px dashed var(--border); }
.source-item:last-child { border-bottom: none; }
.source-link { color: var(--blue); font-size: 13.5px; text-decoration: none; display: inline-flex; align-items: center; gap: 5px; }
.source-sub { color: var(--gray); font-size: 12px; }
.detail-footer { margin-top: 22px; padding-top: 14px; border-top: 1px dashed var(--border); color: var(--gray); font-size: 12px; line-height: 1.7; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.correction-card { margin-top: 16px; }
.correction-actions { display: flex; gap: 10px; margin-top: 14px; }
.archive-disclaimer { margin-top: 18px; color: var(--gray); font-size: 12px; line-height: 1.7; }
@media (max-width: 720px) {
  .detail-title { font-size: 21px; }
}
</style>
