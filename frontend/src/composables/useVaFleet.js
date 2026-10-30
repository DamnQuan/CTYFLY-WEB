import { computed, ref, watch } from 'vue';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import { confirmModal, promptModal } from '../modal.js';

/** 航司机队与转司：CEO 视角的转入申请、运营统计。 */
export function useVaFleet({ airlineId, isCeo, airline, data, reload }) {
  const transferLoading = ref(false);
  const transfers = ref([]);
  const stats = ref(null);

  // 我已向本航司提交的待审批跳槽申请
  const myTransfer = computed(() => data.value?.my_transfer);
  // CEO 视角：本航司收到的转入申请
  const pendingTransfers = computed(() => transfers.value.filter((t) => t.status === 'pending'));

  async function loadTransfers() {
    if (!isCeo.value) return;
    try {
      transfers.value = (await api.get(`/api/airlines/${airlineId.value}/transfers`)).transfers;
    } catch { /* 忽略 */ }
  }

  async function loadStats() {
    if (!isCeo.value) return;
    try {
      stats.value = await api.get(`/api/airlines/${airlineId.value}/stats`);
    } catch { /* 忽略 */ }
  }

  watch(isCeo, (v) => {
    if (v) {
      loadStats();
      loadTransfers();
    }
  });

  async function transfer() {
    const reason = await promptModal({
      title: `跳槽到 ${airline.value?.icao || ''}`,
      message: `将向 ${airline.value?.icao || ''} ${airline.value?.name || ''} 提交跳槽申请，由对方 CEO 审批。`
        + '审批通过前你仍留在原航司。',
      inputPlaceholder: '跳槽理由，选填',
      confirmText: '提交申请',
    });
    if (reason === null) return;
    transferLoading.value = true;
    try {
      const d = await api.post(`/api/airlines/${airlineId.value}/transfer`, { reason: reason || '' });
      showToast(d.message || '跳槽申请已提交');
      reload();
    } catch (err) {
      showToast(err.message);
    } finally {
      transferLoading.value = false;
    }
  }

  async function cancelTransfer() {
    const ok = await confirmModal({
      title: '撤销跳槽申请', confirmText: '撤销',
      message: `确认撤销到 ${airline.value?.icao || ''} 的跳槽申请？`,
    });
    if (!ok) return;
    try {
      const d = await api.post(
        `/api/airlines/${airlineId.value}/transfers/${myTransfer.value.id}/cancel`,
      );
      showToast(d.message || '已撤销');
      reload();
    } catch (err) {
      showToast(err.message);
    }
  }

  async function reviewTransfer(t, action) {
    let reason = '';
    if (action === 'reject') {
      reason = await promptModal({
        title: '驳回跳槽申请', inputPlaceholder: '请填写驳回原因', confirmText: '驳回',
      });
      if (reason === null) return;
      if (!reason.trim()) { showToast('请填写驳回原因'); return; }
    } else {
      const ok = await confirmModal({
        title: '接收该飞行员',
        message: `确认接收 ${t.username}，CID ${t.cid}？通过后将自动解除其原航司成员关系。`,
        confirmText: '通过',
      });
      if (!ok) return;
    }
    try {
      const d = await api.post(
        `/api/airlines/${airlineId.value}/transfers/${t.id}/review`, { action, reason },
      );
      showToast(d.message || '已处理');
      reload();
    } catch (err) {
      showToast(err.message);
    }
  }

  return {
    transferLoading,
    transfers,
    stats,
    myTransfer,
    pendingTransfers,
    loadTransfers,
    loadStats,
    transfer,
    cancelTransfer,
    reviewTransfer,
  };
}
