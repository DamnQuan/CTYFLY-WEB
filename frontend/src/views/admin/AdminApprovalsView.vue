<script setup>
import { onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { fmtTime, showToast } from '../../utils.js';
import { promptModal } from '../../modal.js';
import SegmentedTabs from '../../components/SegmentedTabs.vue';
import Icon from '../../components/Icon.vue';

const approvals = ref([]);
const loading = ref(false);
const status = ref('pending');
const statusOptions = [
  { value: 'pending', label: '待审批' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已驳回' },
];

const TYPE_CLS = {
  role_change: 'tag-blue',
  ban: 'tag-red',
  delete_account: 'tag-red',
};

async function load() {
  loading.value = true;
  try {
    const data = await api.get(`/api/admin/approvals?status=${status.value}`);
    approvals.value = data.approvals;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

function approveCount(a) {
  return a.votes.filter((v) => v.vote === 'approve').length;
}
function rejectCount(a) {
  return a.votes.filter((v) => v.vote === 'reject').length;
}

/** payload 可能不是合法 JSON，历史数据/手工写入：解析失败时回落展示原始文本*/
function parsePayload(a) {
  if (!a.payload) return null;
  try {
    return JSON.parse(a.payload);
  } catch {
    return null;
  }
}
function payloadRole(a) {
  const p = parsePayload(a);
  return p && p.role ? String(p.role).toUpperCase() : '';
}
function payloadRaw(a) {
  return parsePayload(a) === null ? a.payload : '';
}

async function vote(a, vote) {
  let comment = '';
  if (vote === 'reject') {
    comment = await promptModal({
      title: '驳回申请',
      message: `确定要驳回对 ${a.target_username} 的「${a.type_label}」申请吗？请填写驳回理由：`,
      placeholder: '驳回理由（必填）',
      confirmText: '确认驳回',
      danger: true,
    });
    if (comment === null) return;
    if (!comment.trim()) return showToast('请填写驳回理由');
  }
  try {
    const data = await api.post(`/api/admin/approvals/${a.id}/vote`, { vote, comment });
    showToast(data.message || '已提交');
    load();
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">审批中心</div>
      <div class="page-desc">角色变更 / 封禁 / 删除账户需 2 名管理员或主管复核通过；发起人不能审批自己发起的申请</div>
    </div>

    <SegmentedTabs class="lg" :options="statusOptions" :model-value="status"
      @update:model-value="(v) => { status = v; load(); }" />

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!approvals.length" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="shield" :size="22" /></div>
        <div>暂无{{ statusOptions.find((s) => s.value === status)?.label }}的申请</div>
      </div>
    </div>

    <div v-else class="glass card">
      <div v-for="a in approvals" :key="a.id" class="approval-item">
        <div style="display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap">
          <div>
            <div class="list-title">
              <span class="tag" :class="TYPE_CLS[a.type] || 'tag'" style="margin-right: 8px">{{ a.type_label }}</span>
              {{ a.target_username }}，CID {{ a.target_cid }}
              <span v-if="payloadRole(a)" class="tag tag-blue" style="margin-left: 6px">
                → {{ payloadRole(a) }}
              </span>
            </div>
            <div class="list-sub">发起人：{{ a.initiator_name }} · {{ fmtTime(a.created_at) }}</div>
            <div class="list-sub">理由：{{ a.reason || '—' }}</div>
            <div v-if="payloadRaw(a)" class="list-sub">原始载荷：{{ payloadRaw(a) }}</div>
          </div>
          <div style="text-align: right">
            <div class="list-sub">复核进度 {{ approveCount(a) }}/{{ a.required }}</div>
            <div class="list-sub">驳回 {{ rejectCount(a) }}</div>
          </div>
        </div>

        <div v-if="a.votes.length" class="votes">
          <div v-for="v in a.votes" :key="v.id" class="list-sub">
            {{ v.vote === 'approve' ? '通过' : '驳回' }} · {{ v.voter_name }} · {{ fmtTime(v.created_at) }}
            <template v-if="v.comment"> · {{ v.comment }}</template>
          </div>
        </div>

        <div v-if="a.status === 'pending'" style="margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap">
          <button v-if="a.can_vote" class="btn btn-primary btn-sm" @click="vote(a, 'approve')">复核通过</button>
          <button v-if="a.can_vote" class="btn btn-danger btn-sm" @click="vote(a, 'reject')">驳回</button>
          <span v-if="!a.can_vote" class="tag tag-orange">
            {{ a.my_voted ? '你已审批' : '发起人/当事人不能审批' }}
          </span>
        </div>
        <div v-else class="list-sub" style="margin-top: 10px">
          结果：{{ a.status === 'approved' ? '已通过并执行' : '已驳回' }} · {{ fmtTime(a.decided_at) }} · {{ a.decision_note }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.approval-item {
  padding: 14px 2px;
  border-bottom: 1px solid var(--border);
}
.approval-item:last-child { border-bottom: none; }
.votes {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface);
}
</style>
