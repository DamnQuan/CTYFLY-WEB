import { computed, ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api, getToken } from '../api.js';
import { useAuthStore } from '../stores/auth.js';
import { localDate, localMonth, showToast } from '../utils.js';
import { confirmModal, promptModal } from '../modal.js';
import { useAirlineDetail } from './useAirlineDetail.js';
import { useVaDispatch } from './useVaDispatch.js';
import { useVaFleet } from './useVaFleet.js';

/** 航司详情页全部业务状态与动作；视图只负责编排与渲染。 */
export function useAirlineDetailPage() {

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const authUserId = computed(() => auth.user?.id);
const airlineId = computed(() => Number(route.params.id));

const {
  data, loading, error, joinLoading, airline, isCeo, myMembership,
  canManage, isMember, pendingJoin, inOtherAirline, pendingMembers, fetchDetail,
} = useAirlineDetail(airlineId);

const {
  reports, reportsLoading, reportForm, submitting, STATUS_MAP, pendingReports,
  loadReports, rankFor, submitReport, reviewReport, routeForm, addRoute,
} = useVaDispatch({ airlineId, canManage, reload: load });

const {
  transferLoading, stats, myTransfer, pendingTransfers,
  loadTransfers, transfer, cancelTransfer, reviewTransfer,
} = useVaFleet({ airlineId, isCeo, airline, data, reload: load });

// 时薪设置
const hourlyRate = ref(100);
const hub = ref('');
const distanceRate = ref(1);
const logoUrl = ref('');
const savingRate = ref(false);
const savingLogo = ref(false);

// 工资单导出
const payrollMonth = ref(localMonth());
const exporting = ref(false);
async function exportPayroll() {
  exporting.value = true;
  try {
    const resp = await fetch(
      `/api/airlines/${route.params.id}/payroll/export?month=${payrollMonth.value}`,
      { headers: { Authorization: `Bearer ${getToken()}` } },
    );
    if (!resp.ok) throw new Error();
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `payroll-${airline.value.icao}-${payrollMonth.value}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('工资单已导出');
  } catch {
    showToast('导出失败，请重试');
  } finally {
    exporting.value = false;
  }
}

/* ---------- 资金管理，CEO / 部长：公司余额 + 账本流水，只读 ----------*/
const ledger = ref(null);
const ledgerLoading = ref(false);
const ledgerLoadingMore = ref(false);
const ledgerType = ref(''); // '' 全部 | revenue 收入 | expense 支出

async function loadLedger(more = false) {
  if (!canManage.value) return;
  if (more) ledgerLoadingMore.value = true;
  else ledgerLoading.value = true;
  // 分页只传 page：页大小由后端硬编码，运维手册血泪清单 §8.7，
  // 后端不接受用户可控的 LIMIT；「加载更多」就是 page+1 再追加
  const page = more && ledger.value ? (ledger.value.page || 1) + 1 : 1;
  try {
    const qs = new URLSearchParams({ page: String(page) });
    if (ledgerType.value) qs.set('type', ledgerType.value);
    const d = await api.get(`/api/airlines/${airlineId.value}/ledger?${qs.toString()}`);
    ledger.value = more && ledger.value
      ? { ...d, records: [...ledger.value.records, ...d.records] }
      : d;
  } catch (err) {
    if (!more) ledger.value = null;
    showToast(err.message);
  } finally {
    ledgerLoading.value = false;
    ledgerLoadingMore.value = false;
  }
}

function setLedgerType(v) {
  ledgerType.value = v;
  loadLedger(false);
}

/** 金额千分位，账本 amount 带符号：收入为正、支出为负*/
function money(v) {
  return Number(v ?? 0).toLocaleString();
}

function signedMoney(v) {
  const n = Number(v ?? 0);
  return (n > 0 ? '+' : '') + n.toLocaleString();
}

/** 距离统一保留 2 位小数 */
function nm(v) {
  return Number(v ?? 0).toFixed(2);
}

// 我已向本航司提交的待审批跳槽申请
// 选项卡
const tab = ref('members');
// 仅首次加载把管理成员带到「管理中心」；此后，含操作触发 refresh 不再强制拉回
let manageTabDefaulted = false;
const tabOptions = computed(() => {
  const base = [];
  // 管理中心，CEO / 部长：聚合日常管理操作；无管理权限的成员看不到该 tab
  if (canManage.value) base.push({ value: 'manage', label: '管理中心' });
  base.push(
    { value: 'members', label: '成员' },
    { value: 'routes', label: '航线' },
  );
  if (isMember.value) base.push({ value: 'reports', label: '飞行报告' }, { value: 'posts', label: '动态' });
  if (isMember.value) base.push({ value: 'exams', label: '考核' });
  if (isMember.value) base.push({ value: 'public', label: '对外主页' });
  return base;
});

/* ---------- 对外主页自定义，CEO / 部长可改 ----------*/
const pubForm = ref({
  name: '', description: '', slogan: '', welcome: '',
  showMembers: true, showRoutes: true, showFleet: true, showStats: true,
});
const savingPub = ref(false);
const showPreview = ref(false);

/* 预览取值：管理者，CEO / 部长看未保存的表单内容，其他成员看已保存的设置*/
const previewName = computed(() => (canManage.value ? pubForm.value.name : airline.value?.name || ''));
const previewSlogan = computed(() => (canManage.value ? pubForm.value.slogan : airline.value?.slogan || ''));
const previewDescription = computed(() =>
  (canManage.value ? pubForm.value.description : airline.value?.description || ''));
const previewWelcome = computed(() => (canManage.value ? pubForm.value.welcome : airline.value?.welcome || ''));
const previewLogo = computed(() => (canManage.value ? logoUrl.value : airline.value?.logo_url || ''));
const previewFlags = computed(() => (canManage.value
  ? pubForm.value
  : {
      showStats: airline.value?.show_stats !== false,
      showFleet: airline.value?.show_fleet !== false,
      showRoutes: airline.value?.show_routes !== false,
      showMembers: airline.value?.show_members !== false,
    }));
const previewFleet = computed(() =>
  [...new Set((data.value?.routes || []).map((r) => r.aircraft).filter(Boolean))]);

async function copyPublicLink() {
  const url = `${window.location.origin}/va/${airline.value?.icao}`;
  try {
    await navigator.clipboard.writeText(url);
    showToast('主页链接已复制');
  } catch {
    showToast(url);
  }
}

/** 就地切到「对外主页」选项卡并展开预览，不发生页面跳转 */
function openPublicPreview() {
  tab.value = 'public';
  showPreview.value = true;
}

function fillPubForm() {
  const a = data.value?.airline;
  if (!a) return;
  pubForm.value = {
    name: a.name || '',
    description: a.description || '',
    slogan: a.slogan || '',
    welcome: a.welcome || '',
    showMembers: a.show_members !== false,
    showRoutes: a.show_routes !== false,
    showFleet: a.show_fleet !== false,
    showStats: a.show_stats !== false,
  };
}

async function savePublicPage() {
  savingPub.value = true;
  try {
    const d = await api.put(`/api/airlines/${route.params.id}/public-page`, pubForm.value);
    showToast(d.message || '对外主页已更新');
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    savingPub.value = false;
  }
}

// 升级考核
const exams = ref([]);
const examMe = ref(null);
const examForm = ref({ flightDate: localDate(), routeFlown: '', aircraft: '', notes: '' });
const submittingExam = ref(false);

// 内部动态
const posts = ref([]);
const postsLoading = ref(false);
const newPost = ref('');
const newComments = ref({});

async function load() {
  const detail = await fetchDetail();
  if (!detail) return;
  hourlyRate.value = detail.hourlyRate || 100;
  distanceRate.value = detail.distanceRate ?? 1;
  hub.value = detail.airline?.hub || '';
  logoUrl.value = detail.airline?.logo_url || '';
  fillPubForm();
  if (canManage.value && !manageTabDefaulted) { tab.value = 'manage'; manageTabDefaulted = true; }
  if (isMember.value) { loadReports(); loadExams(); loadPosts(); }
  if (canManage.value) loadLedger(false);
  loadTransfers();
}

/* ---------- 升级考核 ---------- */
async function loadExams() {
  try {
    const d = await api.get(`/api/airlines/${airlineId.value}/exams`);
    exams.value = d.exams;
    examMe.value = d.me || null;
  } catch { /* */ }
}
// 本人晋升进度：当前等级 / 累计时长 / 下一考核目标与达标情况
const examProgress = computed(() => {
  const me = examMe.value;
  if (!me) return null;
  if (!me.target) return { maxed: true, rank: me.pilotRank, hours: me.totalHours };
  const pct = Math.min(100, Math.round((me.totalHours / me.targetHours) * 100));
  return {
    maxed: false,
    rank: me.pilotRank,
    hours: me.totalHours,
    target: me.target,
    need: me.targetHours,
    remain: Math.max(0, me.targetHours - me.totalHours),
    pct,
    eligible: me.totalHours >= me.targetHours,
    hasPending: me.hasPending,
  };
});
const canSubmitExam = computed(() => {
  const p = examProgress.value;
  return !!p && !p.maxed && p.eligible && !p.hasPending;
});
const examSubmitHint = computed(() => {
  const p = examProgress.value;
  if (!p) return '';
  if (p.maxed) return '已达到最高可考核等级，无需再提交考核';
  if (p.hasPending) return '你已有一个待审核的考核申请，审核完成后可再次提交';
  if (p.eligible) return `当前可申请：${p.target}考核`;
  return `未达标：距${p.target}考核还差 ${p.remain.toFixed(1)} h`;
});
async function submitExam() {
  if (!canSubmitExam.value) return showToast(examSubmitHint.value);
  submittingExam.value = true;
  try {
    const d = await api.post(`/api/airlines/${airlineId.value}/exams`, examForm.value);
    showToast(d.message || '考核已提交');
    examForm.value = { flightDate: localDate(), routeFlown: '', aircraft: '', notes: '' };
    loadExams();
  } catch (err) { showToast(err.message); }
  finally { submittingExam.value = false; }
}
async function reviewExam(e, action) {
  let reason = '';
  if (action === 'reject') {
    reason = await promptModal({ title: '驳回考核', message: `请填写驳回 ${e.username} 的${e.target_rank}考核原因：`, placeholder: '驳回原因，必填', confirmText: '驳回', danger: true });
    if (reason === null) return;
    if (!reason.trim()) return showToast('请填写驳回原因');
  } else {
    const ok = await confirmModal({ title: '通过考核', confirmText: '通过', message: `确认通过 ${e.username} 的${e.target_rank}考核并晋升？` });
    if (!ok) return;
  }
  try {
    const d = await api.post(`/api/airlines/${airlineId.value}/exams/${e.id}/review`, { action, reason });
    showToast(d.message); loadExams();
  } catch (err) { showToast(err.message); }
}

/* ---------- 内部动态 ---------- */
async function loadPosts() {
  postsLoading.value = true;
  try { posts.value = (await api.get(`/api/airlines/${airlineId.value}/posts`)).posts; }
  finally { postsLoading.value = false; }
}
async function publishPost() {
  if (!newPost.value.trim()) return;
  try {
    await api.post(`/api/airlines/${airlineId.value}/posts`, { content: newPost.value });
    newPost.value = ''; loadPosts();
  } catch (err) { showToast(err.message); }
}
async function toggleLike(p) {
  try { await api.post(`/api/airlines/${airlineId.value}/posts/${p.id}/like`); loadPosts(); }
  catch (err) { showToast(err.message); }
}
async function addComment(p) {
  const text = (newComments.value[p.id] || '').trim();
  if (!text) return;
  try {
    await api.post(`/api/airlines/${airlineId.value}/posts/${p.id}/comments`, { content: text });
    newComments.value[p.id] = ''; loadPosts();
  } catch (err) { showToast(err.message); }
}
async function deletePost(p) {
  const ok = await confirmModal({ title: '删除动态', danger: true, confirmText: '删除', message: '确认删除这条动态？' });
  if (!ok) return;
  try { await api.delete(`/api/airlines/${airlineId.value}/posts/${p.id}`); loadPosts(); }
  catch (err) { showToast(err.message); }
}
async function pinPost(p) {
  try { await api.post(`/api/airlines/${airlineId.value}/posts/${p.id}/pin`, { pinned: !p.pinned }); loadPosts(); }
  catch (err) { showToast(err.message); }
}

async function saveRate() {
  savingRate.value = true;
  try {
    // 经济参数属资金敏感项：后端已收窄为仅 CEO，原 _require_manager 允许部长
    await api.put(`/api/airlines/${route.params.id}/settings`, {
      hourlyRate: hourlyRate.value,
      distanceRate: distanceRate.value,
      hub: hub.value || '',
    });
    showToast(`已保存：时薪 ${hourlyRate.value}/h · 距离补贴 ${distanceRate.value}/NM · 主基地 ${hub.value || '未设'}`);
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    savingRate.value = false;
  }
}

// Logo 单独保存：经济参数已挪到「资金管理」卡，这里不再共用一个保存按钮
async function saveLogo() {
  savingLogo.value = true;
  try {
    await api.put(`/api/airlines/${route.params.id}/settings`, {
      hourlyRate: hourlyRate.value,
      distanceRate: distanceRate.value,
      logoUrl: logoUrl.value,
    });
    showToast('航司 Logo 已更新');
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    savingLogo.value = false;
  }
}

const pendingExams = computed(() => exams.value.filter((e) => e.status === 'pending'));

onMounted(load);

async function join() {
  joinLoading.value = true;
  try {
    const d = await api.post(`/api/airlines/${route.params.id}/join`);
    showToast(d.message || '申请已提交');
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    joinLoading.value = false;
  }
}

async function leave() {
  const ok = await confirmModal({
    title: '退出航司', danger: true, confirmText: '退出',
    message: `确认退出 ${airline.value.icao} ${airline.value.name}？`,
  });
  if (!ok) return;
  try {
    await api.post(`/api/airlines/${route.params.id}/leave`);
    showToast('已退出航司');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

async function reviewMember(m, action) {
  try {
    await api.post(`/api/airlines/${route.params.id}/members/${m.id}/review`, { action });
    showToast(action === 'approve' ? '已通过申请' : '已拒绝申请');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

async function removeMember(m) {
  const ok = await confirmModal({
    title: '移除成员', danger: true, confirmText: '移除',
    message: `确认将 ${m.username}，CID ${m.cid}，移出航司？`,
  });
  if (!ok) return;
  try {
    await api.delete(`/api/airlines/${route.params.id}/members/${m.uid}`);
    showToast('已移除');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

/* 成员职位，现实飞行阶梯：CEO 设置或清除*/
const positionOptions = computed(() => data.value?.positionOptions || []);
async function setPosition(m, position) {
  try {
    const d = await api.put(`/api/airlines/${route.params.id}/members/${m.id}/position`, { position });
    m.position = position;
    showToast(d.message || '已更新职位');
  } catch (err) {
    showToast(err.message);
  }
}

/* 部长任命，仅 CEO：对非 CEO 成员任命 / 取消部长；重复设置后端返回「状态未变化」不算错误*/
async function setMinister(m) {
  try {
    const d = await api.post(
      `/api/airlines/${route.params.id}/members/${m.id}/minister`,
      { on: !m.minister },
    );
    showToast(d.message || (!m.minister ? '已任命为部长' : '已取消部长'));
    load();
  } catch (err) {
    showToast(err.message);
  }
}

/* CSV 批量导入航线，Newsky 排班表导出格式*/
const csvInput = ref(null);
const importingCsv = ref(false);

function pickCsv() {
  csvInput.value?.click();
}

async function importRoutesCsv(ev) {
  const file = ev.target.files?.[0];
  ev.target.value = '';
  if (!file) return;
  const ok = await confirmModal({
    title: 'CSV 批量导入航线', confirmText: '导入',
    message: `确认导入「${file.name}」？将按航班号去重，重复与无效行自动跳过。`,
  });
  if (!ok) return;
  importingCsv.value = true;
  try {
    const fd = new FormData();
    fd.append('file', file);
    const data = await api.upload(`/api/airlines/${route.params.id}/routes/import`, fd);
    showToast(data.message || '导入完成');
    if (data.errors?.length) showToast(data.errors[0]);
    load();
  } catch (err) {
    showToast(err.message);
  }
  importingCsv.value = false;
}

async function deleteRoute(r) {
  const ok = await confirmModal({
    title: '删除航线', danger: true, confirmText: '删除',
    message: `确认删除航线 ${r.flight_no}，${r.dep} → ${r.arr}？`,
  });
  if (!ok) return;
  try {
    await api.delete(`/api/airlines/${route.params.id}/routes/${r.id}`);
    showToast('已删除');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

async function disband() {
  const ok = await confirmModal({
    title: '解散航司', danger: true, confirmText: '解散',
    message: `确认解散 ${airline.value.icao} ${airline.value.name}？所有成员与航线数据将被删除，不可恢复。`,
  });
  if (!ok) return;
  try {
    const d = await api.delete(`/api/airlines/${route.params.id}`);
    showToast(d.message || '已解散');
    router.push('/airlines');
  } catch (err) {
    showToast(err.message);
  }
}


  return {
    STATUS_MAP,
    addComment,
    addRoute,
    airline,
    airlineId,
    authUserId,
    canManage,
    canSubmitExam,
    cancelTransfer,
    copyPublicLink,
    csvInput,
    data,
    deletePost,
    deleteRoute,
    disband,
    distanceRate,
    error,
    examForm,
    examMe,
    examProgress,
    examSubmitHint,
    exams,
    exportPayroll,
    exporting,
    fetchDetail,
    fillPubForm,
    hourlyRate,
    hub,
    importRoutesCsv,
    importingCsv,
    inOtherAirline,
    isCeo,
    isMember,
    join,
    joinLoading,
    leave,
    ledger,
    ledgerLoading,
    ledgerLoadingMore,
    ledgerType,
    load,
    loadExams,
    loadLedger,
    loadPosts,
    loadReports,
    loadTransfers,
    loading,
    logoUrl,
    manageTabDefaulted,
    money,
    myMembership,
    myTransfer,
    newComments,
    newPost,
    nm,
    openPublicPreview,
    payrollMonth,
    pendingExams,
    pendingJoin,
    pendingMembers,
    pendingReports,
    pendingTransfers,
    pickCsv,
    pinPost,
    positionOptions,
    posts,
    postsLoading,
    previewDescription,
    previewFlags,
    previewFleet,
    previewLogo,
    previewName,
    previewSlogan,
    previewWelcome,
    pubForm,
    publishPost,
    rankFor,
    removeMember,
    reportForm,
    reports,
    reportsLoading,
    reviewExam,
    reviewMember,
    reviewReport,
    reviewTransfer,
    routeForm,
    saveLogo,
    savePublicPage,
    saveRate,
    savingLogo,
    savingPub,
    savingRate,
    setLedgerType,
    setMinister,
    setPosition,
    showPreview,
    signedMoney,
    stats,
    submitExam,
    submitReport,
    submitting,
    submittingExam,
    tab,
    tabOptions,
    toggleLike,
    transfer,
    transferLoading,
  };
}
