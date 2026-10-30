<script setup>
import { onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { fmtTime, showToast } from '../../utils.js';
import { promptModal } from '../../modal.js';
import SegmentedTabs from '../../components/SegmentedTabs.vue';

const airlines = ref([]);
const loading = ref(false);
const status = ref('pending');
const statusOptions = [
  { value: 'pending', label: '待审核' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已驳回' },
];

async function load() {
  loading.value = true;
  try {
    const data = await api.get(`/api/airlines/admin/list?status=${status.value}`);
    airlines.value = data.airlines;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

async function review(a, action) {
  let note = '';
  if (action === 'approve') {
    note = await promptModal({
      title: '通过建司申请',
      message: `确认通过 ${a.owner_name}，CID ${a.owner_cid}创建 ${a.icao} ${a.name} 的申请？该用户将成为 CEO。`,
      placeholder: '审核备注，可留空',
      confirmText: '通过',
    });
    if (note === null) return;
  } else {
    note = await promptModal({
      title: '驳回建司申请',
      message: `请填写驳回 ${a.icao} ${a.name} 的原因：`,
      placeholder: '驳回原因，必填',
      confirmText: '驳回',
      danger: true,
    });
    if (note === null) return;
    if (!note.trim()) return showToast('请填写驳回原因');
  }
  try {
    await api.post(`/api/airlines/admin/${a.id}/review`, { action, note });
    showToast(action === 'approve' ? '已通过，创建者已成为 CEO' : '已驳回');
    load();
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">航司审核</div>
      <div class="page-desc">虚拟航司建司申请审核；通过后创建者自动成为 CEO，可自行审批成员与管理航线</div>
    </div>

    <SegmentedTabs class="lg" :options="statusOptions" :model-value="status"
      @update:model-value="(v) => { status = v; load(); }" />

    <div class="glass card">
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else-if="airlines.length">
        <div v-for="a in airlines" :key="a.id" class="list-item">
          <div class="va-badge">{{ a.icao }}</div>
          <div class="list-main">
            <div class="list-title">
              {{ a.name }}
              <span class="tag" style="margin-left: 6px">CEO：{{ a.owner_name }}，CID {{ a.owner_cid }}</span>
            </div>
            <div class="list-sub">{{ a.description || '暂无简介' }}</div>
            <div class="list-sub">申请于 {{ fmtTime(a.created_at) }}</div>
            <div class="list-sub" v-if="a.review_note && a.status !== 'pending'">审核意见：{{ a.review_note }}</div>
          </div>
          <div style="display: flex; flex-direction: column; gap: 6px; align-items: flex-end">
            <span :class="a.status === 'pending' ? 'tag tag-orange' : a.status === 'approved' ? 'tag tag-green' : 'tag tag-red'">
              {{ a.status === 'pending' ? '待审核' : a.status === 'approved' ? '已通过' : '已驳回' }}
            </span>
            <template v-if="a.status === 'pending'">
              <button class="btn btn-primary btn-sm" @click="review(a, 'approve')">通过</button>
              <button class="btn btn-danger btn-sm" @click="review(a, 'reject')">驳回</button>
            </template>
          </div>
        </div>
      </template>
      <div v-else class="empty">暂无申请</div>
    </div>
  </div>
</template>

<style scoped>
.va-badge {
  width: 46px;
  height: 46px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: linear-gradient(135deg, #0a84ff, #0071e3);
  color: #fff;
  font-weight: 700;
  font-size: 12px;
}
</style>
