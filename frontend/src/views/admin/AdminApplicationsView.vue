<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { api } from '../../api.js';
import { fmtTime, APP_STATUS, showToast } from '../../utils.js';
import { confirmModal, promptModal } from '../../modal.js';
import UserAvatar from '../../components/UserAvatar.vue';
import SegmentedTabs from '../../components/SegmentedTabs.vue';
import DatePicker from '../../components/DatePicker.vue';

const route = useRoute();
const type = computed(() => (route.params.type === 'staff' ? 'staff' : 'controller'));
const typeLabel = computed(() => (type.value === 'controller' ? '管制员申请' : '职员申请'));
// 面试流程只针对职员申请：先安排面试，面试完成后才能给结论
const isStaff = computed(() => type.value === 'staff');

const apps = ref([]);
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
    const data = await api.get(`/api/admin/applications?status=${status.value}&type=${type.value}`);
    apps.value = data.applications;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);
watch(type, () => { closeInterview(); load(); });

/* ---------- 面试安排 ----------
 * 弹窗是视图内自建的，全局 AppModal 只能放标题/正文/单行文本框，装不下两个时间选择器。
 * 全部使用项目自研组件，DatePicker 的 datetime 模式替代原生 datetime-local，
 * 关闭/确认也走自研按钮 + confirmModal，不使用任何原生控件或原生弹窗。
 */
const interviewOpen = ref(false);
const interviewTarget = ref(null);
const interviewAt1 = ref('');
const interviewAt2 = ref('');
const interviewSending = ref(false);

function openInterview(a) {
  interviewTarget.value = a;
  interviewAt1.value = a.interview_at1 || '';
  interviewAt2.value = a.interview_at2 || '';
  interviewOpen.value = true;
}

function closeInterview() {
  interviewOpen.value = false;
  interviewTarget.value = null;
}

function onKeydown(e) {
  if (e.key === 'Escape' && interviewOpen.value) {
    e.preventDefault();
    closeInterview();
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown));
onUnmounted(() => window.removeEventListener('keydown', onKeydown));

async function sendInterview() {
  const t = interviewTarget.value;
  if (!t) return;
  if (!interviewAt1.value || !interviewAt2.value) return showToast('请选择两个可用面试时间');
  if (interviewAt1.value === interviewAt2.value) return showToast('两个面试时间不能相同');
  interviewSending.value = true;
  try {
    await api.post(`/api/admin/applications/${t.id}/interview`, {
      at1: interviewAt1.value,
      at2: interviewAt2.value,
    });
    showToast('面试邀约已发送，邮件已发给申请人');
    closeInterview();
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    interviewSending.value = false;
  }
}

async function markInterviewDone(a) {
  const ok = await confirmModal({
    title: '标记面试完成',
    message: `确定已完成与 ${a.username}（CID ${a.cid}）的面试吗？标记后即可通过或驳回该申请。`,
    confirmText: '面试已完成',
  });
  if (!ok) return;
  try {
    await api.post(`/api/admin/applications/${a.id}/interview/done`);
    showToast('已标记面试完成，现在可以通过或驳回');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

/** 面试是否已完成 —— 职员申请通过/驳回的前置条件，后端也会拦*/
function interviewDone(a) {
  return !isStaff.value || (a.interview_status || '') === 'done';
}

function interviewLabel(a) {
  const s = a.interview_status || '';
  if (s === 'done') return '面试已完成';
  if (s === 'sent') return '面试邀约已发';
  return '未安排面试';
}

/** 'YYYY-MM-DDTHH:mm' → 'YYYY-MM-DD HH:mm' */
function fmtAt(v) {
  return (v || '').replace('T', ' ');
}

/* ---------- 审核 ---------- */

async function review(a, action) {
  let note = '';
  if (action === 'approve') {
    // 职员申请通过只改申请状态，不授予任何角色/权限，后端 review_application 明确如此。
    // 文案必须说清楚，否则审批人容易以为「通过=给了 SUP」。
    const permHint = isStaff.value
      ? '注意：通过职员申请不会自动授予 SUP 或任何权限，权限需另行在「用户管理」中配置。'
      : '';
    note = await promptModal({
      title: '通过申请',
      message: `确定要通过 ${a.username}（CID ${a.cid}）的${typeLabel.value}吗？${permHint}可填写备注（选填）`,
      placeholder: '审核备注（可留空）',
      confirmText: '通过',
    });
    if (note === null) return;
  } else {
    note = await promptModal({
      title: '驳回申请',
      message: `请填写驳回 ${a.username}（CID ${a.cid}）申请的原因：`,
      placeholder: '未通过原因（必填）',
      confirmText: '驳回',
      danger: true,
    });
    if (note === null) return;
    if (!note.trim()) return showToast('请填写未通过原因');
  }
  try {
    await api.patch(`/api/admin/applications/${a.id}`, { action, note });
    showToast(action === 'approve' ? '已通过申请' : '已驳回申请');
    load();
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">{{ typeLabel }}管理</div>
      <div class="page-desc">
        {{ type === 'controller'
          ? '审核管制员申请，通过后自动授予管制员身份与初始等级'
          : '审核职员申请：需先安排面试，邮件告知两个可用时间并标记面试完成，之后才能通过或驳回；通过仅记录审核结果，不会自动授予 SUP 或任何权限，权限需在「用户管理 / 权限管理」中单独配置' }}
      </div>
    </div>

    <SegmentedTabs class="lg" :options="statusOptions" :model-value="status"
      @update:model-value="(v) => { status = v; load(); }" />

    <div class="glass card">
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else-if="apps.length">
        <div v-for="a in apps" :key="a.id" class="list-item">
          <UserAvatar :user="a" :size="38" />
          <div class="list-main">
            <div class="list-title">{{ a.username }}，CID {{ a.cid }} · {{ a.nickname }}</div>
            <div class="list-sub">
              <template v-if="type === 'controller'">连飞时长 {{ a.hours }} · 经验：{{ a.experience }}</template>
              <template v-else>可参与时间：{{ a.available_time }}</template>
            </div>
            <div class="list-sub">动机：{{ a.motivation || '—' }}</div>
            <div class="list-sub">提交于 {{ fmtTime(a.created_at) }}</div>
            <div v-if="isStaff && a.interview_at1" class="list-sub">
              面试备选：{{ fmtAt(a.interview_at1) }} / {{ fmtAt(a.interview_at2) }}
              <template v-if="a.interview_done_at"> · 完成于 {{ fmtTime(a.interview_done_at) }}</template>
            </div>
          </div>
          <div style="display: flex; flex-direction: column; gap: 6px; align-items: flex-end">
            <span class="tag" :class="APP_STATUS[a.status]?.cls">{{ APP_STATUS[a.status]?.text }}</span>
            <template v-if="a.status === 'pending'">
              <!-- 职员申请：先面试，再决定通过/驳回 -->
              <template v-if="isStaff">
                <span class="tag" :class="a.interview_status === 'done' ? 'tag-blue' : 'tag-orange'">
                  {{ interviewLabel(a) }}
                </span>
                <button class="btn btn-dark btn-sm" @click="openInterview(a)">
                  {{ a.interview_status ? '重新安排面试' : '面试' }}
                </button>
                <button
                  v-if="a.interview_status === 'sent'"
                  class="btn btn-ghost btn-sm"
                  @click="markInterviewDone(a)"
                >面试已完成</button>
              </template>
              <button
                class="btn btn-primary btn-sm"
                :disabled="!interviewDone(a)"
                @click="review(a, 'approve')"
              >通过</button>
              <button
                class="btn btn-danger btn-sm"
                :disabled="!interviewDone(a)"
                @click="review(a, 'reject')"
              >驳回</button>
              <div
                v-if="!interviewDone(a)"
                class="list-sub" style="text-align: right; max-width: 190px"
              >需先完成面试才能通过 / 驳回</div>
            </template>
            <div v-else-if="a.review_note" style="font-size: 12px; color: var(--gray); max-width: 180px; text-align: right">
              {{ a.review_note }}
            </div>
          </div>
        </div>
      </template>
      <div v-else class="empty">暂无申请</div>
    </div>

    <!-- 面试安排弹窗，自建：全局弹窗装不下两个时间选择器；全程自研组件，无原生控件-->
    <Teleport to="body">
      <div v-if="interviewOpen" class="modal-mask" @mousedown.self="closeInterview">
        <div class="modal-panel" role="dialog" aria-modal="true">
          <div class="modal-title">安排面试</div>
          <div class="modal-message">
            给 {{ interviewTarget?.username }}（CID {{ interviewTarget?.cid }}）选择两个可用面试时间，
            发送后系统会邮件告知对方这两个时间，由对方回复确认。
          </div>
          <div class="field" style="margin-top: 14px">
            <label class="label">选择可用面试时间 1</label>
            <DatePicker v-model="interviewAt1" mode="datetime" :clearable="false" placeholder="选择日期与时间" />
          </div>
          <div class="field" style="margin-top: 12px">
            <label class="label">选择可用面试时间 2</label>
            <DatePicker v-model="interviewAt2" mode="datetime" :clearable="false" placeholder="选择日期与时间" />
          </div>
          <div class="list-sub" style="margin-top: 12px">
            面试完成并标记后，才能通过或驳回该申请；两个时间都需晚于当前时间且不能相同。
          </div>
          <div class="modal-actions">
            <button class="btn btn-ghost" @click="closeInterview">取消</button>
            <button class="btn btn-primary" :disabled="interviewSending" @click="sendInterview">
              {{ interviewSending ? '发送中…' : '发送面试' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
