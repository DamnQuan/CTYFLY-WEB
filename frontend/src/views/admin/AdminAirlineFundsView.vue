<script setup>
/**
 * 航司货币管理，2026-10-11 新增
 *
 * 航司余额，airlines.balance 是 PIREP 结算里发工资的钱 —— 余额为 0 时会员拿不到工资，
 * 用户会集中反映「没钱」。此前只能手工改 SQL，且没有统一口径。本页提供：
 *   总览，余额/成员/费率→ 批量发放基础金，运营中 / 全部 / 指定→ 单个发放或扣除 → 调整记录
 * 每次调整都同时写 airlines.balance 与 airline_ledger，收入/支出，并留管理审计。
 */
import { computed, onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { showToast } from '../../utils.js';
import Icon from '../../components/Icon.vue';
import SelectMenu from '../../components/SelectMenu.vue';

const loading = ref(false);
const data = ref({ airlines: [], summary: {}, recent: [] });

// 批量发放
const grant = ref({ amount: 3000, reason: '基础金发放', scope: 'approved' });
const granting = ref(false);

// 单个调整
const adjust = ref({ airlineId: null, amount: 0, reason: '' });
const adjusting = ref(false);

const airlines = computed(() => data.value.airlines || []);
const summary = computed(() => data.value.summary || {});
const recent = computed(() => data.value.recent || []);

/** 批量发放的预览：影响几家、合计多少 */
const grantTargets = computed(() => (
  grant.value.scope === 'all'
    ? airlines.value
    : airlines.value.filter((a) => a.status === 'approved')
));
const grantTotal = computed(() => (Number(grant.value.amount) || 0) * grantTargets.value.length);

const airlineOptions = computed(() => airlines.value.map((a) => ({
  value: a.id,
  label: `${a.name}，余额 ${a.balance.toLocaleString()}`,
})));

const scopeOptions = [
  { value: 'approved', label: '运营中的航司' },
  { value: 'all', label: '全部航司，含待审核' },
];

function money(n) {
  return Number(n || 0).toLocaleString();
}

async function load() {
  loading.value = true;
  try {
    data.value = await api.get('/api/admin/airlines/funds');
    if (adjust.value.airlineId === null && airlines.value.length) {
      adjust.value.airlineId = airlines.value[0].id;
    }
  } catch (err) {
    showToast(err.message);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function submitGrant() {
  const amount = Number(grant.value.amount);
  if (!amount || amount <= 0) return showToast('请填写发放金额');
  const n = grantTargets.value.length;
  if (!n) return showToast('没有符合条件的航司');
  if (!window.confirm(`将向 ${n} 家航司各发放 ${money(amount)}，合计 ${money(amount * n)}。确认发放？`)) return;
  granting.value = true;
  try {
    const r = await api.post('/api/admin/airlines/funds/grant', {
      amount,
      reason: grant.value.reason.trim(),
      scope: grant.value.scope,
    });
    showToast(r.message || '发放完成');
    await load();
  } catch (err) {
    showToast(err.message);
  } finally {
    granting.value = false;
  }
}

async function submitAdjust() {
  const amount = Number(adjust.value.amount);
  if (!amount) return showToast('请填写调整金额，正数发放，负数扣除');
  if (adjust.value.airlineId === null) return showToast('请选择航司');
  const target = airlines.value.find((a) => a.id === adjust.value.airlineId);
  if (!window.confirm(`确认将「${target?.name || adjust.value.airlineId}」余额调整 ${amount > 0 ? '+' : ''}${money(amount)}？`)) return;
  adjusting.value = true;
  try {
    const r = await api.post('/api/admin/airlines/funds/adjust', {
      airlineId: adjust.value.airlineId,
      amount,
      reason: adjust.value.reason.trim(),
    });
    showToast(r.message || '已调整');
    adjust.value = { airlineId: adjust.value.airlineId, amount: 0, reason: '' };
    await load();
  } catch (err) {
    showToast(err.message);
  } finally {
    adjusting.value = false;
  }
}

function statusLabel(s) {
  return { approved: '运营中', pending: '待审核', rejected: '未通过', closed: '已关闭' }[s] || s;
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>航司货币管理</h1>
        <p class="page-desc">
          航司余额用于 PIREP 结算发放工资，余额为 0 时会员拿不到工资。此处可批量发放基础金、
          对单个航司发放或扣除，并查看最近调整记录；每次调整都会写入航司账本，收入/支出与管理审计。
        </p>
      </div>
      <button class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
        <Icon name="trending" :size="14" /> 刷新
      </button>
    </div>

    <div class="grid grid-4" style="margin-bottom: 16px">
      <div class="stat">
        <div class="stat-num">{{ summary.count || 0 }}</div>
        <div class="stat-label">航司总数，运营中 {{ summary.approved || 0 }}</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ money(summary.totalBalance) }}</div>
        <div class="stat-label">货币总量</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ summary.zeroBalance || 0 }}</div>
        <div class="stat-label">零余额航司</div>
      </div>
      <div class="stat">
        <div class="stat-num">{{ summary.members || 0 }}</div>
        <div class="stat-label">航司成员合计</div>
      </div>
    </div>

    <!-- 批量发放 -->
    <div class="glass card">
      <div class="card-title">批量发放基础金</div>
      <div class="grid grid-4">
        <div class="field">
          <label class="label">每家发放金额</label>
          <input v-model.number="grant.amount" class="input" type="number" min="1" placeholder="例如 3000" />
        </div>
        <div class="field">
          <label class="label">发放范围</label>
          <SelectMenu v-model="grant.scope" :options="scopeOptions" />
        </div>
        <div class="field" style="grid-column: span 2">
          <label class="label">原因，写入账本与审计</label>
          <input v-model="grant.reason" class="input" placeholder="例如 基础金发放 / 春节补贴" />
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: 14px">
        <button class="btn btn-primary btn-sm" :disabled="granting" @click="submitGrant">
          {{ granting ? '发放中…' : '立即发放' }}
        </button>
        <span style="font-size: 13px; color: var(--gray)">
          将影响 <strong>{{ grantTargets.length }}</strong> 家航司，合计发放
          <strong>{{ money(grantTotal) }}</strong>
        </span>
      </div>
    </div>

    <!-- 单个调整 -->
    <div class="glass card" style="margin-top: 16px">
      <div class="card-title">单个航司调整</div>
      <div class="grid grid-4">
        <div class="field">
          <label class="label">航司</label>
          <SelectMenu v-model="adjust.airlineId" :options="airlineOptions" placeholder="选择航司" />
        </div>
        <div class="field">
          <label class="label">金额，正=发放，负=扣除</label>
          <input v-model.number="adjust.amount" class="input" type="number" placeholder="例如 3000 或 -500" />
        </div>
        <div class="field" style="grid-column: span 2">
          <label class="label">原因</label>
          <input v-model="adjust.reason" class="input" placeholder="例如 误扣补偿" />
        </div>
      </div>
      <button class="btn btn-primary btn-sm" :disabled="adjusting" style="margin-top: 14px" @click="submitAdjust">
        {{ adjusting ? '提交中…' : '确认调整' }}
      </button>
    </div>

    <!-- 航司余额表 -->
    <div class="glass card" style="margin-top: 16px">
      <div class="card-title">航司余额</div>
      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="!airlines.length" style="padding: 14px 0; color: var(--gray); font-size: 13.5px">
        还没有任何虚拟航司。
      </div>
      <div v-else class="table-wrap" style="margin-top: 12px">
        <table class="table">
          <thead>
            <tr>
              <th>航司</th>
              <th>状态</th>
              <th>余额</th>
              <th>成员</th>
              <th>时薪 / 距离费率</th>
              <th>CEO</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in airlines" :key="a.id">
              <td>{{ a.name }}</td>
              <td>
                <span class="tag" :class="a.status === 'approved' ? 'tag-green' : 'tag'">
                  {{ statusLabel(a.status) }}
                </span>
              </td>
              <td>
                <strong :style="a.balance <= 0 ? 'color: var(--red)' : ''">{{ money(a.balance) }}</strong>
              </td>
              <td>{{ a.members }}</td>
              <td style="color: var(--gray)">{{ money(a.hourlyRate) }} / {{ money(a.distanceRate) }}</td>
              <td style="color: var(--gray)">{{ a.owner || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 调整记录 -->
    <div class="glass card" style="margin-top: 16px">
      <div class="card-title">最近调整记录，后台发起</div>
      <div v-if="!recent.length" style="font-size: 13px; color: var(--gray)">还没有后台调整记录。</div>
      <div v-else class="table-wrap" style="margin-top: 12px">
        <table class="table">
          <thead>
            <tr><th>时间</th><th>航司</th><th>金额</th><th>类型</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in recent" :key="r.id">
              <td style="color: var(--gray)">{{ r.createdAt }}</td>
              <td>{{ r.airline }}</td>
              <td>{{ r.type === 'revenue' ? '+' : '−' }}{{ money(r.amount) }}</td>
              <td>
                <span class="tag" :class="r.type === 'revenue' ? 'tag-blue' : 'tag-red'">
                  {{ r.type === 'revenue' ? '收入' : '支出' }}
                </span>
              </td>
              <td style="color: var(--gray)">{{ r.note }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
