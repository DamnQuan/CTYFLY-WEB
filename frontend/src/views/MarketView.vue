<script setup>
/**
 * 二手飞机市场
 *
 * 组件红线：
 * - 零原生控件：机型筛选、排序、购买方航司、机况全部用自研 SelectMenu；
 *   确认动作走 confirmModal，promptModal 用于改价，页面上没有 <select>/<input type="date">，
 *   也没有 alert/confirm/prompt。
 * - 滚动条隐藏：横向卡带与卡片内部滚动都隐藏原生滚动条，轨道仍可用滚轮/触摸/拖拽滚动。
 * - 拖拽用**纯 Pointer 事件**，pointerdown/move/up + setPointerCapture，鼠标与手指同一套代码；
 *   ResizeObserver 监听容器宽度：每屏卡片数与卡宽实时重算，窄屏只减少每屏数量、
 *   绝不把卡片压扁到看不清，卡宽下限 220px。
 */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { api } from '../api.js';
import { confirmModal } from '../modal.js';
import { showToast } from '../utils.js';
import { useVaStore } from '../stores/va.js';
import Icon from '../components/Icon.vue';
import SelectMenu from '../components/SelectMenu.vue';

const va = useVaStore();

const loading = ref(true);
const items = ref([]);
const page = ref(1);
const total = ref(0);
const pageSize = ref(12);
const feeRate = ref(5);
const myAirlines = ref([]);
const aircraftCounts = ref([]);
const my = ref({ listings: [], purchases: [], fleet: [] });

const aircraftFilter = ref('ALL');
const sortKey = ref('new');
const buying = ref(false);
const buyTarget = ref(null);
const buyAirline = ref('');
const sellOpen = ref(false);
const sellForm = reactive({ fleetId: '', price: '', conditionPct: 90, description: '' });

/* ---------- 自研下拉的选项 ---------- */
const aircraftOptions = computed(() => [
  { value: 'ALL', label: '全部机型' },
  ...aircraftCounts.value.map((c) => ({
    value: c.aircraft,
    label: `${c.aircraft}（在售 ${c.count}）`,
  })),
]);
const sortOptions = [
  { value: 'new', label: '最新挂牌' },
  { value: 'price_asc', label: '价格从低到高' },
  { value: 'price_desc', label: '价格从高到低' },
  { value: 'condition', label: '机况优先' },
];
const conditionOptions = [
  { value: 95, label: '95% · 近乎全新' },
  { value: 90, label: '90% · 良好' },
  { value: 80, label: '80% · 一般' },
  { value: 70, label: '70% · 需检修' },
  { value: 60, label: '60% · 退役边缘' },
];
const ceoAirlines = computed(() => myAirlines.value.filter((a) => a.role === 'ceo'));
const airlineOptions = computed(() =>
  ceoAirlines.value.map((a) => ({ value: a.id, label: `${a.name}（${a.icao}） · 余额 ${a.balance}` })),
);
const fleetOptions = computed(() =>
  my.value.fleet.map((f) => ({ value: f.id, label: `${f.aircraft} · ${f.reg} · 位于 ${f.location || '未知'}` })),
);

/* ---------- 数据加载 ---------- */
async function load() {
  loading.value = true;
  try {
    const qs = new URLSearchParams({ page: String(page.value), sort: sortKey.value });
    if (aircraftFilter.value !== 'ALL') qs.set('aircraft', aircraftFilter.value);
    const data = await api.get(`/api/market?${qs.toString()}`);
    items.value = data.items || [];
    total.value = data.total || 0;
    pageSize.value = data.pageSize || 12;
    feeRate.value = data.feeRate || 5;
    myAirlines.value = data.myAirlines || [];
    aircraftCounts.value = data.aircraftCounts || [];
    if (myAirlines.value.length) {
      const mine = await api.get('/api/market/my');
      my.value = {
        listings: mine.listings || [],
        purchases: mine.purchases || [],
        fleet: mine.fleet || [],
      };
    }
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}

onMounted(async () => {
  await va.fetch();
  await load();
  measureRail();
  ro = new ResizeObserver(measureRail);
  if (railEl.value) ro.observe(railEl.value);
});
onUnmounted(() => ro?.disconnect());

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)));
const featured = computed(() => items.value.slice(0, 8));

function fmt(n) {
  return Number(n || 0).toLocaleString('zh-CN');
}

/* ---------- 卡带：Pointer 拖拽 + ResizeObserver 防压扁 ---------- */
const railEl = ref(null);
const cardWidth = ref(260);
let ro = null;
const drag = { active: false, startX: 0, startLeft: 0, moved: false };

function measureRail() {
  const el = railEl.value;
  if (!el) return;
  const gap = 14;
  const w = el.clientWidth || 0;
  // 至少 240px 才放一张：屏幕再窄也不压扁卡片，宁可一屏一张
  const perView = Math.max(1, Math.min(4, Math.floor((w + gap) / (240 + gap))));
  cardWidth.value = Math.max(220, Math.floor((w - gap * (perView - 1)) / perView));
}

function onPointerDown(e) {
  if (e.button !== undefined && e.button !== 0) return;
  const el = railEl.value;
  if (!el) return;
  drag.active = true;
  drag.startX = e.clientX;
  drag.startLeft = el.scrollLeft;
  drag.moved = false;
  try { el.setPointerCapture(e.pointerId); } catch { /* 老浏览器无捕获能力：退化为普通拖动 */ }
  el.classList.add('dragging');
}
function onPointerMove(e) {
  if (!drag.active) return;
  const el = railEl.value;
  if (!el) return;
  const dx = e.clientX - drag.startX;
  if (Math.abs(dx) > 4) drag.moved = true;
  el.scrollLeft = drag.startLeft - dx;
}
function onPointerUp(e) {
  if (!drag.active) return;
  drag.active = false;
  const el = railEl.value;
  if (!el) return;
  try { el.releasePointerCapture(e.pointerId); } catch { /* 同上 */ }
  el.classList.remove('dragging');
}

/* ---------- 买入 ---------- */
function openBuy(item) {
  if (drag.moved) return;
  if (!myAirlines.value.length) {
    showToast('请先加入一家虚拟航司才能购买飞机');
    return;
  }
  if (!ceoAirlines.value.length) {
    showToast('只有航司 CEO 可以买入飞机');
    return;
  }
  buyTarget.value = item;
  buyAirline.value = ceoAirlines.value[0].id;
}

async function confirmBuy() {
  const item = buyTarget.value;
  if (!item || !buyAirline.value) return;
  const airline = myAirlines.value.find((a) => a.id === buyAirline.value);
  const ok = await confirmModal({
    title: '确认购买',
    message: `确定要以 ${fmt(item.price)} 买入 ${item.aircraft_name || item.aircraft}（注册号 ${item.reg}）吗？将从「${airline?.name || ''}」余额扣除，手续费 ${feeRate.value}% 由卖家承担。`,
    confirmText: '确认买入',
  });
  if (!ok) return;
  buying.value = true;
  try {
    const data = await api.post(`/api/market/${item.id}/buy`, { airlineId: buyAirline.value });
    showToast(data.message || '成交成功');
    buyTarget.value = null;
    await load();
  } catch (err) {
    showToast(err.message);
  }
  buying.value = false;
}

/* ---------- 挂牌卖出 ---------- */
function openSell() {
  sellForm.fleetId = my.value.fleet[0]?.id ?? '';
  sellForm.price = '';
  sellForm.conditionPct = 90;
  sellForm.description = '';
  sellOpen.value = true;
}

async function doSell() {
  const aid = ceoAirlines.value[0]?.id;
  if (!aid) {
    showToast('只有航司 CEO 可以挂牌出售飞机');
    return;
  }
  if (!sellForm.fleetId) {
    showToast('请选择要出售的飞机');
    return;
  }
  const price = Number(String(sellForm.price).replace(/[^\d]/g, ''));
  if (!price) {
    showToast('请填写挂牌价格');
    return;
  }
  const ok = await confirmModal({
    title: '确认挂牌',
    message: `确定要以 ${fmt(price)} 挂牌吗？成交后平台收取 ${feeRate.value}% 手续费，挂牌期间该飞机不可签派。`,
    confirmText: '确认挂牌',
  });
  if (!ok) return;
  try {
    const data = await api.post('/api/market/list', {
      airlineId: aid,
      fleetId: sellForm.fleetId,
      price,
      conditionPct: sellForm.conditionPct,
      description: sellForm.description,
    });
    showToast(data.message || '已挂牌');
    sellOpen.value = false;
    await load();
  } catch (err) {
    showToast(err.message);
  }
}

async function cancelListing(row) {
  const ok = await confirmModal({
    title: '下架挂牌',
    message: `确定要下架 ${row.aircraft} ${row.reg} 吗？下架后飞机恢复可签派。`,
    danger: true,
    confirmText: '确认下架',
  });
  if (!ok) return;
  try {
    const data = await api.post(`/api/market/${row.id}/cancel`);
    showToast(data.message || '已下架');
    await load();
  } catch (err) {
    showToast(err.message);
  }
}

async function changePage(delta) {
  const next = Math.min(totalPages.value, Math.max(1, page.value + delta));
  if (next === page.value) return;
  page.value = next;
  await load();
}

function statusTag(s) {
  if (s === 'listed') return { text: '在售', cls: 'tag-green' };
  if (s === 'sold') return { text: '已成交', cls: 'tag-blue' };
  return { text: '已下架', cls: 'tag-orange' };
}
</script>

<template>
  <div class="page" style="max-width: clamp(760px, 62vw, 1180px)">
    <div class="page-header">
      <div class="page-title">二手飞机市场</div>
      <div class="page-desc">
        航司之间整机转让 · 成交手续费 {{ feeRate }}% 由卖家承担 · 买家实付即挂牌价
        <template v-if="myAirlines.length">
          · 我的航司余额：
          <b v-for="a in myAirlines" :key="a.id" style="margin-left: 4px">{{ a.name }} {{ fmt(a.balance) }}</b>
        </template>
      </div>
    </div>

    <div class="glass card">
      <div class="market-toolbar">
        <div class="market-filter">
          <span class="label" style="margin: 0 6px 0 0">机型</span>
          <SelectMenu v-model="aircraftFilter" :options="aircraftOptions" />
        </div>
        <div class="market-filter">
          <span class="label" style="margin: 0 6px 0 0">排序</span>
          <SelectMenu v-model="sortKey" :options="sortOptions" />
        </div>
        <button class="btn btn-ghost btn-sm" @click="load">刷新</button>
        <button
          v-if="ceoAirlines.length" class="btn btn-primary btn-sm"
          :disabled="!my.fleet.length" @click="openSell"
        >出售飞机</button>
      </div>
      <div v-if="ceoAirlines.length && !my.fleet.length" class="card-sub" style="margin: 8px 0 0">
        本航司当前没有可用且未挂牌的飞机，签派中的飞机需先完成飞行报告才能挂牌。
      </div>
    </div>

    <!-- 精选卡带：纯 Pointer 拖拽 + ResizeObserver 防压扁 -->
    <div class="glass card" style="margin-top: 16px">
      <div class="card-title"><Icon name="shop" :size="16" /> 精选在售</div>
      <div class="card-sub">按住卡片左右拖动浏览，触屏同样可用；卡片宽度随容器实时重算，窄屏不会压扁</div>
      <div
        ref="railEl" class="market-rail" :style="{ '--card-w': cardWidth + 'px' }"
        @pointerdown="onPointerDown" @pointermove="onPointerMove"
        @pointerup="onPointerUp" @pointercancel="onPointerUp" @pointerleave="onPointerUp"
      >
        <div v-if="!featured.length" class="card-sub" style="margin: 0">暂无在售飞机</div>
        <article
          v-for="item in featured" :key="'f' + item.id" class="market-card"
          :class="{ picked: buyTarget && buyTarget.id === item.id }"
          @click="openBuy(item)"
        >
          <div class="mc-head">
            <span class="tag" :class="item.condition_pct >= 90 ? 'tag-green' : 'tag-orange'">
              机况 {{ item.condition_pct }}%
            </span>
            <span class="mc-reg">{{ item.reg }}</span>
          </div>
          <div class="mc-name">{{ item.aircraft_name || item.aircraft }}</div>
          <div class="mc-meta">{{ item.aircraft }} · {{ item.seller_airline_name }}（{{ item.seller_icao }}）</div>
          <div class="mc-meta">位于 {{ item.location || '未知' }} · 挂牌 {{ item.created_at?.slice(0, 10) }}</div>
          <div class="mc-price"><Icon name="diamond" :size="14" /> {{ fmt(item.price) }}</div>
        </article>
      </div>
    </div>

    <!-- 购买面板，自研下拉选购买方航司，confirmModal 二次确认-->
    <div v-if="buyTarget" class="glass card market-buy" style="margin-top: 16px">
      <div class="card-title"><Icon name="plane" :size="16" /> 买入 {{ buyTarget.aircraft_name || buyTarget.aircraft }} · {{ buyTarget.reg }}</div>
      <div class="card-sub">
        挂牌价 {{ fmt(buyTarget.price) }} · 手续费 {{ feeRate }}%，{{ fmt(Math.floor(buyTarget.price * feeRate / 100)) }}
        由卖家承担 · 卖家 {{ buyTarget.seller_airline_name }}
      </div>
      <div class="market-buy-row">
        <div style="flex: 1; min-width: 220px">
          <div class="label">使用哪家航司购买</div>
          <SelectMenu v-model="buyAirline" :options="airlineOptions" />
        </div>
        <button class="btn btn-primary btn-sm" :disabled="buying" @click="confirmBuy">
          {{ buying ? '成交中…' : '确认买入' }}
        </button>
        <button class="btn btn-ghost btn-sm" @click="buyTarget = null">取消</button>
      </div>
    </div>

    <!-- 全部在售 -->
    <div class="glass card" style="margin-top: 16px">
      <div class="card-title"><Icon name="trending" :size="16" /> 全部在售（{{ total }}）</div>
      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="!items.length" class="empty">
        <div class="empty-icon"><Icon name="shop" :size="22" /></div>
        <div>暂无符合条件的在售飞机，可调整筛选条件</div>
      </div>
      <div v-else class="market-list">
        <div v-for="item in items" :key="item.id" class="list-item">
          <div class="list-main">
            <div class="list-title">
              <span class="tag" :class="item.condition_pct >= 90 ? 'tag-green' : 'tag-orange'" style="margin-right: 8px">
                {{ item.condition_pct }}%
              </span>
              {{ item.aircraft_name || item.aircraft }} · {{ item.reg }}
            </div>
            <div class="list-sub">
              {{ item.aircraft }} · 卖家 {{ item.seller_airline_name }}（{{ item.seller_icao }}）
              · 位于 {{ item.location || '未知' }} · 挂牌 {{ item.created_at?.slice(0, 16) }}
            </div>
            <div v-if="item.description" class="list-sub" style="opacity: .8">{{ item.description }}</div>
          </div>
          <div class="market-price">
            <b>{{ fmt(item.price) }}</b>
            <button class="btn btn-primary btn-sm" @click="openBuy(item)">购买</button>
          </div>
        </div>
      </div>
      <div v-if="totalPages > 1" class="market-pager">
        <button class="btn btn-ghost btn-sm" :disabled="page <= 1" @click="changePage(-1)">上一页</button>
        <span class="card-sub" style="margin: 0">{{ page }} / {{ totalPages }}</span>
        <button class="btn btn-ghost btn-sm" :disabled="page >= totalPages" @click="changePage(1)">下一页</button>
      </div>
    </div>

    <!-- 出售面板：机型用自研 SelectMenu，替代原生 <select>，价格用普通文本框，只收数字-->
    <div v-if="sellOpen" class="glass card" style="margin-top: 16px">
      <div class="card-title"><Icon name="key" :size="16" /> 出售飞机</div>
      <div class="field">
        <div class="label">选择飞机</div>
        <SelectMenu v-model="sellForm.fleetId" :options="fleetOptions" placeholder="请选择本航司可用飞机" />
      </div>
      <div class="field">
        <div class="label">挂牌价（游戏币，10% ~ 150% 目录价）</div>
        <input v-model="sellForm.price" class="input" inputmode="numeric" placeholder="例如 500000" maxlength="9" />
      </div>
      <div class="field">
        <div class="label">机况</div>
        <SelectMenu v-model="sellForm.conditionPct" :options="conditionOptions" />
      </div>
      <div class="field">
        <div class="label">挂牌说明（可选）</div>
        <input v-model="sellForm.description" class="input" maxlength="200" placeholder="如：定期检修完毕，可立即投入运营" />
      </div>
      <div class="modal-actions">
        <button class="btn btn-ghost" @click.prevent="sellOpen = false">取消</button>
        <button class="btn btn-primary" @click.prevent="doSell">确认挂牌</button>
      </div>
    </div>

    <!-- 我的挂牌 / 买入记录 -->
    <div v-if="myAirlines.length" class="glass card" style="margin-top: 16px">
      <div class="card-title"><Icon name="file" :size="16" /> 我的航司交易</div>
      <div v-if="!my.listings.length" class="card-sub" style="margin: 0">暂无挂牌记录</div>
      <div v-for="row in my.listings" :key="'m' + row.id" class="list-item">
        <div class="list-main">
          <div class="list-title">
            <span class="tag" :class="statusTag(row.status).cls" style="margin-right: 8px">{{ statusTag(row.status).text }}</span>
            {{ row.aircraft }} · {{ row.reg }}
          </div>
          <div class="list-sub">
            挂牌 {{ fmt(row.price) }} · {{ row.created_at?.slice(0, 16) }}
            <template v-if="row.status === 'sold'">
              · 成交 {{ fmt(row.sold_price) }} · 到手 {{ fmt(row.sold_price - row.fee) }}
            </template>
          </div>
        </div>
        <button v-if="row.status === 'listed'" class="btn btn-ghost btn-sm" @click="cancelListing(row)">下架</button>
      </div>
      <div v-if="my.purchases.length" class="side-section" style="margin-top: 14px">买入记录</div>
      <div v-for="t in my.purchases" :key="'t' + t.id" class="list-item">
        <div class="list-main">
          <div class="list-title">{{ t.aircraft }} · {{ t.reg }}</div>
          <div class="list-sub">成交 {{ fmt(t.price) }} · {{ t.created_at?.slice(0, 16) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.market-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.market-filter { display: flex; align-items: center; gap: 6px; min-width: 190px; }
.market-filter :deep(.sm) { width: 170px; }

/* 卡带：隐藏原生滚动条，轨道仍可拖动/滚轮/触摸滚动*/
.market-rail {
  display: flex;
  gap: 14px;
  overflow-x: auto;
  padding: 4px 2px 8px;
  cursor: grab;
  touch-action: pan-y;            /* 横向手势交给拖拽，纵向仍可翻页 */
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.market-rail::-webkit-scrollbar { display: none; }
.market-rail.dragging { cursor: grabbing; }
.market-rail.dragging .market-card { pointer-events: none; }

.market-card {
  flex: 0 0 var(--card-w, 260px);
  width: var(--card-w, 260px);
  box-sizing: border-box;
  padding: 14px 16px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
  background: var(--surface);
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
  user-select: none;
}
.market-card:hover { transform: translateY(-2px); border-color: var(--blue); }
.market-card.picked { border-color: var(--blue); box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.14); }
.mc-head { display: flex; align-items: center; justify-content: space-between; }
.mc-reg { font-size: 12px; color: var(--text-2); letter-spacing: 0.5px; }
.mc-name { font-size: 15px; font-weight: 600; margin-top: 8px; }
.mc-meta { font-size: 12px; color: var(--text-2); margin-top: 4px; line-height: 1.5; }
.mc-price {
  display: flex; align-items: center; gap: 6px;
  margin-top: 10px; font-size: 17px; font-weight: 700; color: var(--blue);
}

.market-buy-row { display: flex; align-items: flex-end; gap: 10px; flex-wrap: wrap; }
.market-list { display: flex; flex-direction: column; }
.market-price { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.market-pager { display: flex; align-items: center; justify-content: center; gap: 14px; margin-top: 12px; }
</style>
