<script setup>
import { computed, ref, onMounted } from 'vue';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import { confirmModal, promptModal } from '../modal.js';
import Icon from '../components/Icon.vue';
import LogoUploader from '../components/LogoUploader.vue';

const airlines = ref([]);
const mine = ref(null);
const myApplication = ref(null);
const myTransfer = ref(null);
const loading = ref(true);
const busyId = ref(0);

// 创建表单
const showCreate = ref(false);
const creating = ref(false);
const createError = ref('');
const form = ref({ icao: '', name: '', description: '', logoUrl: '' });

const applicationPending = computed(() => myApplication.value?.status === 'pending');
const applicationRejected = computed(() => myApplication.value?.status === 'rejected');
const canCreate = computed(() => !mine.value && !applicationPending.value && myApplication.value?.status !== 'approved');
const membershipStatusText = computed(() => {
  if (!mine.value) return '';
  if (mine.value.role === 'ceo') return 'CEO';
  return mine.value.status === 'pending' ? '加入申请审核中' : '正式飞行员';
});

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/airlines');
    airlines.value = data.airlines;
    mine.value = data.mine;
    myApplication.value = data.myApplication || null;
    myTransfer.value = data.myTransfer || null;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

function fillApplicationForm() {
  const app = myApplication.value;
  if (!app) return;
  form.value = {
    icao: app.icao || '',
    name: app.name || '',
    description: app.description || '',
    logoUrl: app.logo_url || '',
  };
}

/** 创建入口常驻：已加入航司时点击给出明确原因，而不是把按钮藏起来 */
function openCreate() {
  if (mine.value) {
    showToast(`你已加入 ${mine.value.icao}，需先退出或解散当前航司才能创建`);
    return;
  }
  if (applicationPending.value) {
    showToast('你的建司申请正在审核中，请等待管理员处理');
    return;
  }
  if (!showCreate.value && applicationRejected.value) fillApplicationForm();
  showCreate.value = !showCreate.value;
}

async function create() {
  createError.value = '';
  creating.value = true;
  try {
    const data = await api.post('/api/airlines', form.value);
    showToast(data.message || '创建申请已提交');
    showCreate.value = false;
    form.value = { icao: '', name: '', description: '', logoUrl: '' };
    load();
  } catch (err) {
    createError.value = err.message;
  } finally {
    creating.value = false;
  }
}

async function join(a) {
  busyId.value = a.id;
  try {
    const data = await api.post(`/api/airlines/${a.id}/join`);
    showToast(data.message || '申请已提交');
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    busyId.value = 0;
  }
}

/** 我要跳槽：批准前仍在原航司，由目标航司 CEO 审批 */
async function transfer(a) {
  const reason = await promptModal({
    title: `跳槽到 ${a.icao}`,
    message: `将向 ${a.icao} ${a.name} 提交跳槽申请，由对方 CEO 审批。审批通过前你仍留在 ${mine.value.icao}。`,
    inputPlaceholder: '跳槽理由（选填）',
    confirmText: '提交申请',
  });
  if (reason === null) return;
  busyId.value = a.id;
  try {
    const data = await api.post(`/api/airlines/${a.id}/transfer`, { reason: reason || '' });
    showToast(data.message || 'bingo~跳槽申请提交成功~');
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    busyId.value = 0;
  }
}

async function cancelTransfer() {
  const ok = await confirmModal({
    title: '撤销跳槽申请', confirmText: '撤销',
    message: `确定要撤销到 ${myTransfer.value.to_icao} 的跳槽申请吗？`,
  });
  if (!ok) return;
  try {
    const data = await api.post(`/api/airlines/${myTransfer.value.to_airline_id}/transfers/${myTransfer.value.id}/cancel`);
    showToast(data.message || '已撤销');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

async function leave() {
  const pending = mine.value.status === 'pending';
  const ok = await confirmModal({
    title: pending ? '撤销加入申请' : '退出航司',
    message: pending
      ? `确定要撤回向 ${mine.value.icao} ${mine.value.name} 提交的加入申请吗？`
      : `确定要退出 ${mine.value.icao} ${mine.value.name} 吗？退出后可重新申请加入其他航司。`,
    danger: true,
    confirmText: pending ? '撤回申请' : '退出',
  });
  if (!ok) return;
  try {
    await api.post(`/api/airlines/${mine.value.airline_id}/leave`);
    showToast(pending ? '已撤回加入申请' : '已退出航司');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

async function disband() {
  const ok = await confirmModal({
    title: '解散航司',
    message: `确定要解散 ${mine.value.icao} ${mine.value.name} 吗？所有成员与航线数据将被删除，且无法恢复。`,
    danger: true,
    confirmText: '解散',
  });
  if (!ok) return;
  try {
    const data = await api.delete(`/api/airlines/${mine.value.airline_id}`);
    showToast(data.message || '已解散');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

/** 每家航司右下角该显示什么操作 */
function actionFor(a) {
  if (myTransfer.value && myTransfer.value.to_airline_id === a.id) return 'transferring';
  if (!mine.value) return 'join';
  if (mine.value.airline_id === a.id) return 'inside';
  if (mine.value.role === 'ceo') return 'ceo';
  if (mine.value.status !== 'active') return 'pending';
  return 'transfer';
}
</script>

<template>
  <div class="page">
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
      <div>
        <div class="page-title">虚拟航司</div>
        <div class="page-desc">创建或加入虚拟航司，维护航线网络，经营你的航空公司</div>
      </div>
      <button class="btn btn-dark" @click="openCreate">
        <Icon :name="showCreate && canCreate ? 'x' : 'plus'" :size="15" />
        {{ showCreate && canCreate ? '收起' : applicationPending ? '申请审核中' : applicationRejected ? '重新申请' : '创建航司' }}
      </button>
    </div>

    <!-- 建司申请状态：被驳回后允许修改并重新提交 -->
    <div v-if="!mine && myApplication && (applicationPending || applicationRejected)" class="glass card" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
        <div>
          <div class="card-title" style="margin-bottom: 4px">
            建司申请
            <span :class="applicationPending ? 'tag tag-orange' : 'tag tag-red'" style="margin-left: 8px">
              {{ applicationPending ? '审核中' : '已驳回' }}
            </span>
          </div>
          <div class="card-sub" style="margin-bottom: 0">
            <template v-if="applicationPending">
              你的建司申请正在审核中，请等待管理员处理。
              <template v-if="myApplication.review_note">上次审核意见：{{ myApplication.review_note }}</template>
            </template>
            <template v-else>
              上次申请未通过：{{ myApplication.review_note || '未通过审核' }}。修改资料后可以重新提交。
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 我的航司 -->
    <div v-if="mine" class="glass card" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
        <div style="display: flex; gap: 16px; align-items: center">
          <div class="va-badge">
            <img v-if="mine.logo_url" :src="mine.logo_url" alt="" />
            <template v-else>{{ mine.icao }}</template>
          </div>
          <div>
            <div class="card-title" style="margin-bottom: 2px">
              {{ mine.name }}
              <span :class="mine.role === 'ceo' ? 'tag tag-red' : (mine.status === 'pending' ? 'tag tag-orange' : 'tag tag-green')" style="margin-left: 8px">
                {{ membershipStatusText }}
              </span>
            </div>
            <div class="card-sub" style="margin-bottom: 0">
              <template v-if="mine.status === 'pending' && mine.role !== 'ceo'">加入申请审核中，请等待 CEO 审批</template>
              <template v-else-if="myTransfer">跳槽申请已提交，等待 {{ myTransfer.to_icao }} 审批</template>
              <template v-else>你的身份：{{ mine.role === 'ceo' ? '首席执行官（CEO）' : '飞行员' }}</template>
            </div>
          </div>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
          <span v-if="myTransfer" class="tag tag-orange">
            待转往 {{ myTransfer.to_icao }} · {{ myTransfer.to_name }}
          </span>
          <button v-if="myTransfer" class="btn btn-ghost btn-sm" @click="cancelTransfer">撤销跳槽</button>
          <router-link class="btn btn-ghost btn-sm" :to="`/va/${mine.icao}`" target="_blank">
            <Icon name="globe" :size="14" /> 对外主页
          </router-link>
          <router-link class="btn btn-primary btn-sm" :to="`/airlines/${mine.airline_id}`">进入航司</router-link>
          <button
            v-if="mine.role !== 'ceo'"
            class="btn btn-danger btn-sm"
            @click="leave"
          >{{ mine.status === 'pending' ? '撤回申请' : '退出航司' }}</button>
          <button v-if="mine.role === 'ceo'" class="btn btn-danger btn-sm" @click="disband">解散航司</button>
        </div>
      </div>
    </div>

    <!-- 创建表单 -->
    <div v-if="showCreate && canCreate" class="glass card" style="margin-bottom: 16px">
      <div class="card-title">{{ applicationRejected ? '重新申请虚拟航司' : '创建虚拟航司' }}</div>
      <div class="card-sub">
        {{ applicationRejected ? '上次申请已被驳回，修改资料后可重新提交审核。' : '创建需管理员审核；通过后你将成为该航司 CEO，可自行审批成员与管理航线' }}
      </div>
      <div v-if="createError" class="alert alert-err">{{ createError }}</div>
      <div class="grid grid-2">
        <div class="field">
          <label class="label">航司代码 <span style="color: var(--red)">*</span></label>
          <input v-model="form.icao" class="input input-icao" maxlength="4" placeholder="2/3 位，如 MU/CES" />
        </div>
        <div class="field">
          <label class="label">航司名称 <span style="color: var(--red)">*</span></label>
          <input v-model="form.name" class="input" maxlength="20" placeholder="如 中国东方航空" />
        </div>
      </div>
      <div class="field">
        <label class="label">航司简介 <span class="optional">选填</span></label>
        <textarea v-model="form.description" class="textarea" rows="2" placeholder="介绍航司定位、主基地与运营风格…"></textarea>
      </div>
      <div class="field">
        <label class="label">航司 Logo <span class="optional">选填（从本地上传）</span></label>
        <LogoUploader v-model="form.logoUrl" :fallback="(form.icao || '').toUpperCase()" />
      </div>
      <button class="btn btn-primary" :disabled="creating" @click="create">
        {{ creating ? '提交中…' : applicationRejected ? '重新提交申请' : '提交创建申请' }}
      </button>
    </div>
    <div v-else-if="showCreate && mine" class="glass card" style="margin-bottom: 16px">
      <div class="card-title">暂时无法创建航司</div>
      <div class="card-sub" style="margin-bottom: 0">
        你当前是 {{ mine.icao }} {{ mine.name }} 的成员。每个账号同时只能拥有一家航司，
        请先<template v-if="mine.role !== 'ceo'">「退出航司」</template><template v-else>「解散航司」</template>，
        再创建新的航司。
      </div>
    </div>

    <!-- 航司列表 -->
    <div class="glass card">
      <div class="card-title">航司列表</div>
      <div class="card-sub">想换一家航司？点击「我要跳槽」，由对方 CEO 审批，通过前你仍是当前航司成员</div>
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else>
        <div v-for="a in airlines" :key="a.id" class="list-item">
          <div class="va-badge">
            <img v-if="a.logo_url" :src="a.logo_url" alt="" />
            <template v-else>{{ a.icao }}</template>
          </div>
          <div class="list-main">
            <div class="list-title">{{ a.name }} <span class="tag" style="margin-left: 6px">CEO：{{ a.ceo }}</span></div>
            <div class="list-sub">{{ a.description || '暂无简介' }}</div>
            <div class="list-sub">
              <Icon name="users" :size="12" /> {{ a.member_count }} 名成员 · {{ a.route_count }} 条航线
            </div>
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end">
            <router-link class="btn btn-ghost btn-sm" :to="`/airlines/${a.id}`">查看详情</router-link>

            <!-- 未加入任何航司：申请加入 -->
            <button
              v-if="actionFor(a) === 'join'"
              class="btn btn-primary btn-sm"
              :disabled="busyId === a.id"
              @click="join(a)"
            >{{ busyId === a.id ? '提交中…' : '申请加入' }}</button>

            <!-- 已在别家航司：我要跳槽 -->
            <button
              v-else-if="actionFor(a) === 'transfer'"
              class="btn btn-dark btn-sm"
              :disabled="busyId === a.id"
              @click="transfer(a)"
            ><Icon name="trending" :size="13" /> {{ busyId === a.id ? '提交中…' : '我要跳槽' }}</button>

            <!-- 跳槽审核中 -->
            <template v-else-if="actionFor(a) === 'transferring'">
              <span class="tag tag-orange" style="align-self: center">跳槽申请审核中</span>
              <button class="btn btn-ghost btn-sm" @click="cancelTransfer">撤销</button>
            </template>

            <span v-else-if="actionFor(a) === 'inside'" class="tag tag-green" style="align-self: center">你所在的航司</span>

            <span
              v-else-if="actionFor(a) === 'ceo'"
              class="tag tag-red"
              style="align-self: center"
              title="CEO 不能跳槽，请先解散航司或将职务移交"
            >CEO 无法跳槽</span>

            <span v-else-if="actionFor(a) === 'pending'" class="tag tag-orange" style="align-self: center">加入申请审核中</span>
          </div>
        </div>
        <div v-if="!airlines.length" class="empty">
          <div class="empty-icon"><Icon name="plane" :size="22" /></div>
          <div>还没有通过审核的航司</div>
          <button class="btn btn-primary btn-sm" @click="openCreate">创建航司</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.va-badge {
  width: 52px;
  height: 52px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: var(--blue);
  color: #fff;
  font-weight: 700;
  font-size: 13px;
  letter-spacing: 0.5px;
  overflow: hidden;
}
.va-badge img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
</style>
