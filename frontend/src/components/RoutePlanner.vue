<script setup>
/**
 * 航路查询：AIRAC 导航数据 A* 规划，sidecar 服务
 * 机场联想 / SID·STAR 选择 / 备选航线 / 自定义航路分析
 */
import { computed, onUnmounted, ref, watch } from 'vue';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import Icon from './Icon.vue';
import SelectMenu from './SelectMenu.vue';
import AirportInput from './AirportInput.vue';

const status = ref(null);          // sidecar {cycle, waypointCount, ...}

const originQuery = ref('');
const destQuery = ref('');
const originSel = ref(null);       // {icao, name, lat, lon}
const destSel = ref(null);
const details = ref({});           // icao -> {airport, runways, sids, stars}

const sidChoice = ref('');
const starChoice = ref('');
const planning = ref(false);
const planError = ref('');
// 航路数据，sidecar 状态查询失败时的提示。
// 修复，2026-10-11，ESLint no-undef 抓出：这里原先只写 `statusError.value = err.message`
// 却从未声明 statusError —— sidecar 挂掉时 catch 里会抛 ReferenceError，
// 本该显示的「航路数据不可用」提示从未出现过，错误被静默吞掉。
const statusError = ref('');
const plan = ref(null);            // 推荐航路
const alternatives = ref([]);      // 备选航路
const activeIndex = ref(-1);       // -1 = 推荐
const analyzed = ref(false);       // 是否处于自定义分析视图
const analysis = ref(null);
const analyzing = ref(false);
const copied = ref(false);
let copyTimer = null;

const originDetails = computed(() => (originSel.value ? details.value[originSel.value.icao] : null));
const destDetails = computed(() => (destSel.value ? details.value[destSel.value.icao] : null));
const sidOptions = computed(() => (originDetails.value ? originDetails.value.sids.map((s) => s.fullName) : []));
const starOptions = computed(() => (destDetails.value ? destDetails.value.stars.map((s) => s.fullName) : []));

/**
 * 选中机场，来自 AirportInput 联想后的处理
 */
function onAirportPicked(field, ap) {
  plan.value = null;
  alternatives.value = [];
  activeIndex.value = -1;
  analysis.value = null;
  analyzed.value = false;
  planError.value = '';
  if (field === 'origin') {
    originQuery.value = ap.icao;
    originSel.value = ap;
    sidChoice.value = '';
  } else {
    destQuery.value = ap.icao;
    destSel.value = ap;
    starChoice.value = '';
  }
  loadDetails(ap.icao);
  if (originSel.value && destSel.value) planRoute();
}

/**
 * 从输入文本自动识别机场，用户直接输入 4 位 ICAO 而未点选联想时的兜底
 */
async function resolveAirport(field) {
  const sel = field === 'origin' ? originSel.value : destSel.value;
  if (sel) return sel;

  const raw = (field === 'origin' ? originQuery.value : destQuery.value).trim().toUpperCase();
  if (!/^[A-Z0-9]{4}$/.test(raw)) return null;

  try {
    const data = await api.get(`/api/nav/airports?q=${encodeURIComponent(raw)}`);
    const list = data.airports || [];
    if (!list.length) return null;
    const exact = list.find((a) => a.icao === raw);
    if (!exact) return null;
    if (field === 'origin') originSel.value = exact;
    else destSel.value = exact;
    loadDetails(exact.icao);
    return exact;
  } catch {
    return null;
  }
}

async function loadDetails(icao) {
  if (details.value[icao]) return;
  try {
    details.value = { ...details.value, [icao]: await api.get(`/api/nav/airports/${icao}/details`) };
  } catch { /* 详情失败不阻塞规划 */ }
}

/* ---------- 规划 ---------- */
async function planRoute() {
  planning.value = true;
  planError.value = '';
  analysis.value = null;
  analyzed.value = false;
  try {
    // 先自动解析输入文本中的机场，不强制走联想列表
    const o = await resolveAirport('origin');
    const d = await resolveAirport('dest');
    if (!o || !d) {
      showToast('无法识别机场：请输入 4 位 ICAO 代码或从联想列表选择');
      return;
    }
    if (o.icao === d.icao) {
      showToast('起飞与到达机场相同');
      return;
    }
    const data = await api.post('/api/nav/routes/plan', {
      origin: o.icao,
      destination: d.icao,
      sid: sidChoice.value || null,
      star: starChoice.value || null,
    });
    plan.value = data;
    alternatives.value = data.alternatives || [];
    activeIndex.value = -1;
  } catch (err) {
    plan.value = null;
    alternatives.value = [];
    planError.value = err.message;
  } finally {
    planning.value = false;
  }
}

function showRoute(i) {
  analyzed.value = false;
  activeIndex.value = i;
}

// 展示中的航路，推荐或某条备选
const displayRoute = computed(() => {
  if (analyzed.value) return null;
  if (activeIndex.value === -1) return plan.value;
  return alternatives.value[activeIndex.value] || plan.value;
});

// 更换 SID/STAR 后自动重新规划，机场已选且至少规划过一次或两端齐全时
watch([sidChoice, starChoice], ([ns, nt], [os, ot]) => {
  if (ns === os && nt === ot) return;
  if (originSel.value && destSel.value && plan.value) planRoute();
});

/* ---------- 自定义航路分析 ---------- */
const analyzeInput = ref('');
async function analyze() {
  if (!analyzeInput.value.trim()) return;
  analyzing.value = true;
  planError.value = '';
  try {
    const data = await api.post('/api/nav/routes/analyze', {
      route: analyzeInput.value.trim(),
      origin: originSel.value?.icao || null,
      destination: destSel.value?.icao || null,
    });
    analysis.value = data;
    analyzed.value = data.ok === true;
    if (!data.ok) showToast(data.error || '航路分析失败');
  } catch (err) {
    analysis.value = null;
    analyzed.value = false;
    planError.value = err.message;
  } finally {
    analyzing.value = false;
  }
}

async function copyRouteString() {
  const text = displayRoute.value?.routeString;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copied.value = true;
    // 1 秒后自动复原，图标翻回对勾前、提示消失
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => (copied.value = false), 1000);
  } catch {
    showToast('复制失败，请手动选择复制');
  }
}

/** 距离统一保留 2 位小数 */
function nm(v) {
  return Number(v ?? 0).toFixed(2);
}

/* ---------- 查询进度，阶段化文案 + 动画条 ----------*/
const progressText = ref('');
let progressTimer = null;
const PROGRESS_STEPS = [
  '正在连接规划服务…',
  '构建高空航路图…',
  '搜索最优航路…',
  '正在生成备选航线…',
];

watch([planning, analyzing], ([p, a]) => {
  if (p || a) {
    let i = 0;
    progressText.value = PROGRESS_STEPS[0];
    clearInterval(progressTimer);
    progressTimer = setInterval(() => {
      i = Math.min(i + 1, PROGRESS_STEPS.length - 1);
      progressText.value = PROGRESS_STEPS[i];
    }, 1200);
  } else {
    clearInterval(progressTimer);
  }
});
onUnmounted(() => { clearInterval(progressTimer); clearTimeout(copyTimer); });

/* 状态探活 */
(async () => {
  try {
    status.value = await api.get('/api/nav/status');
  } catch (err) {
    statusError.value = err.message;
  }
})();
</script>

<template>
  <div class="glass card">
    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 8px">
      <div class="card-title" style="margin: 0">航路查询</div>
      <span v-if="status" class="tag tag-blue">{{ status.cycle }}</span>
    </div>

    <!-- 航路数据服务不可用时的显式提示，原先只赋值不显示，见 script 里的修复说明-->
    <div v-if="statusError" class="alert alert-err" style="margin-top: 12px">
      航路数据服务暂时不可用，{{ statusError }}。查询与规划可能失败，请稍后重试或联系管理员。
    </div>

    <div class="planner-grid" style="margin-top: 16px">
      <!-- 起飞机场 -->
      <div class="field" style="margin-bottom: 0">
        <label class="label">起飞机场 ICAO</label>
        <AirportInput
          v-model="originQuery"
          placeholder="输入 ICAO 或英文名，如 ZBAA"
          @select="(ap) => onAirportPicked('origin', ap)"
        />
      </div>

      <!-- 到达机场 -->
      <div class="field" style="margin-bottom: 0">
        <label class="label">到达机场 ICAO</label>
        <AirportInput
          v-model="destQuery"
          placeholder="输入 ICAO 或英文名，如 ZSPD"
          @select="(ap) => onAirportPicked('dest', ap)"
        />
      </div>

      <!-- SID / STAR -->
      <div class="field" style="margin-bottom: 0">
        <label class="label">离场程序 <span class="optional">选填，默认自动</span></label>
        <SelectMenu
          v-model="sidChoice"
          :disabled="!sidOptions.length"
          :options="[{ value: '', label: '自动选择，NO SID' }, ...sidOptions.map((s) => ({ value: s, label: s }))]"
        />
      </div>
      <div class="field" style="margin-bottom: 0">
        <label class="label">进场程序 <span class="optional">选填，默认自动</span></label>
        <SelectMenu
          v-model="starChoice"
          :disabled="!starOptions.length"
          :options="[{ value: '', label: '自动选择，NO STAR' }, ...starOptions.map((s) => ({ value: s, label: s }))]"
        />
      </div>
    </div>

    <div style="display: flex; gap: 10px; margin-top: 16px; flex-wrap: wrap">
      <button class="btn btn-primary" :disabled="planning || !status" @click="planRoute">
        {{ planning ? '规划中…' : '规划航路' }}
      </button>
    </div>

    <!-- 查询进度 -->
    <div v-if="planning || analyzing" class="plan-progress">
      <div class="plan-progress-track"><div class="plan-progress-fill"></div></div>
      <span class="plan-progress-text">{{ progressText }}</span>
    </div>

    <div v-if="planError" class="alert alert-err" style="margin-top: 14px; margin-bottom: 0">{{ planError }}</div>

    <!-- 规划结果 -->
    <template v-if="plan">
      <div v-if="plan.fallbackMessage" class="alert alert-info" style="margin-top: 14px; margin-bottom: 0">
        {{ plan.fallbackMessage }}
      </div>

      <div v-if="displayRoute" style="margin-top: 16px">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px">
          <div class="card-title" style="margin: 0">
            航路，{{ displayRoute.origin.icao }} → {{ displayRoute.destination.icao }}
          </div>
          <button class="btn btn-ghost btn-sm copy-btn" :class="{ 'is-copied': copied }" @click="copyRouteString">
            <span class="copy-icon"><Icon :name="copied ? 'check' : 'plus'" :size="13" /></span>
            {{ copied ? '已复制' : '复制' }}
            <!-- 上方「已复制」提示，出现 1 秒后随状态一起复原-->
            <transition name="copy-tip">
              <span v-if="copied" class="copy-tip">已复制</span>
            </transition>
          </button>
        </div>
        <div class="route-str">{{ displayRoute.routeString }}</div>
      </div>

      <div v-if="displayRoute" style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px">
        <span class="tag tag-blue">离场 {{ nm(displayRoute.costs.sidDistance) }} NM<span v-if="displayRoute.sid.procedure">{{ displayRoute.sid.procedure }}</span></span>
        <span class="tag tag-orange">航路 {{ nm(displayRoute.costs.airwayDistance) }} NM</span>
        <span v-if="displayRoute.costs.switchCount" class="tag">换路 {{ displayRoute.costs.switchCount }} 次，+{{ nm(displayRoute.costs.switchPenalty) }} NM</span>
        <span class="tag tag-purple">进场 {{ nm(displayRoute.costs.starDistance) }} NM<span v-if="displayRoute.star.procedure">{{ displayRoute.star.procedure }}</span></span>
        <span class="tag tag-green">总距离 {{ nm(displayRoute.costs.total) }} NM</span>
        <span class="tag">{{ displayRoute.method === 'DCT' ? '直飞连接' : '高空航路' }}</span>
      </div>

      <!-- 可选航线 -->
      <div v-if="alternatives.length" style="margin-top: 12px">
        <div class="label" style="margin-bottom: 6px">可选航线</div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <button class="btn btn-sm" :class="activeIndex === -1 && !analyzed ? 'btn-dark' : 'btn-ghost'" @click="showRoute(-1)">
            推荐，{{ nm(plan.costs.total) }} NM
          </button>
          <button
            v-for="(alt, i) in alternatives"
            :key="i"
            class="btn btn-sm"
            :class="activeIndex === i && !analyzed ? 'btn-dark' : 'btn-ghost'"
            @click="showRoute(i)"
          >
            备选 {{ i + 1 }}，+{{ nm(alt.costDelta) }} NM
          </button>
          <button v-if="analyzed" class="btn btn-sm btn-ghost" @click="analyzed = false">返回规划结果</button>
        </div>
      </div>
    </template>

    <!-- 自定义航路分析 -->
    <div style="margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border)">
      <div class="card-title">自定义航路分析</div>
      <div class="card-sub">粘贴航路字符串，支持 DCT 与进离场程序名，自动忽略速度/高度字段，验证并绘制</div>
      <div class="input-row" style="max-width: 760px">
        <input v-model="analyzeInput" class="input" placeholder="如 ELKUR W40 VYK W34 ANRAT" @keyup.enter="analyze" />
        <button class="btn btn-dark" :disabled="analyzing" @click="analyze">
          {{ analyzing ? '分析中…' : '分析航路' }}
        </button>
      </div>

      <template v-if="analysis">
        <div v-if="!analysis.ok" class="alert alert-err" style="margin-top: 14px; margin-bottom: 0">
          {{ analysis.error || '航路分析失败' }}
        </div>
        <template v-else>
          <div class="alert alert-ok" style="margin-top: 14px; margin-bottom: 0">
            您的航路适合 AIRAC {{ analysis.cycle }} 导航数据 · 总距离 {{ nm(analysis.totalDistance) }} NM
          </div>
          <div class="route-str" style="margin-top: 10px">{{ analysis.routeString }}</div>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.planner-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px 16px;
}
@media (max-width: 720px) {
  .planner-grid { grid-template-columns: 1fr; }
}
.input-icao {
  text-transform: uppercase;
  font-family: 'SF Mono', 'JetBrains Mono', Consolas, monospace;
  letter-spacing: 1.5px;
  font-weight: 600;
}

/* 航路串：跟随主题配色 */
.route-str {
  font-family: 'SF Mono', 'JetBrains Mono', Consolas, monospace;
  font-size: 13.5px;
  line-height: 1.7;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: var(--radius-sm);
  padding: 13px 16px;
  word-break: break-word;
  user-select: all;
}

/* 查询进度条：蓝色填充 + 白色边框 */
.plan-progress { margin-top: 16px; }
.plan-progress-track {
  height: 14px;
  border-radius: 999px;
  background: var(--surface);
  border: 2px solid #ffffff;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}
.plan-progress-fill {
  height: 100%;
  width: 34%;
  border-radius: 999px;
  background: linear-gradient(90deg, #0a84ff, #0071e3);
  animation: plan-slide 1.15s ease-in-out infinite;
}
@keyframes plan-slide {
  0% { transform: translateX(-110%); }
  100% { transform: translateX(410%); }
}
.plan-progress-text {
  display: block;
  margin-top: 7px;
  font-size: 12px;
  color: var(--text-2);
}

/* ---------- 复制按钮：图标翻转为对勾 + 上方弹出「已复制」，1 秒后复原 ----------
   注意：不能用常驻的 rotateY 180deg —— 镜像会留在最终状态，对勾看起来就成了「∨」。
   这里用「翻转穿过」动画，90° 时侧身不可见、落地回正，结束后对勾是正的。*/
.copy-btn { position: relative; }
.copy-icon {
  display: inline-flex;
  transform-origin: 50% 50%;
}
.copy-btn.is-copied .copy-icon { animation: copy-flip 0.36s cubic-bezier(0.34, 1.3, 0.64, 1); }
@keyframes copy-flip {
  0% { transform: rotateY(0deg) scale(1); }
  45% { transform: rotateY(90deg) scale(0.8); }
  100% { transform: rotateY(0deg) scale(1); }
}

.copy-tip {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 7px);
  transform: translateX(-50%);
  padding: 4px 9px;
  border-radius: 7px;
  background: #1f2937;
  color: #fff;
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
  pointer-events: none;
  z-index: 5;
}
.copy-tip::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 100%;
  margin-left: -4px;
  border: 4px solid transparent;
  border-top-color: #1f2937;
}
.copy-tip-enter-active { transition: opacity 0.18s ease, transform 0.24s cubic-bezier(0.34, 1.4, 0.64, 1); }
.copy-tip-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.copy-tip-enter-from { opacity: 0; transform: translateX(-50%) translateY(4px) scale(0.96); }
.copy-tip-leave-to { opacity: 0; transform: translateX(-50%) translateY(-3px); }
</style>
