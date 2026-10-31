<script setup>
/**
 * 飞圈事件检索后台：投稿审核、纠错审核、已发布事件管理。
 */
import { ref } from 'vue';
import { api } from '../../api.js';
import { fmtMonth, showToast } from '../../utils.js';
import Icon from '../../components/Icon.vue';

const tab = ref('submissions');
const submissions = ref([]);
const corrections = ref([]);
const events = ref([]);
const loading = ref(false);
const statusFilter = ref('pending');

async function load() {
  loading.value = true;
  try {
    if (tab.value === 'submissions') {
      const data = await api.get(`/api/admin/archive/submissions?status=${statusFilter.value}`);
      submissions.value = data.items || [];
    } else if (tab.value === 'corrections') {
      const data = await api.get(`/api/admin/archive/corrections?status=${statusFilter.value}`);
      corrections.value = data.items || [];
    } else {
      const data = await api.get(`/api/admin/archive/events?status=${statusFilter.value === 'pending' ? 'all' : statusFilter.value}`);
      events.value = data.items || [];
    }
  } catch (err) {
    showToast(err.message);
  } finally {
    loading.value = false;
  }
}

function switchTab(next) {
  tab.value = next;
  statusFilter.value = next === 'events' ? 'all' : 'pending';
  load();
}

function review(type, id) {
  return `/admin/archive/review/${type}/${id}`;
}

load();
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <div class="page-title">飞圈事件检索</div>
        <div class="page-desc">审核投稿、处理纠错、管理已发布事件</div>
      </div>
      <router-link class="btn btn-primary btn-sm" :to="review('event', 0)">
        <Icon name="plus" :size="14" /> 新建事件
      </router-link>
    </div>

    <div class="tabs-row">
      <button class="btn btn-ghost btn-sm" :class="{ 'btn-primary': tab === 'submissions' }" @click="switchTab('submissions')">投稿审核</button>
      <button class="btn btn-ghost btn-sm" :class="{ 'btn-primary': tab === 'corrections' }" @click="switchTab('corrections')">纠错审核</button>
      <button class="btn btn-ghost btn-sm" :class="{ 'btn-primary': tab === 'events' }" @click="switchTab('events')">事件管理</button>
      <select v-model="statusFilter" class="input status-select" @change="load">
        <option v-if="tab !== 'events'" value="pending">待处理</option>
        <option v-if="tab !== 'events'" value="approved">已通过</option>
        <option v-if="tab !== 'events'" value="rejected">已驳回</option>
        <option v-if="tab !== 'events'" value="all">全部</option>
        <option v-if="tab === 'events'" value="all">全部</option>
        <option v-if="tab === 'events'" value="published">已发布</option>
        <option v-if="tab === 'events'" value="offline">已下线</option>
      </select>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <template v-else>
      <div v-if="tab === 'submissions'">
        <div v-if="submissions.length" class="glass card">
          <div v-for="row in submissions" :key="row.id" class="review-item">
            <div class="review-main">
              <div class="review-title">{{ row.payload?.title || '未命名投稿' }}</div>
              <div class="review-sub">投稿人 {{ row.username }}，CID {{ row.cid }} · {{ row.created_at }}</div>
            </div>
            <span class="tag" :class="row.status === 'pending' ? 'tag-orange' : row.status === 'approved' ? 'tag-green' : 'tag-red'">{{ row.status }}</span>
            <router-link class="btn btn-primary btn-sm" :to="review('submission', row.id)">审核</router-link>
          </div>
        </div>
        <div v-else class="glass card"><div class="empty">暂无待处理投稿</div></div>
      </div>

      <div v-if="tab === 'corrections'">
        <div v-if="corrections.length" class="glass card">
          <div v-for="row in corrections" :key="row.id" class="review-item">
            <div class="review-main">
              <div class="review-title">{{ row.event_title }}</div>
              <div class="review-sub">纠错人 {{ row.username }}，CID {{ row.cid }} · {{ row.field }} · {{ row.created_at }}</div>
              <div class="review-proposed">{{ row.proposed_value }}</div>
            </div>
            <span class="tag" :class="row.status === 'pending' ? 'tag-orange' : row.status === 'approved' ? 'tag-green' : 'tag-red'">{{ row.status }}</span>
            <router-link class="btn btn-primary btn-sm" :to="review('correction', row.id)">审核</router-link>
          </div>
        </div>
        <div v-else class="glass card"><div class="empty">暂无待处理纠错</div></div>
      </div>

      <div v-if="tab === 'events'">
        <div v-if="events.length" class="glass card">
          <div v-for="row in events" :key="row.id" class="review-item">
            <div class="review-main">
              <div class="review-title">{{ row.title }}</div>
              <div class="review-sub">{{ fmtMonth(row.occurred_at) }} · {{ row.category }} · {{ row.status }}</div>
            </div>
            <router-link v-if="row.status === 'published'" class="btn btn-ghost btn-sm" :to="`/archive/${row.id}`" target="_blank">查看</router-link>
            <router-link class="btn btn-primary btn-sm" :to="review('event', row.id)">编辑</router-link>
          </div>
        </div>
        <div v-else class="glass card"><div class="empty">还没有事件</div></div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.tabs-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
.status-select { width: 130px; margin-left: auto; }
.review-item { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px dashed var(--border); }
.review-item:last-child { border-bottom: none; }
.review-main { flex: 1; min-width: 0; }
.review-title { font-size: 14.5px; font-weight: 600; }
.review-sub { margin-top: 4px; color: var(--gray); font-size: 12px; }
.review-proposed { margin-top: 6px; color: var(--text-2); font-size: 12.5px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
