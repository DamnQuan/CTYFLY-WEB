<script setup>
/**
 * ACIS 事件检索后台：投稿审核、纠错审核、事件管理、评论管理与举报处理。
 */
import { computed, ref } from 'vue';
import { api } from '../../api.js';
import { fmtMonth, showToast } from '../../utils.js';
import Icon from '../../components/Icon.vue';
import SelectMenu from '../../components/SelectMenu.vue';

const tab = ref('submissions');
const submissions = ref([]);
const corrections = ref([]);
const events = ref([]);
const comments = ref([]);
const reports = ref([]);
const loading = ref(false);
const statusFilter = ref('pending');

const statusOptions = computed(() => {
  if (tab.value === 'events') {
    return [
      { value: 'all', label: '全部' },
      { value: 'published', label: '已发布' },
      { value: 'offline', label: '已下线' },
    ];
  }
  if (tab.value === 'comments') {
    return [
      { value: 'published', label: '正常' },
      { value: 'hidden', label: '已隐藏' },
      { value: 'deleted', label: '已删除' },
      { value: 'all', label: '全部' },
    ];
  }
  if (tab.value === 'reports') {
    return [
      { value: 'pending', label: '待处理' },
      { value: 'resolved', label: '已处理' },
      { value: 'all', label: '全部' },
    ];
  }
  return [
    { value: 'pending', label: '待处理' },
    { value: 'approved', label: '已通过' },
    { value: 'rejected', label: '已驳回' },
    { value: 'all', label: '全部' },
  ];
});

async function load() {
  loading.value = true;
  try {
    if (tab.value === 'submissions') {
      const data = await api.get(`/api/admin/archive/submissions?status=${statusFilter.value}`);
      submissions.value = data.items || [];
    } else if (tab.value === 'corrections') {
      const data = await api.get(`/api/admin/archive/corrections?status=${statusFilter.value}`);
      corrections.value = data.items || [];
    } else if (tab.value === 'events') {
      const data = await api.get(`/api/admin/archive/events?status=${statusFilter.value}`);
      events.value = data.items || [];
    } else if (tab.value === 'comments') {
      const data = await api.get(`/api/admin/archive/comments?status=${statusFilter.value}`);
      comments.value = data.items || [];
    } else {
      const data = await api.get(`/api/admin/archive/reports?status=${statusFilter.value}`);
      reports.value = data.items || [];
    }
  } catch (err) {
    showToast(err.message);
  } finally {
    loading.value = false;
  }
}

function switchTab(next) {
  tab.value = next;
  if (next === 'events' || next === 'comments' || next === 'reports') {
    statusFilter.value = next === 'comments' ? 'published' : next === 'reports' ? 'pending' : 'all';
  } else {
    statusFilter.value = 'pending';
  }
  load();
}

function review(type, id) {
  return `/admin/archive/review/${type}/${id}`;
}

async function toggleFeatured(row) {
  try {
    const data = await api.post(`/api/admin/archive/events/${row.id}/featured`, { featured: !row.featured });
    row.featured = data.featured;
    showToast(data.featured ? '已设为精选' : '已取消精选');
  } catch (err) {
    showToast(err.message);
  }
}

async function setCommentStatus(row, status) {
  try {
    await api.post(`/api/admin/archive/comments/${row.id}/status`, { status });
    showToast('评论状态已更新');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

async function resolveReport(row, action) {
  try {
    await api.post(`/api/admin/archive/reports/${row.id}/resolve`, { action });
    showToast(action === 'hide' ? '评论已隐藏，举报已处理' : '举报已驳回');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

load();
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <div class="page-title">ACIS 管理</div>
        <div class="page-desc">审核投稿与纠错、管理事件、评论和举报</div>
      </div>
      <router-link class="btn btn-primary btn-sm" :to="review('event', 0)">
        <Icon name="plus" :size="14" /> 新建事件
      </router-link>
    </div>

    <div class="tabs-row">
      <button class="btn btn-ghost btn-sm" :class="{ 'btn-primary': tab === 'submissions' }" @click="switchTab('submissions')">投稿审核</button>
      <button class="btn btn-ghost btn-sm" :class="{ 'btn-primary': tab === 'corrections' }" @click="switchTab('corrections')">纠错审核</button>
      <button class="btn btn-ghost btn-sm" :class="{ 'btn-primary': tab === 'events' }" @click="switchTab('events')">事件管理</button>
      <button class="btn btn-ghost btn-sm" :class="{ 'btn-primary': tab === 'comments' }" @click="switchTab('comments')">评论管理</button>
      <button class="btn btn-ghost btn-sm" :class="{ 'btn-primary': tab === 'reports' }" @click="switchTab('reports')">举报处理</button>
      <SelectMenu v-model="statusFilter" :options="statusOptions" style="width: 130px; margin-left: auto" @update:model-value="load" />
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
              <div class="review-title">
                <span v-if="row.featured" class="tag tag-orange" style="margin-right: 6px">精选</span>
                {{ row.title }}
              </div>
              <div class="review-sub">{{ fmtMonth(row.occurred_at) }} · {{ row.category }} · {{ row.status }} · {{ row.like_count }} 赞 · {{ row.comment_count }} 评论</div>
            </div>
            <button class="btn btn-ghost btn-sm" type="button" @click="toggleFeatured(row)">
              {{ row.featured ? '取消精选' : '设为精选' }}
            </button>
            <router-link v-if="row.status === 'published'" class="btn btn-ghost btn-sm" :to="`/acis/${row.id}`" target="_blank">查看</router-link>
            <router-link class="btn btn-primary btn-sm" :to="review('event', row.id)">编辑</router-link>
          </div>
        </div>
        <div v-else class="glass card"><div class="empty">还没有事件</div></div>
      </div>

      <div v-if="tab === 'comments'">
        <div v-if="comments.length" class="glass card">
          <div v-for="row in comments" :key="row.id" class="review-item comment-item">
            <div class="review-main">
              <div class="review-title">{{ row.event_title }}</div>
              <div class="review-sub">{{ row.username }} · {{ row.created_at }} · {{ row.status }}<template v-if="row.report_count"> · {{ row.report_count }} 个待处理举报</template></div>
              <div class="review-proposed">{{ row.content }}</div>
            </div>
            <button v-if="row.status !== 'published'" class="btn btn-ghost btn-sm" type="button" @click="setCommentStatus(row, 'published')">恢复</button>
            <button v-if="row.status === 'published'" class="btn btn-ghost btn-sm" type="button" @click="setCommentStatus(row, 'hidden')">隐藏</button>
            <button v-if="row.status !== 'deleted'" class="btn btn-danger btn-sm" type="button" @click="setCommentStatus(row, 'deleted')">删除</button>
          </div>
        </div>
        <div v-else class="glass card"><div class="empty">暂无评论</div></div>
      </div>

      <div v-if="tab === 'reports'">
        <div v-if="reports.length" class="glass card">
          <div v-for="row in reports" :key="row.id" class="review-item comment-item">
            <div class="review-main">
              <div class="review-title">{{ row.event_title }}</div>
              <div class="review-sub">举报人 {{ row.reporter_name }} · 评论作者 {{ row.author_name }} · {{ row.created_at }} · {{ row.status }}</div>
              <div class="review-proposed">举报原因：{{ row.reason }}</div>
              <div class="report-content">评论内容：{{ row.content }}</div>
            </div>
            <button v-if="row.status === 'pending'" class="btn btn-danger btn-sm" type="button" @click="resolveReport(row, 'hide')">隐藏评论</button>
            <button v-if="row.status === 'pending'" class="btn btn-ghost btn-sm" type="button" @click="resolveReport(row, 'dismiss')">举报不成立</button>
          </div>
        </div>
        <div v-else class="glass card"><div class="empty">暂无举报</div></div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.tabs-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
.review-item { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px dashed var(--border); }
.review-item:last-child { border-bottom: none; }
.comment-item { align-items: flex-start; }
.review-main { flex: 1; min-width: 0; }
.review-title { font-size: 14.5px; font-weight: 600; }
.review-sub { margin-top: 4px; color: var(--gray); font-size: 12px; }
.review-proposed { margin-top: 6px; color: var(--text-2); font-size: 12.5px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.report-content { margin-top: 5px; color: var(--gray); font-size: 12px; line-height: 1.6; }
</style>
