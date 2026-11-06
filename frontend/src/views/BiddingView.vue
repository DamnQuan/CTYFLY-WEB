<script setup>
/**
 * 航线竞标：出价即冻结航司资金，截止后统一结算
 *
 * 组件红线：金额输入用自研 promptModal，不是原生 prompt，确认走 confirmModal，
 * 页面没有任何 <select>/原生日期控件/原生弹窗。
 */
import { computed, onMounted, ref } from 'vue';
import { api } from '../api.js';
import { confirmModal, promptModal } from '../modal.js';
import { showToast } from '../utils.js';
import { useVaStore } from '../stores/va.js';
import Icon from '../components/Icon.vue';

const va = useVaStore();
const loading = ref(true);
const scope = ref('open');
const items = ref([]);
const myAirlines = ref([]);
const balances = ref({});
const busy = ref(0);

const myAirlineId = computed(() => va.membership?.airlineId || 0);
const myBalance = computed(() => balances.value[myAirlineId.value] ?? null);

async function load() {
  loading.value = true;
  try {
    const data = await api.get(`/api/bids/tenders?scope=${scope.value}`);
    items.value = data.items || [];
    myAirlines.value = data.myAirlines || [];
    balances.value = data.balances || {};
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}

onMounted(async () => {
  await va.fetch();
  await load();
});

function fmt(n) {
  return Number(n || 0).toLocaleString('zh-CN');
}

async function placeOffer(t) {
  if (!myAirlineId.value) {
    showToast('请先加入一家虚拟航司');
    return;
  }
  if (!va.isCEO) {
    showToast('只有航司 CEO 可以出价');
    return;
  }
  const floor = t.topOffer ? t.topOffer.amount + t.min_step : t.start_price;
  const input = await promptModal({
    title: `竞标 ${t.dep} - ${t.arr}`,
    message: `起拍 ${fmt(t.start_price)} · 当前最高 ${fmt(t.topOffer?.amount || 0)} · 最小加价 ${fmt(t.min_step)}。出价后资金立即冻结，未中标全额退回。`,
    inputPlaceholder: `至少 ${floor}`,
    confirmText: '确认出价',
  });
  if (input === null) return;
  const amount = Number(String(input).replace(/[^\d]/g, ''));
  if (!amount) {
    showToast('请输入有效金额');
    return;
  }
  const ok = await confirmModal({
    title: '确认出价',
    message: `将从「${va.membership.name}」余额冻结 ${fmt(amount)}，确定要出价吗？`,
    confirmText: '冻结并出价',
  });
  if (!ok) return;
  busy.value = t.id;
  try {
    const data = await api.post(`/api/bids/tenders/${t.id}/offers`, {
      airlineId: myAirlineId.value,
      amount,
    });
    showToast(data.message || '出价成功');
    await load();
  } catch (err) {
    showToast(err.message);
  }
  busy.value = 0;
}

async function withdraw(t) {
  if (!t.myOffer) return;
  const ok = await confirmModal({
    title: '撤回出价',
    message: `撤回后冻结的 ${fmt(t.myOffer.amount)} 将退回航司余额。确定要撤标吗？`,
    danger: true,
    confirmText: '确认撤标',
  });
  if (!ok) return;
  try {
    const data = await api.post(`/api/bids/offers/${t.myOffer.id}/withdraw`);
    showToast(data.message || '已撤标');
    await load();
  } catch (err) {
    showToast(err.message);
  }
}

async function settle() {
  const ok = await confirmModal({
    title: '结算到期招标',
    message: '将结算所有已过截止时间的招标：最高价中标并分配航线，其余出价全额退款。确定要继续吗？',
    confirmText: '立即结算',
  });
  if (!ok) return;
  try {
    const data = await api.post('/api/bids/settle');
    showToast(data.message || '结算完成');
    await load();
  } catch (err) {
    showToast(err.message);
  }
}

async function switchScope(s) {
  scope.value = s;
  await load();
}
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 56vw, 1080px)">
    <div class="page-header">
      <div class="page-title">航线竞标</div>
      <div class="page-desc">
        平台放出的待竞争航线，航司出价竞标 · 出价即冻结资金，截止后最高价中标，其余全额退回
        <template v-if="myAirlineId"> · 本航司余额 {{ myBalance === null ? '—' : fmt(myBalance) }}</template>
      </div>
    </div>

    <div class="glass card">
      <div class="bid-toolbar">
        <div class="seg">
          <button class="seg-btn" :class="{ on: scope === 'open' }" @click="switchScope('open')">在标</button>
          <button class="seg-btn" :class="{ on: scope === 'settled' }" @click="switchScope('settled')">已结算</button>
        </div>
        <button class="btn btn-ghost btn-sm" @click="load">刷新</button>
        <button class="btn btn-primary btn-sm" @click="settle">结算到期招标</button>
      </div>
      <div class="card-sub" style="margin: 10px 0 0">
        结算可重复点击，不会重复退款；只有已过截止时间的招标会被处理。
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!items.length" class="glass card" style="margin-top: 16px">
      <div class="empty">
        <div class="empty-icon"><Icon name="key" :size="22" /></div>
        <div>{{ scope === 'open' ? '暂无在标航线' : '暂无已结算的招标' }}</div>
      </div>
    </div>

    <div v-for="t in items" :key="t.id" class="glass card" style="margin-top: 16px">
      <div class="bid-head">
        <div>
          <div class="list-title" style="font-size: 17px">
            <Icon name="plane" :size="16" style="margin-right: 6px" />{{ t.dep }} — {{ t.arr }}
            <span class="tag" :class="t.status === 'open' ? 'tag-green' : 'tag-blue'" style="margin-left: 8px">
              {{ t.status === 'open' ? '在标' : '已结算' }}
            </span>
          </div>
          <div class="list-sub">
            {{ t.flight_no }} · 距离 {{ t.distance_nm ? Math.round(t.distance_nm) + ' NM' : '—' }}
            · 起拍 {{ fmt(t.start_price) }} · 最小加价 {{ fmt(t.min_step) }}
            · 出价 {{ t.offerCount }} 家
          </div>
          <div class="list-sub">
            截止 {{ t.closes_at }}
            <template v-if="t.status === 'open' && !t.canBid"> · 已过截止时间，可点击「结算」处理</template>
            <template v-if="t.status === 'settled'"> · 结算于 {{ t.settled_at }} · 成交 {{ fmt(t.settle_price) }}</template>
          </div>
        </div>
        <div class="bid-side">
          <div class="bid-top">
            当前最高
            <b>{{ fmt(t.topOffer?.amount || 0) }}</b>
            <span v-if="t.topOffer" class="card-sub" style="margin: 0">{{ t.topOffer.airline_name }}</span>
          </div>
          <div v-if="t.myOffer" class="bid-mine">
            我的出价
            <b>{{ fmt(t.myOffer.amount) }}</b>
            <span class="tag" :class="t.myOffer.status === 'won' ? 'tag-green' : 'tag-orange'" style="margin-left: 6px">
              {{ t.myOffer.status === 'won' ? '中标' : (t.myOffer.status === 'active' ? '冻结中' : t.myOffer.status) }}
            </span>
          </div>
          <div class="bid-actions">
            <button
              v-if="t.canBid" class="btn btn-primary btn-sm"
              :disabled="busy === t.id || !va.isCEO" @click="placeOffer(t)"
            >{{ t.myOffer ? '改价' : '出价' }}</button>
            <button
              v-if="t.canBid && t.myOffer" class="btn btn-ghost btn-sm" @click="withdraw(t)"
            >撤标</button>
            <span v-if="t.canBid && !va.isCEO" class="card-sub" style="margin: 0">仅 CEO 可出价</span>
          </div>
        </div>
      </div>
      <div v-if="t.status === 'settled' && t.winner_airline_id" class="bid-winner">
        中标航司：#{{ t.winner_airline_id }} · 成交价 {{ fmt(t.settle_price) }} · 航线已加入其航线网络
      </div>
    </div>
  </div>
</template>

<style scoped>
.bid-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.bid-head { display: flex; justify-content: space-between; gap: 18px; flex-wrap: wrap; }
.bid-side { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
.bid-top { font-size: 13px; color: var(--text-2); }
.bid-top b { font-size: 18px; color: var(--blue); margin-left: 6px; }
.bid-mine { font-size: 13px; color: var(--text-2); }
.bid-mine b { color: var(--text); margin-left: 6px; }
.bid-actions { display: flex; gap: 8px; align-items: center; }
.bid-winner {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface);
  font-size: 13px;
  color: var(--text-2);
}
</style>
