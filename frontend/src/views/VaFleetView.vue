<script setup>
import { ref, computed, onMounted } from 'vue';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import { useVaStore } from '../stores/va.js';
import Icon from '../components/Icon.vue';

const va = useVaStore();
const fleet = ref([]);
const catalog = ref({});
const loading = ref(true);
const buying = ref('');
const mfrTab = ref('全部');
const ferryTarget = ref('');        // 正在转场的飞机 id
const ferryTo = ref('');            // 转场目的地 ICAO
const ferrying = ref(false);

async function loadAll() {
  const aid = va.membership.airlineId;
  const data = await api.get(`/api/airlines/${aid}/fleet`);
  fleet.value = data.fleet || [];
  catalog.value = data.catalog || {};
}

onMounted(async () => {
  await va.fetch();
  if (!va.joined) {
    loading.value = false;
    return;
  }
  try {
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});

const availableCount = computed(() => fleet.value.filter((f) => f.status === 'available').length);

const mfrs = computed(() => {
  const set = new Set(Object.values(catalog.value).map((s) => s.mfr));
  return ['全部', ...set];
});

const catalogGroups = computed(() => {
  const groups = {};
  for (const [key, s] of Object.entries(catalog.value)) {
    if (mfrTab.value !== '全部' && s.mfr !== mfrTab.value) continue;
    (groups[s.mfr] = groups[s.mfr] || []).push({ key, ...s });
  }
  // 组内按价格升序
  for (const k of Object.keys(groups)) groups[k].sort((a, b) => a.price - b.price);
  const order = ['中国商飞', '巴航工业', '空客', '波音'];
  return order.filter((m) => groups[m]).map((m) => ({ mfr: m, items: groups[m] }));
});

async function buy(key) {
  buying.value = key;
  try {
    const data = await api.post(`/api/airlines/${va.membership.airlineId}/fleet/purchase`, { aircraft: key });
    showToast(data.message || '购置成功');
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  buying.value = '';
}

function startFerry(f) {
  ferryTarget.value = f.id;
  ferryTo.value = '';
}

async function doFerry(f) {
  if (!ferryTo.value.trim()) { showToast('请填写目的地机场 ICAO'); return; }
  ferrying.value = true;
  try {
    const data = await api.post(`/api/airlines/${va.membership.airlineId}/fleet/${f.id}/ferry`, { to: ferryTo.value.trim().toUpperCase() });
    showToast(data.message || '转场任务已创建');
    ferryTarget.value = '';
    ferryTo.value = '';
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  ferrying.value = false;
}
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 56vw, 1100px)">
    <div class="page-header">
      <div class="page-title">机队管理</div>
      <div class="page-desc">
        公司机队与机型购置目录
        <template v-if="va.membership">
          · {{ va.membership.name }}（{{ va.membership.icao }}） · 在册 {{ fleet.length }} 架，可用 {{ availableCount }} 架
        </template>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!va.joined" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="plane" :size="22" /></div>
        <div>你还没有加入航司</div>
        <router-link class="btn btn-primary btn-sm" to="/airlines">去航司列表加入</router-link>
      </div>
    </div>

    <template v-else>
      <div class="glass card">
        <div class="card-title"><Icon name="wings" :size="16" /> 在册机队</div>
        <div class="card-sub" style="margin-bottom: 10px">
          飞机停在所属机场。签派要求飞机位于航线起飞机场，不在本场时先执行转场调机；调机不载客货，按距离发放调机补贴
        </div>
        <div v-if="!fleet.length" class="card-sub">机队为空</div>
        <div v-for="f in fleet" :key="f.id" class="list-item" style="flex-wrap: wrap">
          <div class="list-main">
            <div class="list-title">
              <span class="tag" :class="f.status === 'available' ? 'tag-green' : 'tag-orange'" style="margin-right: 8px">
                {{ f.status === 'available' ? '可用' : '签派中' }}
              </span>
              {{ catalog[f.aircraft]?.name || f.aircraft }} · {{ f.reg }}
            </div>
            <div class="list-sub">
              {{ f.aircraft }} · 位于 <b>{{ f.location || '未登记' }}</b> · 入册 {{ f.purchased_at }}
            </div>
            <!-- 转场：行内展开目的地输入 -->
            <div v-if="ferryTarget === f.id" style="display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap">
              <input
                v-model="ferryTo" class="input" style="max-width: 160px"
                placeholder="目的地 ICAO" maxlength="4" @keyup.enter="doFerry(f)"
              />
              <button class="btn btn-primary btn-sm" :disabled="ferrying" @click="doFerry(f)">
                {{ ferrying ? '创建中…' : '确认转场' }}
              </button>
              <button class="btn btn-ghost btn-sm" @click="ferryTarget = ''">取消</button>
            </div>
          </div>
          <button
            v-if="f.status === 'available'" class="btn btn-ghost btn-sm"
            @click="ferryTarget === f.id ? (ferryTarget = '') : startFerry(f)"
          >转场</button>
        </div>
      </div>

      <div class="glass card" style="margin-top: 16px">
        <div class="card-title" style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap">
          <Icon name="shop" :size="16" /> 机型购置目录
          <template v-if="va.isCEO">
            <span class="card-sub" style="margin: 0">从你的钱包扣款</span>
          </template>
        </div>
        <div class="card-sub" style="margin-bottom: 10px">
          规格与价格依据各厂商公开资料，ACAP 机场适配手册 / 价目表；
          价格按真实目录价等比换算，以 A320neo 目录价 $110.6M = 600,000 为基准，实际成交价通常低于目录价。
        </div>
        <div class="seg" style="margin-bottom: 14px">
          <button
            v-for="m in mfrs" :key="m"
            class="seg-btn" :class="{ on: mfrTab === m }"
            @click="mfrTab = m"
          >{{ m }}</button>
        </div>

        <div v-for="g in catalogGroups" :key="g.mfr" style="margin-bottom: 8px">
          <div class="side-section" style="margin-top: 4px">{{ g.mfr }}</div>
          <div v-for="s in g.items" :key="s.key" class="list-item">
            <div class="list-main">
              <div class="list-title">
                <span class="tag" style="background: var(--surface-strong); margin-right: 8px">{{ s.key }}</span>
                {{ s.name }}
              </div>
              <div class="list-sub">
                价格 {{ s.price.toLocaleString() }}
                · OEW {{ s.oew.toLocaleString() }}kg · MTOW {{ s.mtow.toLocaleString() }}kg
                · 最多 {{ s.pax }} 座
                <template v-if="s.suggestedHourly"> · 建议时薪 {{ s.suggestedHourly }}/h</template>
              </div>
              <div class="list-sub" style="opacity: 0.75">来源：{{ s.src }}</div>
            </div>
            <button
              v-if="va.isCEO" class="btn btn-primary btn-sm"
              :disabled="buying === s.key"
              @click="buy(s.key)"
            >{{ buying === s.key ? '购置中…' : '购置' }}</button>
          </div>
        </div>
        <div v-if="!va.isCEO" class="card-sub">仅 CEO 可购置飞机</div>
      </div>
    </template>
  </div>
</template>
