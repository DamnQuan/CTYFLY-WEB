import { computed, ref } from 'vue';
import { api } from '../api.js';
import { localDate, showToast } from '../utils.js';
import { confirmModal, promptModal } from '../modal.js';

/** 航司签派与报告：飞行报告提交、审核、航线新增。 */
export function useVaDispatch({ airlineId, canManage, reload }) {
  const reports = ref([]);
  const reportsLoading = ref(false);
  const reportForm = ref({
    routeId: '', aircraft: '', hours: 1.5, flightDate: localDate(), notes: '',
  });
  const submitting = ref(false);

  const STATUS_MAP = {
    pending: { text: '待审核', cls: 'tag-orange' },
    approved: { text: '已通过', cls: 'tag-green' },
    rejected: { text: '已驳回', cls: 'tag-red' },
  };

  const pendingReports = computed(() => reports.value.filter((r) => r.status === 'pending'));

  async function loadReports() {
    reportsLoading.value = true;
    try {
      // 管理成员拉全量报告用于审核；普通成员只看到自己的报告
      const data = await api.get(
        `/api/airlines/${airlineId.value}/reports${canManage.value ? '?scope=all' : ''}`,
      );
      reports.value = data.reports;
    } finally {
      reportsLoading.value = false;
    }
  }

  function rankFor(h) {
    if (h >= 200) return '教员';
    if (h >= 50) return '机长';
    if (h >= 10) return '副驾驶';
    return '学员';
  }

  async function submitReport() {
    if (!reportForm.value.routeId) {
      showToast('请选择航线');
      return;
    }
    submitting.value = true;
    try {
      const d = await api.post(`/api/airlines/${airlineId.value}/reports`, reportForm.value);
      showToast(d.message || '报告已提交');
      reportForm.value = { ...reportForm.value, notes: '' };
      loadReports();
    } catch (err) {
      showToast(err.message);
    } finally {
      submitting.value = false;
    }
  }

  async function reviewReport(r, action) {
    let reason = '';
    if (action === 'reject') {
      reason = await promptModal({
        title: '驳回飞行报告',
        message: `请填写驳回 ${r.username} 报告，${r.dep}-${r.arr}的原因：`,
        placeholder: '驳回原因，必填',
        confirmText: '驳回',
        danger: true,
      });
      if (reason === null) return;
      if (!reason.trim()) return showToast('请填写驳回原因');
    } else {
      const ok = await confirmModal({
        title: '通过飞行报告',
        message: `确认通过 ${r.username} 的报告，${r.dep}-${r.arr} · ${r.hours}h 并发放工资？`,
        confirmText: '通过并发薪',
      });
      if (!ok) return;
    }
    try {
      const d = await api.post(`/api/airlines/${airlineId.value}/reports/${r.id}/review`, { action, reason });
      showToast(d.message || '已处理');
      loadReports();
    } catch (err) {
      showToast(err.message);
    }
  }

  const routeForm = ref({ flightNo: '', dep: '', arr: '', aircraft: '', notes: '', baseSalary: 200, intl: false });

  async function addRoute() {
    try {
      await api.post(`/api/airlines/${airlineId.value}/routes`, routeForm.value);
      showToast('航线已添加');
      routeForm.value = { flightNo: '', dep: '', arr: '', aircraft: '', notes: '', intl: false };
      reload();
    } catch (err) {
      showToast(err.message);
    }
  }

  return {
    reports,
    reportsLoading,
    reportForm,
    submitting,
    STATUS_MAP,
    pendingReports,
    loadReports,
    rankFor,
    submitReport,
    reviewReport,
    routeForm,
    addRoute,
  };
}
