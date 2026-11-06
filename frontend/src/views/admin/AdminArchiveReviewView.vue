<script setup>
/**
 * 飞圈事件审核工作台：左侧展示原始投稿，右侧管理员可编辑后发布。
 * 纠错审核展示当前值与建议值，通过后写回事件。
 */
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../../api.js';
import { showToast } from '../../utils.js';
import ArchiveEditor from '../../components/archive/ArchiveEditor.vue';
import Icon from '../../components/Icon.vue';

const route = useRoute();
const router = useRouter();
const kind = route.params.type;
const id = Number(route.params.id);
const loading = ref(true);
const saving = ref(false);
const ready = ref(false);
const note = ref('');
const submission = ref(null);
const correction = ref(null);
const event = ref(null);
const editorRef = ref(null);

const title = computed(() => {
  if (kind === 'submission') return '审核投稿';
  if (kind === 'correction') return '审核纠错';
  return id ? '编辑事件' : '新建事件';
});

const initialPayload = computed(() => {
  if (kind === 'submission') {
    return submission.value?.draft && Object.keys(submission.value.draft).length
      ? submission.value.draft
      : submission.value?.payload || {};
  }
  return event.value || {};
});

const originalText = computed(() => {
  if (kind !== 'submission' || !submission.value) return '';
  return (submission.value.payload?.blocks || [])
    .filter((block) => block.type === 'text')
    .map((block) => block.text)
    .join('\n\n');
});

async function load() {
  loading.value = true;
  try {
    if (kind === 'submission') {
      submission.value = await api.get(`/api/admin/archive/submissions/${id}`);
    } else if (kind === 'correction') {
      correction.value = await api.get(`/api/admin/archive/corrections/${id}`);
    } else if (id) {
      event.value = await api.get(`/api/admin/archive/events/${id}`);
    }
    ready.value = true;
  } catch (err) {
    showToast(err.message);
  } finally {
    loading.value = false;
  }
}

function payload() {
  return editorRef.value?.getPayload();
}

async function saveDraft() {
  saving.value = true;
  try {
    await api.put(`/api/admin/archive/submissions/${id}/draft`, payload());
    showToast('审核草稿已保存');
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = false;
  }
}

async function approveSubmission() {
  saving.value = true;
  try {
    const data = await api.post(`/api/admin/archive/submissions/${id}/approve`, {
      payload: payload(),
      note: note.value,
    });
    showToast('已审核通过并发布');
    router.replace(`/acis/${data.event_id}`);
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = false;
  }
}

async function rejectSubmission() {
  if (note.value.trim().length < 2) {
    showToast('请填写驳回原因');
    return;
  }
  saving.value = true;
  try {
    await api.post(`/api/admin/archive/submissions/${id}/reject`, { note: note.value });
    showToast('已驳回');
    router.push('/admin/archive');
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = false;
  }
}

async function saveEvent() {
  saving.value = true;
  try {
    if (!id) {
      const data = await api.post('/api/admin/archive/events', payload());
      showToast('事件已创建并发布');
      router.replace(`/acis/${data.event_id}`);
      return;
    }
    await api.put(`/api/admin/archive/events/${id}`, payload());
    showToast('事件已保存');
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = false;
  }
}

async function toggleEventStatus() {
  const next = event.value?.status === 'published' ? 'offline' : 'published';
  saving.value = true;
  try {
    await api.post(`/api/admin/archive/events/${id}/status`, { status: next });
    event.value.status = next;
    showToast(next === 'published' ? '已上线' : '已下线');
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = false;
  }
}

async function approveCorrection() {
  saving.value = true;
  try {
    await api.post(`/api/admin/archive/corrections/${id}/approve`, { note: note.value });
    showToast('纠错已通过并写回事件');
    router.push('/admin/archive');
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = false;
  }
}

async function rejectCorrection() {
  if (note.value.trim().length < 2) {
    showToast('请填写驳回原因');
    return;
  }
  saving.value = true;
  try {
    await api.post(`/api/admin/archive/corrections/${id}/reject`, { note: note.value });
    showToast('已驳回');
    router.push('/admin/archive');
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = false;
  }
}

load();
</script>

<template>
  <div class="page review-page">
    <div class="page-header">
      <div>
        <router-link class="back-link" to="/admin/archive"><Icon name="chevron" :size="14" style="transform: rotate(90deg)" /> 返回管理</router-link>
        <div class="page-title">{{ title }}</div>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <template v-else-if="ready">
      <div v-if="kind === 'submission'" class="review-grid">
        <div class="glass card">
          <div class="card-title" style="font-size: 15px">原始投稿</div>
          <div class="meta-list">
            <div>投稿人：{{ submission.username }}，CID {{ submission.cid }}</div>
            <div>提交时间：{{ submission.created_at }}</div>
            <div>联系 QQ：{{ submission.payload?.contact || '未填写' }}</div>
          </div>
          <div class="original-title">{{ submission.payload?.title }}</div>
          <div class="original-summary">{{ submission.payload?.summary }}</div>
          <div class="original-text">{{ originalText }}</div>
        </div>

        <div class="glass card">
          <div class="card-title" style="font-size: 15px">编辑后发布</div>
          <ArchiveEditor ref="editorRef" :initial="initialPayload" admin-mode />
          <div style="margin-top: 14px">
            <div class="label">审核备注 / 驳回原因</div>
            <input v-model="note" class="input" maxlength="500" placeholder="驳回时必填，通过时选填" />
          </div>
          <div class="review-actions">
            <button class="btn btn-ghost" type="button" :disabled="saving" @click="saveDraft">保存草稿</button>
            <button class="btn btn-primary" type="button" :disabled="saving" @click="approveSubmission">通过并发布</button>
            <button class="btn btn-danger" type="button" :disabled="saving" @click="rejectSubmission">驳回</button>
          </div>
        </div>
      </div>

      <div v-else-if="kind === 'correction'" class="glass card">
        <div class="card-title" style="font-size: 15px">{{ correction.event_title }}</div>
        <div class="meta-list">
          <div>纠错人：{{ correction.username }}，CID {{ correction.cid }}</div>
          <div>提交时间：{{ correction.created_at }}</div>
          <div>字段：{{ correction.field }}</div>
        </div>
        <div class="correction-compare">
          <div>
            <div class="label">当前内容</div>
            <div class="compare-box">{{ correction.current_value || '暂无' }}</div>
          </div>
          <div>
            <div class="label">建议更正为</div>
            <div class="compare-box proposed">{{ correction.proposed_value }}</div>
          </div>
        </div>
        <div class="meta-list" style="margin-top: 12px">
          <div>理由：{{ correction.reason || '未填写' }}</div>
          <div>来源：{{ correction.source_url || '未填写' }}</div>
        </div>
        <div style="margin-top: 14px">
          <div class="label">审核备注 / 驳回原因</div>
          <input v-model="note" class="input" maxlength="500" placeholder="驳回时必填" />
        </div>
        <div class="review-actions">
          <button class="btn btn-primary" type="button" :disabled="saving" @click="approveCorrection">通过并更新</button>
          <button class="btn btn-danger" type="button" :disabled="saving" @click="rejectCorrection">驳回</button>
        </div>
      </div>

      <div v-else class="glass card">
        <ArchiveEditor ref="editorRef" :initial="initialPayload" admin-mode />
        <div class="review-actions">
          <button class="btn btn-primary" type="button" :disabled="saving" @click="saveEvent">{{ id ? '保存事件' : '创建并发布' }}</button>
          <button v-if="id" class="btn btn-ghost" type="button" :disabled="saving" @click="toggleEventStatus">
            {{ event?.status === 'published' ? '下线' : '上线' }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.review-page { max-width: clamp(900px, 78vw, 1480px); }
.back-link { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); font-size: 13px; text-decoration: none; margin-bottom: 8px; }
.review-grid { display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr); gap: 16px; align-items: start; }
.meta-list { color: var(--gray); font-size: 12.5px; line-height: 1.9; margin-top: 8px; }
.original-title { margin-top: 14px; font-size: 17px; font-weight: 600; }
.original-summary { margin-top: 8px; color: var(--text-2); font-size: 13.5px; line-height: 1.7; }
.original-text { margin-top: 10px; white-space: pre-wrap; color: var(--text-2); font-size: 13px; line-height: 1.8; max-height: 420px; overflow: auto; }
.review-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
.correction-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
.compare-box { margin-top: 6px; padding: 12px; border-radius: var(--radius-sm); background: var(--surface); font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
.compare-box.proposed { border: 1px solid rgba(10, 132, 255, 0.35); }
@media (max-width: 900px) {
  .review-grid { grid-template-columns: 1fr; }
  .correction-compare { grid-template-columns: 1fr; }
}
</style>
