<script>
/* 油量估算请求序号，模块级：连续输入触发多次请求时，只有最后一次的响应允许写入*/
let fuelSeq = 0;
</script>

<script setup>
import { ref, onMounted, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { fmtTime, showToast } from '../utils.js';
import { useVaStore } from '../stores/va.js';
import { useAuthStore } from '../stores/auth.js';
import Icon from '../components/Icon.vue';
import SelectMenu from '../components/SelectMenu.vue';
import DatePicker from '../components/DatePicker.vue';

const va = useVaStore();
const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const routes = ref([]);
const dispatches = ref([]);
const fleet = ref([]);
const catalog = ref({});
const loading = ref(true);
const submitting = ref(false);

const form = ref({
  routeId: '', fleetId: '', captain: '', callsign: '', schedDep: '',
  pax: '', cargo: '', copilot: '', ci: '',
  depRwy: '', arrRwy: '', cruiseFl: '', fuelKg: '', alternate: '', remarks: '',
});

const selectedRoute = computed(() => routes.value.find((r) => r.id === Number(form.value.routeId)) || null);
const selectedFleet = computed(() => fleet.value.find((f) => f.id === Number(form.value.fleetId)) || null);
const availableFleet = computed(() => fleet.value.filter((f) => f.status === 'available'));
/* 运营地理：航线签派要求飞机位于航线起飞机场 */
const dispatchableFleet = computed(() => {
  const dep = selectedRoute.value?.dep || '';
  if (!dep) return availableFleet.value;
  return availableFleet.value.filter((f) => (f.location || '') === dep);
});
const spec = computed(() => catalog.value[selectedFleet.value?.aircraft] || null);
const payloadKg = computed(() => (Number(form.value.pax) || 0) * 95 + (Number(form.value.cargo) || 0));
const zfw = computed(() => (spec.value ? spec.value.oew + payloadKg.value : 0));
const tow = computed(() => (spec.value ? zfw.value + (Number(form.value.fuelKg) || 0) : 0));
const overMtow = computed(() => !!(spec.value && tow.value > spec.value.mtow));
const routeOptions = computed(() => routes.value.map((r) => ({
  value: String(r.id),
  label: `${r.flight_no || '—'} ${r.dep} → ${r.arr}，${r.aircraft || '机型不限'}`,
})));
const dispatchableOptions = computed(() => dispatchableFleet.value.map((f) => ({
  value: String(f.id),
  label: `${catalog.value[f.aircraft]?.name || f.aircraft} · ${f.reg}，位于 ${f.location || '?'}`,
})));
const depRunwayOptions = computed(() => depRunways.value.map((r) => ({ value: r, label: r })));
const arrRunwayOptions = computed(() => arrRunways.value.map((r) => ({ value: r, label: r })));
const charterFleetOptions = computed(() => charterFleet.value.map((f) => ({
  value: String(f.id),
  label: `${catalog.value[f.aircraft]?.name || f.aircraft} · ${f.reg}，位于 ${f.location || '?'}`,
})));
const depRunways = ref([]);
const plannedRoute = ref('');          // 自动规划的航路字符串
const planningRoute = ref(false);
const fuelEstimating = ref(false);
const fuelModel = ref('');             // 油量模型标注，OpenAP
const routeDistance = ref(0);
let fuelTimer = 0;
const arrRunways = ref([]);

async function loadRunways(icao) {
  if (!/^[A-Z0-9]{4}$/.test(icao || '')) return [];
  try {
    const data = await api.get(`/api/nav/runways/${icao}`);
    return (data.runways || []).map((r) => r.ident).filter(Boolean);
  } catch {
    return [];
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
  dispatches.value = d.dispatches || [];
  fleet.value = f.fleet || [];
  catalog.value = f.catalog || {};
  const pre = Number(route.query.routeId) || 0;
  if (pre && routes.value.some((x) => x.id === pre)) form.value.routeId = String(pre);
}

onMounted(async () => {
  await va.fetch();
  if (!va.joined) {
    loading.value = false;
    return;
  }
  // 机长默认当前登录用户，可改
  form.value.captain = auth.user?.username || '';
  try {
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});

async function onRouteChangeFull() {
  if (selectedRoute.value && !form.value.callsign) form.value.callsign = selectedRoute.value.flight_no || '';
  // 跑道选择标签跟随航线两端机场
  const dep = selectedRoute.value?.dep || '';
  const arr = selectedRoute.value?.arr || '';
  const [d, a] = await Promise.all([loadRunways(dep), loadRunways(arr)]);
  depRunways.value = d;
  arrRunways.value = a;
  form.value.depRwy = '';
  form.value.arrRwy = '';
  routeDistance.value = Math.round(selectedRoute.value?.distance_nm || 0);
  // 自动规划航路 + 推荐巡航高度层
  plannedRoute.value = '';
  if (dep && arr) {
    planningRoute.value = true;
    try {
      const plan = await api.post('/api/nav/routes/plan', { origin: dep, destination: arr });
      plannedRoute.value = plan.routeString || '';
      if (plan.totalDistance) routeDistance.value = Math.round(plan.totalDistance);
    } catch { /* 规划失败不阻塞签派 */ }
    planningRoute.value = false;
    if (!form.value.cruiseFl) {
      // route 是 vue-router 的 useRoute，没有 distance_nm；航线距离取所选航线
      const dist = routeDistance.value || selectedRoute.value?.distance_nm || 0;
      form.value.cruiseFl = String(dist < 250 ? 240 : dist < 550 ? 300 : dist < 900 ? 350 : 370);
    }
  }
  scheduleFuelEstimate();
}

async function submit() {
  if (!form.value.routeId) { showToast('请选择航线'); return; }
  if (!form.value.fleetId) { showToast('请选择本公司的飞机'); return; }
  submitting.value = true;
  try {
    const data = await api.post(`/api/airlines/${va.membership.airlineId}/dispatches`, {
      routeId: Number(form.value.routeId),
      fleetId: Number(form.value.fleetId),
      captain: form.value.captain,
      callsign: form.value.callsign,
      schedDep: form.value.schedDep,
      pax: Number(form.value.pax) || 0,
      cargo: Number(form.value.cargo) || 0,
      copilot: form.value.copilot,
      ci: Number(form.value.ci) || 0,
      depRwy: form.value.depRwy,
      arrRwy: form.value.arrRwy,
      cruiseAlt: Number(form.value.cruiseFl) || 0,
      fuelKg: Number(form.value.fuelKg) || 0,
      alternate: form.value.alternate,
      remarks: form.value.remarks,
    });
    showToast(data.message || '签派单已生成');
    form.value = {
      routeId: '', fleetId: '', captain: auth.user?.username || '', callsign: '', schedDep: '', pax: '', cargo: '',
      copilot: '', ci: '', depRwy: '', arrRwy: '', cruiseFl: '', fuelKg: '', alternate: '', remarks: '',
    };
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  submitting.value = false;
}

async function cancel(d) {
  try {
    const data = await api.delete(`/api/airlines/${va.membership.airlineId}/dispatches/${d.id}`);
    showToast(data.message || '已取消');
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
}


/* ---------- 自动油量估算，OpenAP ----------*/
let lastFuelSig = '';
function scheduleFuelEstimate() {
  clearTimeout(fuelTimer);
  fuelTimer = setTimeout(estimateFuel, 600);
}

async function estimateFuel() {
  const type = selectedFleet.value?.aircraft || '';
  const dist = routeDistance.value || selectedRoute.value?.distance_nm || 0;
  if (!type || !dist) return;
  const sig = JSON.stringify([type, Math.round(dist), form.value.cruiseFl, form.value.pax, form.value.cargo]);
  if (sig === lastFuelSig) return;
  lastFuelSig = sig;
  // 竞速保护：请求带递增序号，响应回来只有最新一次才允许写入表单
  const mySeq = ++fuelSeq;
  fuelEstimating.value = true;
  try {
    // 国际航线附加 intl=1：后端按国际备用油规章，30 分钟等待油 + 5% contingency 估算
    const intl = selectedRoute.value?.intl ? 1 : 0;
    const data = await api.get(`/api/nav/fuel-estimate?type=${type}&dist=${Math.round(dist)}&fl=${Number(form.value.cruiseFl) || 0}&pax=${Number(form.value.pax) || 0}&cargo=${Number(form.value.cargo) || 0}&intl=${intl}`);
    if (mySeq !== fuelSeq) return;   // 已有更新的估算请求，丢弃过期响应
    if (data.ok) {
      form.value.fuelKg = String(data.fuel_kg);
      fuelModel.value = `OpenAP 模型 · 巡航 ${Math.round(data.cruise_alt_ft / 100)} · 巡航约 ${data.cruise_hours}h`;
    } else {
      fuelModel.value = '';
      showToast(data.reason || '该机型暂无自动油量模型');
    }
  } catch {
    if (mySeq !== fuelSeq) return;
    fuelModel.value = '';
  }
  if (mySeq === fuelSeq) fuelEstimating.value = false;
}

watch([() => form.value.pax, () => form.value.cargo, () => form.value.cruiseFl], () => scheduleFuelEstimate());

function statusTag(s) {
  if (s === 'open') return { text: '待飞', cls: 'tag-orange' };
  if (s === 'flown') return { text: '已飞', cls: 'tag-green' };
  return { text: '已取消', cls: 'tag' };
}

function kindTag(d) {
  if (d.kind === 'ferry') return { text: '转场', cls: 'tag' };
  if (d.kind === 'charter') return { text: '包机', cls: 'tag-blue' };
  return { text: '航线', cls: 'tag-blue' };
}

/* ---------- 包机任务 ---------- */
const charterMode = ref(false);
const cForm = ref({ dep: '', arr: '', fleetId: '', pax: '', cargo: '' });
const charterFleet = computed(() => {
  const dep = cForm.value.dep.trim().toUpperCase();
  if (!dep) return availableFleet.value;
  return availableFleet.value.filter((f) => (f.location || '') === dep);
});

async function submitCharter() {
  if (!cForm.value.dep || !cForm.value.arr) { showToast('请填写起降机场 ICAO'); return; }
  if (!cForm.value.fleetId) { showToast('请选择飞机'); return; }
  submitting.value = true;
  try {
    const data = await api.post(`/api/airlines/${va.membership.airlineId}/charters`, {
      dep: cForm.value.dep.trim().toUpperCase(),
      arr: cForm.value.arr.trim().toUpperCase(),
      fleetId: Number(cForm.value.fleetId),
      pax: Number(cForm.value.pax) || 0,
      cargo: Number(cForm.value.cargo) || 0,
    });
    showToast(data.message || '包机任务已创建');
    cForm.value = { dep: '', arr: '', fleetId: '', pax: '', cargo: '' };
    charterMode.value = false;
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  submitting.value = false;
}

function flightStateText(d) {
  if (d.status !== 'open') return '';
  if (d.flight_state === 'issued') return '待起飞上报';
  if (d.flight_state === 'departed') return '已起飞 · 空中';
  if (d.flight_state === 'landed') return '已落地 · 可提交报告';
  return '';
}

const reporting = ref('');

async function reportEvent(d, type) {
  if (reporting.value) return;
  reporting.value = d.id + ':' + type;
  try {
    const data = await api.post(`/api/airlines/${va.membership.airlineId}/dispatches/${d.id}/events`, {
      type,
      token: d.flight_token || '',
    });
    showToast(data.message || '已记录');
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  reporting.value = '';
}

function toPirep(d) {
  router.push({ path: '/va/pirep', query: { dispatchId: d.id } });
}
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 56vw, 1100px)">
    <div class="page-header">
      <div class="page-title">飞行签派</div>
      <div class="page-desc">
        起飞前选择航司航线与本公司飞机生成放行单，飞完后凭签派单提交飞行报告
        <template v-if="va.membership">
          · 公司账上 {{ (va.membership.balance || 0).toLocaleString() }}
          现实结算：飞行员领固定工资，公司挣客票收入
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
      <!-- 模式切换：航线签派 / 包机任务 -->
      <div class="seg" style="margin-bottom: 16px">
        <button class="seg-btn" :class="{ on: !charterMode }" @click="charterMode = false">航线签派</button>
        <button class="seg-btn" :class="{ on: charterMode }" @click="charterMode = true">包机任务</button>
      </div>

      <!-- 机队概况，购置在机队管理页-->
      <div class="glass card" v-if="!charterMode">
        <div class="card-title" style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap; row-gap: 8px">
          <Icon name="wings" :size="16" /> 公司机队
          <span class="card-sub" style="margin: 0">{{ availableFleet.length }}/{{ fleet.length }} 架可用</span>
          <router-link
            :to="'/va/fleet'"
            class="btn btn-primary btn-sm"
            style="margin-left: auto"
          >{{ va.isCEO ? '去购置飞机' : '查看机队' }}</router-link>
        </div>
        <div v-if="!fleet.length" class="card-sub">机队为空，新航司审核通过时赠送 2 架 A320neo</div>
        <div v-else class="card-sub">
          <span v-for="f in fleet" :key="f.id" style="margin-right: 14px">
            <span :style="{ color: f.status === 'available' ? 'var(--green)' : 'var(--orange)' }">●</span>
            {{ catalog[f.aircraft]?.name || f.aircraft }} {{ f.reg }}
          </span>
        </div>
      </div>

      <!-- 结算规则公示 -->
      <div class="glass card">
        <div class="card-title"><Icon name="award" :size="16" /> 结算规则公示</div>
        <div class="list-sub" style="line-height: 1.9">
          <b>飞行员工资</b> = 航线底薪 + 飞行时长 × 时薪，本公司当前 {{ va.membership.hourlyRate }}
          + 航程 × 里程津贴，本公司当前 {{ va.membership.distanceRate }}<br />
          <b>公司运输收入</b> = 旅客 × 航程 nm × 0.6，客运 + 货物 kg × 航程 × 0.002，货运<br />
          <b>公司净入</b> = 运输收入 − 飞行员工资，空载或亏损航段公司照付工资，可能为负<br />
          CEO 审核通过后工资立即入账；CEO 审本人报告单笔工资封顶 20,000。<br />
          时薪与里程津贴由 CEO 在航司设置中调整；底薪由 CEO 按航线设定。
        </div>
      </div>

      <!-- 新建签派单，航线模式-->
      <div v-if="!charterMode" class="glass card" style="margin-top: 16px">
        <div class="card-title"><Icon name="check" :size="16" /> 新建签派单</div>
        <div v-if="!routes.length" class="card-sub">本航司还没有航线，请先让 CEO 在航司管理中添加</div>
        <div v-else-if="!fleet.length" class="card-sub">公司没有可用飞机——请 CEO 先购置飞机</div>
        <div v-else>
          <div class="field">
            <label class="label">航线</label>
            <SelectMenu
              v-model="form.routeId" :options="routeOptions"
              placeholder="选择 CEO 发布的航线" @update:model-value="onRouteChangeFull"
            />
          </div>
          <div class="field">
            <label class="label">飞机，需为本公司机队并位于 {{ selectedRoute?.dep || '起飞机场' }}</label>
            <SelectMenu
              v-model="form.fleetId" :options="dispatchableOptions"
              :placeholder="dispatchableFleet.length ? '选择可用飞机' : `无位于 ${selectedRoute?.dep || '本场'} 的可用飞机——机队页可发起转场`"
            />
          </div>
          <div class="input-row">
            <div class="field" style="flex: 1">
              <label class="label">呼号</label>
              <input v-model="form.callsign" class="input" :placeholder="selectedRoute?.flight_no || '如 CES5966'" maxlength="16" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">计划起飞，本地时间</label>
              <DatePicker v-model="form.schedDep" mode="datetime" placeholder="选择计划起飞时间" />
            </div>
          </div>
          <div class="input-row">
            <div class="field" style="flex: 1">
              <label class="label">旅客{{ spec ? `最多 ${spec.pax}` : '' }}</label>
              <input v-model="form.pax" class="input" type="number" min="0" :max="spec?.pax || 600" placeholder="0" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">货物，单位 kg，最多 40,000</label>
              <input v-model="form.cargo" class="input" type="number" min="0" max="40000" placeholder="0" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">成本指数 CI</label>
              <input v-model="form.ci" class="input" type="number" min="0" max="999" placeholder="0" />
            </div>
          </div>
          <div class="input-row">
            <div class="field" style="flex: 1">
              <label class="label">机长</label>
              <input v-model="form.captain" class="input" maxlength="20" placeholder="机长姓名" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">副驾，可选</label>
              <input v-model="form.copilot" class="input" maxlength="20" />
            </div>
          </div>
          <div class="input-row">
            <div class="field" style="flex: 1">
              <label class="label">出发跑道</label>
              <SelectMenu
                v-if="depRunways.length" v-model="form.depRwy" :options="depRunwayOptions"
                placeholder="选择跑道"
              />
              <input v-else v-model="form.depRwy" class="input" placeholder="如 36L" maxlength="8" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">到达跑道</label>
              <SelectMenu
                v-if="arrRunways.length" v-model="form.arrRwy" :options="arrRunwayOptions"
                placeholder="选择跑道"
              />
              <input v-else v-model="form.arrRwy" class="input" placeholder="如 36R" maxlength="8" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">备降场，ICAO</label>
              <input v-model="form.alternate" class="input" placeholder="如 ZBTJ" maxlength="8" />
            </div>
          </div>
          <div class="input-row">
            <div class="field" style="flex: 1">
              <label class="label">巡航高度层，FL</label>
              <input v-model="form.cruiseFl" class="input" type="number" min="50" max="450" placeholder="如 350，相当于 35000 英尺" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">携带燃油，kg{{ fuelModel ? ' · ' + fuelModel : fuelEstimating ? ' · 估算中…' : '' }}</label>
              <input v-model="form.fuelKg" class="input" type="number" placeholder="自动估算，可手动修改" />
            </div>
          </div>
          <div class="field">
            <label class="label">
              航路，自动查询
              <span v-if="planningRoute" style="color: var(--text-2)"> · 规划中…</span>
              <span v-else-if="plannedRoute" style="color: var(--green)"> · 已自动生成，AIRAC 2609</span>
            </label>
            <div v-if="plannedRoute" class="route-box">{{ plannedRoute }}</div>
            <div v-else class="card-sub" style="padding: 10px 14px; border: 1px dashed var(--border); border-radius: 10px">
              {{ planningRoute ? '正在规划航路…' : '选择航线后自动规划航路' }}
            </div>
          </div>
          <div class="field">
            <label class="label">签派备注</label>
            <textarea v-model="form.remarks" class="textarea" rows="2" placeholder="航路要点、天气提示等，可空" maxlength="200"></textarea>
          </div>

          <!-- 载重与收入预览 -->
          <div v-if="spec" class="card-sub" style="margin: 4px 0 12px">
            载荷 {{ payloadKg.toLocaleString() }} kg · ZFW {{ zfw.toLocaleString() }} kg ·
            预计起飞全重 {{ tow.toLocaleString() }} kg
            <span v-if="overMtow" style="color: var(--red)">超过 MTOW {{ spec.mtow.toLocaleString() }} kg，请减载！</span>
            <template v-if="selectedRoute?.distance_nm && Number(form.pax) > 0">
              · 预计票款收入 {{ Math.round(Number(form.pax) * selectedRoute.distance_nm * 0.6).toLocaleString() }}
              {{ Number(form.pax) }} 客 × {{ Math.round(selectedRoute.distance_nm) }}nm × 0.6
            </template>
          </div>
          <button class="btn btn-primary" :disabled="submitting" @click="submit">
            {{ submitting ? '生成中…' : '生成签派单' }}
          </button>
        </div>
      </div>

      <!-- 包机任务，自选起降，不依赖航线-->
      <div v-if="charterMode" class="glass card" style="margin-top: 16px">
        <div class="card-title"><Icon name="plane" :size="16" /> 承接包机任务</div>
        <div class="card-sub" style="margin-bottom: 10px">
          自由包机：自选起降机场，需飞机在本场，客货自定；包机溢价 1.5× 计入公司收入，
          飞行员按时薪 1.2× + 里程补贴结算，同样需要完成起飞/落地上报并接受 ACARS 核验
        </div>
        <div v-if="!fleet.length" class="card-sub">公司没有可用飞机——请 CEO 先购置飞机</div>
        <template v-else>
          <div class="input-row">
            <div class="field" style="flex: 1">
              <label class="label">起飞机场，ICAO · 需飞机在本场</label>
              <input v-model="cForm.dep" class="input" placeholder="如 ZBAA" maxlength="4" @input="cForm.dep = cForm.dep.toUpperCase(); cForm.fleetId = ''" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">到达机场，ICAO</label>
              <input v-model="cForm.arr" class="input" placeholder="如 ZSPD" maxlength="4" @input="cForm.arr = cForm.arr.toUpperCase()" />
            </div>
          </div>
          <div class="field">
            <label class="label">飞机，位于 {{ cForm.dep || '起飞机场' }}</label>
            <SelectMenu
              v-model="cForm.fleetId" :options="charterFleetOptions"
              :placeholder="charterFleet.length ? '选择可用飞机' : `无位于 ${cForm.dep || '本场'} 的可用飞机`"
            />
          </div>
          <div class="input-row">
            <div class="field" style="flex: 1">
              <label class="label">旅客{{ spec ? `最多 ${spec.pax}` : '' }}</label>
              <input v-model="cForm.pax" class="input" type="number" min="0" :max="spec?.pax || 600" placeholder="0" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">货物，单位 kg，最多 40,000</label>
              <input v-model="cForm.cargo" class="input" type="number" min="0" max="40000" placeholder="0" />
            </div>
          </div>
          <button class="btn btn-primary" :disabled="submitting" @click="submitCharter">
            {{ submitting ? '创建中…' : '承接包机任务' }}
          </button>
        </template>
      </div>

      <!-- 我的签派单 -->
      <div class="glass card" style="margin-top: 16px">
        <div class="card-title"><Icon name="briefcase" :size="16" /> 我的签派单</div>
        <div v-if="!dispatches.length" class="empty">
          <div class="empty-icon"><Icon name="briefcase" :size="22" /></div>
          <div>还没有签派单</div>
        </div>
        <div v-for="d in dispatches" :key="d.id" class="list-item" style="flex-wrap: wrap">
          <div class="list-main">
            <div class="list-title">
              <span class="tag" :class="kindTag(d).cls" style="margin-right: 6px">{{ kindTag(d).text }}</span>
              <span class="tag" :class="statusTag(d.status).cls" style="margin-right: 8px">{{ statusTag(d.status).text }}</span>
              {{ d.flight_no || '—' }} {{ d.dep }} → {{ d.arr }}<template v-if="d.distance_nm"> · {{ Math.round(d.distance_nm) }}nm</template>
              <span class="card-sub" style="margin-left: 6px">{{ d.callsign }}</span>
            </div>
            <div class="list-sub">
              {{ d.aircraft }}<template v-if="d.fleet_reg"> · {{ d.fleet_reg }}</template>
              <template v-if="d.captain"> · 机长 {{ d.captain }}</template>
              <template v-if="d.pax"> · 旅客 {{ d.pax }}</template>
              <template v-if="d.cargo"> · 货物 {{ d.cargo }}kg</template>
              <template v-if="d.cruise_alt"> · 巡航 FL{{ d.cruise_alt }}</template>
              <template v-if="d.fuel_kg"> · 燃油 {{ d.fuel_kg }}kg</template>
              <template v-if="d.alternate"> · 备降 {{ d.alternate }}</template>
              · {{ fmtTime(d.created_at) }}
            </div>
            <!-- 平台 ACARS：飞行节点上报 -->
            <div v-if="d.status === 'open'" style="display: flex; align-items: center; gap: 8px; margin-top: 10px; flex-wrap: wrap">
              <span class="card-sub" style="font-weight: 600">{{ flightStateText(d) }}</span>
              <button
                v-if="d.flight_state === 'issued'" class="btn btn-primary btn-sm"
                :disabled="!!reporting" @click="reportEvent(d, 'depart')"
              >{{ reporting === d.id + ':depart' ? '上报中…' : '起飞上报' }}</button>
              <button
                v-else-if="d.flight_state === 'departed'" class="btn btn-primary btn-sm"
                :disabled="!!reporting" @click="reportEvent(d, 'arrive')"
              >{{ reporting === d.id + ':arrive' ? '上报中…' : '落地上报' }}</button>
              <span v-else-if="d.flight_state === 'landed'" class="tag tag-green">时间线完整</span>
            </div>
          </div>
          <div style="display: flex; gap: 8px">
            <button v-if="d.status === 'open' && d.flight_state === 'landed'" class="btn btn-primary btn-sm" @click="toPirep(d)">提交报告</button>
            <button v-if="d.status === 'open'" class="btn btn-ghost btn-sm" @click="cancel(d)">取消</button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.route-box {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.8;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  word-break: break-all;
  white-space: pre-wrap;
}
</style>
