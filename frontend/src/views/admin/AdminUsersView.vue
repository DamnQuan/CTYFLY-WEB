<script setup>
import { computed, onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { showToast } from '../../utils.js';
import { alertModal, confirmModal, promptModal } from '../../modal.js';
import UserAvatar from '../../components/UserAvatar.vue';
import SegmentedTabs from '../../components/SegmentedTabs.vue';
import SelectMenu from '../../components/SelectMenu.vue';
import { useAuthStore } from '../../stores/auth.js';

const auth = useAuthStore();
/** 改等级需要 manage_users 能力；没有就锁住下拉，避免「点得动但接口 403」 */
const canEditRating = computed(() => auth.can('manage_users'));

const users = ref([]);
const ratings = ref([]);       // 管制等级阶梯，由后端下发，单一来源
const pilotRanks = ref([]);    // 飞行员等级阶梯，由后端下发
const loading = ref(false);
const q = ref('');
const roleFilter = ref('');
const statusFilter = ref('');
const roleOptions = [
  { value: '', label: '全部角色' },
  { value: 'user', label: 'USER' },
  { value: 'sup', label: 'SUP' },
  { value: 'admin', label: 'ADM' },
];
// 兜底阶梯：后端未下发时也能正常渲染下拉
const FALLBACK_RATINGS = ['飞行员', 'OBS', 'S1', 'S2', 'S3', 'T2', 'C1', 'C2', 'C3', 'I1', 'I2', 'I3', 'SUP', 'ADM'];
const FALLBACK_PILOT_RANKS = ['学员', '副驾驶', '机长', '教员'];
// banned 置顶展示：封禁审议触发器，选中后走双人审批，后端拦截，不改等级字段
const ratingOptions = computed(() => [{ value: 'banned', label: 'banned（发起封禁审议）' }]
  .concat((ratings.value.length ? ratings.value : FALLBACK_RATINGS)
  .map((r) => ({ value: r, label: r }))));
const rankOptions = computed(() => (pilotRanks.value.length ? pilotRanks.value : FALLBACK_PILOT_RANKS)
  .map((r) => ({ value: r, label: r })));
const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'active', label: '正常' },
  { value: 'banned', label: '已封禁' },
  { value: 'deleted', label: '已注销' },
];

const ROLE_TEXT = { admin: 'ADM', sup: 'SUP', user: 'USER' };
const STATUS_MAP = {
  active: { text: '正常', cls: 'tag-green' },
  banned: { text: '已封禁', cls: 'tag-red' },
  deleted: { text: '已注销', cls: 'tag' },
};

async function load() {
  loading.value = true;
  try {
    const data = await api.get(
      `/api/admin/users?q=${encodeURIComponent(q.value)}&role=${roleFilter.value}&status=${statusFilter.value}`,
    );
    users.value = data.users;
    if (data.ratings?.length) ratings.value = data.ratings;
    if (data.pilotRanks?.length) pilotRanks.value = data.pilotRanks;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

/* 等级 / 职级：选完即刻保存。
   之前的做法是「先下拉、再点旁边的『存』」，那个按钮太小、很容易以为选完就生效了，
   所以改成选择即提交：乐观更新 + 失败回滚，行内显示保存中状态。 */
const saving = ref('');   // `${user.id}:rating` | `${user.id}:rank`

async function changeRating(u, next) {
  const prev = u.rating;
  if (!next || next === prev) return;
  // banned = 发起封禁审议：先确认，走双人审批流，通过后才真正封禁
  if (next === 'banned') {
    const ok = await confirmModal({
      title: '发起封禁审议', danger: true, confirmText: '发起审议',
      message: `确定要对 ${u.username}（CID ${u.cid}）发起封禁审议吗？` +
        '将提交另一位管理员复核，通过后账号才会被封禁。',
    });
    if (!ok) return;
  }
  u.rating = next;                                  // 先改界面，交互不卡顿
  saving.value = `${u.id}:rating`;
  try {
    await api.patch(`/api/admin/users/${u.id}`, { rating: next });
    showToast(next === 'banned'
      ? `已对 ${u.username} 发起封禁审议，待另一位管理员复核`
      : `已将 ${u.username} 的管制等级改为 ${next}`);
  } catch (err) {
    u.rating = prev;                                // 失败回滚，避免界面与后端不一致
    showToast(err.message);
  } finally {
    if (saving.value === `${u.id}:rating`) saving.value = '';
  }
}

async function changeRank(u, next) {
  const prev = u.pilot_rank;
  if (!next || next === prev) return;
  u.pilot_rank = next;
  saving.value = `${u.id}:rank`;
  try {
    await api.patch(`/api/admin/users/${u.id}`, { pilotRank: next });
    showToast(`已将 ${u.username} 的飞行员等级改为 ${next}`);
  } catch (err) {
    u.pilot_rank = prev;
    showToast(err.message);
  } finally {
    if (saving.value === `${u.id}:rank`) saving.value = '';
  }
}
async function resetPassword(u) {
  const ok = await confirmModal({
    title: '重置密码', confirmText: '重置',
    message: `确定要为 ${u.username}（CID ${u.cid}）生成新密码吗？其所有登录会话将失效。`,
  });
  if (!ok) return;
  try {
    const data = await api.patch(`/api/admin/users/${u.id}`, { resetPassword: true });
    await alertModal({
      title: '密码已重置', copyable: true, alertValue: data.newPassword,
      message: `请把新密码安全地告知 ${u.username}：`, hideCancel: true, confirmText: '完成',
    });
  } catch (err) {
    showToast(err.message);
  }
}

/* 敏感操作：走双人复核审批 */
async function requestApproval(u, type) {
  let role = null;
  if (type === 'role_change') {
    const input = await promptModal({
      title: '发起角色变更审批',
      message: `目标：${u.username}，当前 ${ROLE_TEXT[u.role]}。请输入目标角色：user / sup / admin`,
      placeholder: 'user / sup / admin',
      confirmText: '下一步',
    });
    if (input === null) return;
    role = input.trim().toLowerCase();
    if (!['user', 'sup', 'admin'].includes(role)) return showToast('角色无效，只能填 user / sup / admin');
  }
  const reason = await promptModal({
    title: type === 'ban' ? '发起封禁审批' : type === 'delete_account' ? '发起删除账户审批' : '填写申请理由',
    message: `目标：${u.username}，CID ${u.cid}${role ? ` → ${role.toUpperCase()}` : ''}。请填写理由（必填）`,
    placeholder: '申请理由',
    confirmText: '提交审批',
    danger: type !== 'role_change',
  });
  if (reason === null) return;
  if (!reason.trim()) return showToast('请填写申请理由');

  try {
    const data = await api.post(`/api/admin/users/${u.id}/approvals`, { type, role, reason });
    showToast(data.message || '已提交审批');
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">用户管理</div>
      <div class="page-desc">
        查看注册来源与设备指纹；<strong>管制等级 / 飞行员等级选择后即刻生效</strong>，角色变更、封禁、删除账户需双人复核审批
      </div>
      <div v-if="!canEditRating" class="alert" style="margin-top: 10px">
        你当前没有「修改用户等级」权限，下面的等级下拉已锁定，需要 manage_users 能力。
      </div>
    </div>

    <div class="glass card" style="margin-bottom: 16px">
      <div class="input-row" style="max-width: 720px">
        <input v-model="q" class="input" placeholder="搜索用户 ID / CID / 用户名 / 邮箱" @keyup.enter="load" />
        <button class="btn btn-primary" @click="load">搜索</button>
      </div>
      <div style="display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap">
        <SegmentedTabs :options="roleOptions" :model-value="roleFilter"
          @update:model-value="(v) => { roleFilter = v; load(); }" />
        <SegmentedTabs :options="statusOptions" :model-value="statusFilter"
          @update:model-value="(v) => { statusFilter = v; load(); }" />
      </div>
    </div>

    <div class="glass card">
      <div v-if="loading" class="loading">加载中…</div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>用户</th><th>角色</th><th>管制等级</th><th>飞行员等级</th><th>状态</th>
              <th>注册来源</th><th>设备指纹</th><th>最近登录</th><th>IPv6</th><th style="min-width: 300px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td>
                <div style="display: flex; align-items: center; gap: 8px">
                  <UserAvatar :user="u" :size="26" />
                  <div>
                    <div style="font-weight: 500">
                      <span class="list-sub" style="margin-right: 6px">#{{ u.id }}</span>{{ u.username }}
                    </div>
                    <div class="list-sub">CID {{ u.cid }}</div>
                  </div>
                </div>
              </td>
              <td>
                <span :class="u.role === 'admin' ? 'tag tag-red' : u.role === 'sup' ? 'tag tag-purple' : 'tag'">
                  {{ ROLE_TEXT[u.role] || u.role }}
                </span>
              </td>
              <td>
                <div style="display: flex; gap: 6px; align-items: center">
                  <div style="width: 104px">
                    <SelectMenu
                      :model-value="u.rating"
                      :options="ratingOptions"
                      :disabled="!canEditRating || saving === `${u.id}:rating`"
                      placeholder="选择等级"
                      @update:model-value="(v) => changeRating(u, v)"
                    />
                  </div>
                  <span v-if="saving === `${u.id}:rating`" class="list-sub">保存中…</span>
                </div>
              </td>
              <td>
                <div style="display: flex; gap: 6px; align-items: center">
                  <div style="width: 112px">
                    <SelectMenu
                      :model-value="u.pilot_rank"
                      :options="rankOptions"
                      :disabled="!canEditRating || saving === `${u.id}:rank`"
                      placeholder="选择等级"
                      @update:model-value="(v) => changeRank(u, v)"
                    />
                  </div>
                  <span v-if="saving === `${u.id}:rank`" class="list-sub">保存中…</span>
                </div>
              </td>
              <td><span class="tag" :class="STATUS_MAP[u.status]?.cls">{{ STATUS_MAP[u.status]?.text || u.status }}</span></td>
              <td>
                <div style="font-size: 12.5px">{{ u.reg_ip || '—' }}</div>
                <div class="list-sub">{{ u.reg_geo || '内网/未解析' }}</div>
                <div class="list-sub">{{ u.created_at?.slice(0, 16) }}</div>
                <span v-if="u.reg_ua" :class="u.reg_ua_bot ? 'tag tag-red' : 'tag tag-green'" style="margin-top: 4px">
                  {{ u.reg_ua_bot ? '脚本/爬虫' : '浏览器' }}
                </span>
                <div v-if="u.reg_ua_label" class="list-sub">{{ u.reg_ua_label }}</div>
              </td>
              <td><code style="font-size: 11.5px">{{ u.reg_fingerprint ? u.reg_fingerprint.slice(0, 9) : '—' }}</code></td>
              <td>
                <div style="font-size: 12.5px">{{ u.last_login_at || '—' }}</div>
                <div class="list-sub">{{ u.last_login_ip || '' }} {{ u.last_login_geo || '' }}</div>
              </td>
              <!-- 浏览器主动探测到的公网 IPv6，站点只有 IPv4 入口时的补充线索；空=未探测到-->
              <td>
                <template v-if="u.last_ip_v6">
                  <code style="font-size: 11.5px">{{ u.last_ip_v6 }}</code>
                  <div class="list-sub">{{ u.last_ip_v6_at || '' }}</div>
                </template>
                <span v-else class="list-sub">—</span>
              </td>
              <td>
                <div style="display: flex; gap: 6px; flex-wrap: wrap">
                  <button class="btn btn-ghost btn-sm" @click="resetPassword(u)">重置密码</button>
                  <button class="btn btn-ghost btn-sm" @click="requestApproval(u, 'role_change')">角色变更审批</button>
                  <button v-if="u.status !== 'banned'" class="btn btn-danger btn-sm" @click="requestApproval(u, 'ban')">封禁审批</button>
                  <button class="btn btn-danger btn-sm" @click="requestApproval(u, 'delete_account')">删除审批</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!users.length" class="empty">没有匹配的用户，试试调整搜索条件或筛选</div>
      </div>
    </div>
  </div>
</template>
