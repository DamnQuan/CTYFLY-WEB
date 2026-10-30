<script setup>
/**
 * 管理后台：平台发展问卷反馈
 *
 * 只读页面：概览统计、逐份查看答案、导出 CSV。
 * 后端按 view_surveys 能力控制访问，列表与导出走同一能力。
 */
import { onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { fmtTime, showToast } from '../../utils.js';
import Icon from '../../components/Icon.vue';

const items = ref([]);
const summary = ref({ total: 0, today: 0, averageSatisfaction: 0, priorities: [] });
const total = ref(0);
const offset = ref(0);
const pageSize = ref(20);
const loading = ref(true);
const exporting = ref(false);

async function load() {
  loading.value = true;
  try {
    // 每页条数由服务端固定，前端只传 offset，避免用户可控的 LIMIT
    const data = await api.get(`/api/admin/surveys?offset=${offset.value}`);
    items.value = data.items || [];
    summary.value = data.summary || summary.value;
    total.value = data.total || 0;
    pageSize.value = data.limit || 20;
  } catch (err) {
    showToast(err.message);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function prev() {
  if (offset.value === 0) return;
  offset.value = Math.max(0, offset.value - pageSize.value);
  load();
}
function next() {
  if (offset.value + pageSize.value >= total.value) return;
  offset.value += pageSize.value;
  load();
}

function who(item) {
  if (item.identity) return item.identity.username || `CID ${item.identity.cid}`;
  return item.nickname || '匿名访客';
}

function whoSub(item) {
  const parts = [];
  if (item.identity?.cid) parts.push(`CID ${item.identity.cid}`);
  if (item.contact) parts.push(item.contact);
  return parts.join(' · ');
}

const maxPriority = () => Math.max(1, ...summary.value.priorities.map((p) => p.count));

async function exportCsv() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    const blob = await api.blob('/api/admin/surveys/export');
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'survey-export.csv';
    a.click();
    URL.revokeObjectURL(url);
    showToast('已导出 CSV');
  } catch (err) {
    showToast(err.message);
  } finally {
    exporting.value = false;
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap">
      <div>
        <div class="page-title">问卷反馈</div>
        <div class="page-desc">来自平台发展问卷的真实建议，按提交时间倒序</div>
      </div>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="exporting" @click="exportCsv">
        {{ exporting ? '导出中…' : '导出 CSV' }}
      </button>
    </div>

    <div class="survey-stats">
      <div class="glass card survey-stat">
        <div class="survey-stat-label">总反馈</div>
        <div class="survey-stat-value">{{ summary.total }}</div>
      </div>
      <div class="glass card survey-stat">
        <div class="survey-stat-label">今日新增</div>
        <div class="survey-stat-value">{{ summary.today }}</div>
      </div>
      <div class="glass card survey-stat">
        <div class="survey-stat-label">平均满意度</div>
        <div class="survey-stat-value">
          {{ summary.averageSatisfaction ? summary.averageSatisfaction : '暂无' }}
          <span v-if="summary.averageSatisfaction" class="survey-stat-unit">/ 5</span>
        </div>
      </div>
    </div>

    <div v-if="summary.priorities?.length" class="glass card survey-priorities">
      <div class="card-title">发展优先级</div>
      <div v-for="p in summary.priorities" :key="p.value" class="survey-bar-row">
        <span class="survey-bar-label">{{ p.label }}</span>
        <div class="survey-bar-track">
          <div class="survey-bar" :style="{ width: `${Math.round((p.count / maxPriority()) * 100)}%` }"></div>
        </div>
        <span class="survey-bar-count">{{ p.count }}</span>
      </div>
    </div>

    <div v-if="loading" class="glass card survey-empty">正在加载…</div>
    <div v-else-if="!items.length" class="glass card survey-empty">还没有收到问卷反馈</div>

    <div v-else class="survey-list">
      <div v-for="item in items" :key="item.id" class="glass card survey-item">
        <div class="survey-item-head">
          <div class="survey-item-who">
            <Icon name="user" :size="15" />
            <span>{{ who(item) }}</span>
            <span v-if="whoSub(item)" class="survey-item-sub">{{ whoSub(item) }}</span>
          </div>
          <div class="survey-item-time">#{{ item.id }} · {{ fmtTime(item.createdAt) }}</div>
        </div>
        <div class="survey-answer-list">
          <div
            v-for="a in item.answers"
            :key="a.key"
            class="survey-answer"
            :class="{ 'is-text': a.type === 'text' }"
          >
            <div class="survey-answer-title">{{ a.title }}</div>
            <div class="survey-answer-value">{{ a.display }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="total > pageSize" class="survey-pager">
      <button class="btn btn-ghost btn-sm" type="button" :disabled="offset === 0" @click="prev">上一页</button>
      <span class="survey-pager-info">{{ offset + 1 }} - {{ Math.min(offset + pageSize, total) }} / {{ total }}</span>
      <button class="btn btn-ghost btn-sm" type="button" :disabled="offset + pageSize >= total" @click="next">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.survey-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.survey-stat { padding: 18px 20px; }
.survey-stat-label { color: var(--text-2); font-size: 12.5px; }
.survey-stat-value {
  margin-top: 6px;
  color: var(--text);
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.5px;
}
.survey-stat-unit { color: var(--gray); font-size: 13px; font-weight: 500; }
.survey-priorities { padding: 20px 22px; margin-bottom: 16px; }
.survey-bar-row {
  display: grid;
  grid-template-columns: 130px 1fr 34px;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}
.survey-bar-label { color: var(--text-2); font-size: 12.5px; }
.survey-bar-track {
  height: 8px;
  border-radius: 999px;
  background: var(--surface);
  overflow: hidden;
}
.survey-bar {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--blue), color-mix(in srgb, var(--blue) 55%, transparent));
}
.survey-bar-count { color: var(--text-2); font-size: 12px; text-align: right; }
.survey-list { display: flex; flex-direction: column; gap: 12px; }
.survey-item { padding: 18px 20px; }
.survey-item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.survey-item-who {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text);
  font-size: 13.5px;
  font-weight: 600;
}
.survey-item-sub { color: var(--gray); font-size: 12px; font-weight: 400; }
.survey-item-time { color: var(--gray); font-size: 12px; }
.survey-answer-list { display: flex; flex-direction: column; gap: 10px; padding-top: 12px; }
.survey-answer { display: grid; grid-template-columns: 170px 1fr; gap: 12px; }
.survey-answer-title { color: var(--text-2); font-size: 12.5px; }
.survey-answer-value { color: var(--text); font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
.survey-answer.is-text { grid-template-columns: 1fr; gap: 4px; }
.survey-empty { padding: 34px; text-align: center; color: var(--text-2); font-size: 13.5px; }
.survey-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 18px;
}
.survey-pager-info { color: var(--gray); font-size: 12.5px; }
@media (max-width: 720px) {
  .survey-stats { grid-template-columns: 1fr; }
  .survey-bar-row { grid-template-columns: 100px 1fr 28px; }
  .survey-answer { grid-template-columns: 1fr; gap: 3px; }
}
</style>
