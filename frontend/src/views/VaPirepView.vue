<script setup>
import { ref, onMounted, computed } from 'vue';
import { useRoute } from 'vue-router';
import { api } from '../api.js';
import { localDate, showToast } from '../utils.js';
import { useVaStore } from '../stores/va.js';
import Icon from '../components/Icon.vue';
import SelectMenu from '../components/SelectMenu.vue';
import DatePicker from '../components/DatePicker.vue';

const va = useVaStore();
const route = useRoute();

const routes = ref([]);
const reportableDispatches = ref([]);   // 已完成起飞/落地上报、可提交报告的签派单
const loading = ref(true);
const submitting = ref(false);
const lastScore = ref(null);

const form = ref({ dispatchId: '', routeId: '', aircraft: '', hours: '', flightDate: '', notes: '' });

const today = () => localDate();   // 本地时区日期，避免 UTC 偏移差一天
const selectedDispatch = computed(() => reportableDispatches.value.find((d) => d.id === Number(form.value.dispatchId)) || null);
const dispatchOptions = computed(() => reportableDispatches.value.map((d) => ({
  value: String(d.id),
  label: `${d.flight_no || '—'} ${d.dep} → ${d.arr}，${d.aircraft || '机型不限'}`,
})));
const routeOptions = computed(() => routes.value.map((r) => ({
  value: String(r.id),
  label: `${r.flight_no || '—'} ${r.dep} → ${r.arr}，工资 ${r.base_salary}`,
})));
const selectedRoute = computed(() => routes.value.find((r) => r.id === Number(form.value.routeId)) || null);
/* 包机/转场签派没有关联航线，route_id 为 NULL，后端要求这类报告 routeId=0 并自动匹配溢价结算*/
const isCharterDispatch = computed(() => ['charter', 'ferry'].includes(selectedDispatch.value?.kind));
const catalog = ref({});

/* 预计结算，与后端 review_report 同一公式；旅客数优先用签派单，否则按机型典型客座率 80% 估算；
   货运收入取签派货载，无签派不计*/
const est = computed(() => {
  const r = selectedRoute.value;
  if (!r) return null;
  const rate = va.membership?.hourlyRate ?? 100;
  const drate = va.membership?.distanceRate ?? 1;
  const hours = Number(form.value.hours) || 0;
  const dist = r.distance_nm || 0;
  const wage = Math.round((r.base_salary || 0) + hours * rate + dist * drate);
  const spec = catalog.value[String(r.aircraft || '').trim().toUpperCase()];
  const pax = selectedDispatch.value?.pax || Math.round((spec?.pax || 0) * 0.8);
  const cargo = selectedDispatch.value?.cargo || 0;
  const paxRev = Math.round(pax * dist * 0.6);
  const cargoRev = Math.round(cargo * dist * 0.002);
  return {
    wage, pax, cargo, paxRev, cargoRev,
    revenue: paxRev + cargoRev, net: paxRev + cargoRev - wage,
    hasPax: !!selectedDispatch.value?.pax, hasCargo: cargo > 0,
  };
});

function applyDispatch() {
  const d = selectedDispatch.value;
  if (d) {
    // 包机/转场无关联航线：清空选择，提交时 routeId=0
    form.value.routeId = ['charter', 'ferry'].includes(d.kind) ? '' : String(d.route_id || '');
    form.value.aircraft = d.aircraft || '';
  }
}

async function loadAll() {
  const aid = va.membership.airlineId;
  const [r, d, f] = await Promise.all([
    api.get(`/api/airlines/${aid}/routes`),
    api.get(`/api/airlines/${aid}/dispatches?scope=mine`),
    api.get(`/api/airlines/${aid}/fleet`),
  ]);
  routes.value = r.routes || [];
  reportableDispatches.value = (d.dispatches || []).filter((x) => x.status === 'open' && x.flight_state === 'landed');
  catalog.value = f.catalog || {};
  const pre = Number(route.query.dispatchId) || 0;
  if (pre && reportableDispatches.value.some((x) => x.id === pre)) {
    form.value.dispatchId = String(pre);
    applyDispatch();
  }
}

onMounted(async () => {
  await va.fetch();
  if (!va.joined) {
    loading.value = false;
    return;
  }
  form.value.flightDate = today();
  try {
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});

async function submit() {
  if (!form.value.dispatchId) {
    showToast('请选择已落地的签派单，先在签派页完成起飞/落地上报');
    return;
  }
  if (!isCharterDispatch.value && !form.value.routeId) {
    showToast('请选择航线');
    return;
  }
  if (!(Number(form.value.hours) > 0)) {
    showToast('请填写飞行时长');
    return;
  }
  submitting.value = true;
  try {
    const data = await api.post(`/api/airlines/${va.membership.airlineId}/reports`, {
      // 包机/转场报告不带航线，后端要求 routeId=0，自动按任务类型溢价/补贴结算
      routeId: isCharterDispatch.value ? 0 : Number(form.value.routeId),
      aircraft: form.value.aircraft,
      hours: Number(form.value.hours),
      flightDate: form.value.flightDate,
      notes: form.value.notes,
      dispatchId: Number(form.value.dispatchId),
    });
    showToast(data.message || '已提交');
    lastScore.value = data.score ?? null;
    form.value = { dispatchId: '', routeId: '', aircraft: '', hours: '', flightDate: today(), notes: '' };
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  submitting.value = false;
}
</script>

<template>
  <div class="page" style="max-width: clamp(680px, 52vw, 980px)">
    <div class="page-header">
      <div class="page-title">提交飞行报告</div>
      <div class="page-desc">报告必须关联已落地的签派单，平台 ACARS 核验；选择后自动带出航线与机型</div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!va.joined" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="plane" :size="22" /></div>
        <div>你还没有加入航司</div>
        <router-link class="btn btn-primary btn-sm" to="/airlines">去航司列表加入</router-link>
      </div>
    </div>

    <div v-else class="glass card">
      <div class="field">
        <label class="label">关联签派单，必选 · 需已完成起飞/落地上报</label>
        <SelectMenu
          v-model="form.dispatchId" :options="dispatchOptions"
          placeholder="选择已落地的签派单" @update:model-value="applyDispatch"
        />
        <div v-if="reportableDispatches.length === 0" class="card-sub" style="margin-top: 6px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap">
          <span>暂无已落地的签派单——先去签派页生成签派单并完成「起飞/落地」上报</span>
          <router-link to="/va/dispatch" class="btn btn-primary btn-sm">去飞行签派</router-link>
        </div>
        <div v-else-if="selectedDispatch" class="card-sub" style="margin-top: 6px">
          时间线：起飞 {{ selectedDispatch.flight_state === 'landed' ? '已记录' : '未记录' }} ·
          平台 ACARS 将自动核验时长/航线/时间线一致性，≥80 分自动发薪
        </div>
      </div>
      <!-- 包机/转场签派无关联航线，不渲染航线选择；正常签派保持航线选择 -->
      <div v-if="!isCharterDispatch" class="field">
        <label class="label">航线</label>
        <SelectMenu
          v-model="form.routeId" :options="routeOptions"
          placeholder="选择本航司的航线"
        />
      </div>
      <div v-else class="field">
        <label class="label">航线</label>
        <div class="card-sub">包机 / 转场任务无关联航线，报告将按任务类型自动结算，包机 1.5× 溢价，转场计调机补贴</div>
      </div>
      <div class="input-row">
        <div class="field" style="flex: 1">
          <label class="label">机型</label>
          <input v-model="form.aircraft" class="input" placeholder="如 A320 / B738" maxlength="16" />
        </div>
        <div class="field" style="flex: 1">
          <label class="label">飞行时长，小时</label>
          <input v-model="form.hours" class="input" type="number" step="0.1" min="0.1" max="24" placeholder="如 2.5" />
        </div>
      </div>
      <div class="field">
        <label class="label">飞行日期</label>
        <DatePicker v-model="form.flightDate" mode="date" placeholder="选择飞行日期" />
      </div>
      <div class="field">
        <label class="label">备注</label>
        <textarea v-model="form.notes" class="textarea" rows="2" placeholder="航路、特殊情况等，可空" maxlength="200"></textarea>
      </div>
      <button class="btn btn-primary" :disabled="submitting" @click="submit">
        {{ submitting ? '提交中…' : '提交飞行报告' }}
      </button>

      <!-- 预计结算，随选择实时更新-->
      <div v-if="est" class="card-sub" style="margin-top: 14px; line-height: 1.9">
        <b>预计结算公示</b><br />
        飞行工资 {{ est.wage.toLocaleString() }} = 底薪 {{ selectedRoute?.base_salary || 0 }}
        + {{ form.hours || 0 }}h × 时薪 {{ va.membership?.hourlyRate ?? 100 }}
        + {{ Math.round(selectedRoute?.distance_nm || 0) }}nm × 津贴 {{ va.membership?.distanceRate ?? 1 }}<br />
        公司运输收入 {{ est.revenue.toLocaleString() }} = 客运 {{ est.paxRev.toLocaleString() }}，{{ est.hasPax ? `签派旅客 ${est.pax}` : `无签派，按机型 80% 客座率估 ${est.pax} 客` }} × {{ Math.round(selectedRoute?.distance_nm || 0) }}nm × 0.6<template v-if="est.hasCargo"> + 货运 {{ est.cargoRev.toLocaleString() }}，{{ est.cargo }}kg × 航程 × 0.002</template>
        · 公司净 {{ est.net.toLocaleString() }}
      </div>
    </div>

    <!-- 结算规则公示 -->
    <div v-if="va.joined" class="glass card" style="margin-top: 16px">
      <div class="card-title"><Icon name="award" :size="16" /> 结算规则公示</div>
      <div class="list-sub" style="line-height: 1.9">
        <b>平台 ACARS 核验</b>：报告必须关联已落地的签派单；系统自动核验时长与时间线、航线一致性、起飞时间与提交频率，满分 100——≥80 分自动发薪，60-79 分转 CEO 复核，&lt;60 分自动拒绝。<br />
        <b>飞行员工资</b> = 航线底薪 + 飞行时长 × 时薪，CEO 在航司设置中调整+ 航程 × 里程津贴<br />
        <b>公司运输收入</b> = 旅客 × 航程 nm × 0.6，客运 + 货物 kg × 航程 × 0.002，货运<br />
        <b>公司净入</b> = 运输收入 − 飞行员工资，空载或亏损航段公司照付工资，可能为负<br />
        CEO 审核通过后工资立即入账；CEO 审本人报告单笔工资封顶 20,000。<br />
        载客与货载数以签派单为准；无签派时按机型典型客座率 80% 估算客运、不计货运。
      </div>
    </div>
  </div>
</template>
