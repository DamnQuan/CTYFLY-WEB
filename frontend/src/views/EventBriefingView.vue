<script setup>
/**
 * 活动简报页 —— VACST 风格定稿设计
 *
 * 布局：顶部 header 卡，返回 + 标题 + 状态→ 中部两栏，左海报 / 右信息卡
 * → 底部 4 张统计卡，统一白卡→ 管制席位报名区 → 报名名单 tab。
 * 席位制报名：飞行员在信息卡内联表单报名，呼号 + 机型，
 * 管制员在席位区点选席位报名，POST signup {role:'atc', positionId}。
 * 数据来自活动详情接口，/api/events/{id}：含航路 / 距离 / NOTAMS / 发布人 CID、
 * 席位列表，含占用状态、分角色报名统计与当前用户报名状态。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { useAuthStore } from '../stores/auth.js';
import { fmtTime, showToast } from '../utils.js';
import { confirmModal } from '../modal.js';
import Icon from '../components/Icon.vue';
import SegmentedTabs from '../components/SegmentedTabs.vue';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const eventId = computed(() => Number(route.params.id));

/* 与顶部 tag 同源的状态映射：报名中蓝 / 进行中橙 / 已结束灰 */
const BRIEF_STATUS = {
  upcoming: { text: '报名中', tag: 'tag-blue' },
  ongoing: { text: '进行中', tag: 'tag-orange' },
  ended: { text: '已结束', tag: '' },
  cancelled: { text: '已取消', tag: '' },
};

const event = ref(null);
const signups = ref([]);
const atcPositions = ref([]);
const pilotCount = ref(0);
const atcCount = ref(0);
const my = ref({ signed: false, role: '', callsign: '', aircraft: '', positionId: null });
const posterImageId = ref(null);
const posterUrl = ref('');
const depName = ref('');
const arrName = ref('');
const loading = ref(true);
const countdown = ref('00:00:00');
const tab = ref('pilot');

/* 飞行员报名：信息卡内联小表单，呼号 + 机型*/
const showPilotForm = ref(false);
const pilotForm = ref({ callsign: '', aircraft: '' });
const pilotBusy = ref(false);
/* 管制席位报名防连点，记录正在操作的席位 id*/
const posBusyId = ref(0);

const depFull = computed(() => (event.value?.dep || '—') + (depName.value ? ' ' + depName.value : ''));
const arrFull = computed(() => (event.value?.arr || '—') + (arrName.value ? ' ' + arrName.value : ''));
const statusMeta = computed(() => BRIEF_STATUS[event.value?.status] || { text: event.value?.status || '', tag: '' });
const pilotList = computed(() => signups.value.filter((s) => s.role !== 'atc'));
const atcList = computed(() => signups.value.filter((s) => s.role === 'atc'));
const rosterList = computed(() => (tab.value === 'atc' ? atcList.value : pilotList.value));
const rosterTabs = [
  { value: 'pilot', label: '飞行员' },
  { value: 'atc', label: '管制员' },
];
/* 报名是否开放，已结束/已取消的活动只可查看*/
const signupOpen = computed(() => ['upcoming', 'ongoing'].includes(event.value?.status));

async function load() {
  loading.value = true;
  try {
    const data = await api.get(`/api/events/${eventId.value}`);
    event.value = data.event;
    signups.value = data.signups || [];
    atcPositions.value = data.atcPositions || [];
    pilotCount.value = data.pilotCount || 0;
    atcCount.value = data.atcCount || 0;
    my.value = data.my || { signed: false, role: '', callsign: '', aircraft: '', positionId: null };
    await loadPoster(data.posterImageId || null);
    tickCountdown();
    loadAirportNames();
    // 未报名时预填上次呼号，减少重复输入
    if (!my.value.signed && !pilotForm.value.callsign) {
      pilotForm.value.callsign = await lastCallsign();
    }
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}

async function loadPoster(imageId) {
  // 海报图同工单附件一样要带鉴权头，先取 Blob 再转 objectURL，用完统一 revoke
  if (posterUrl.value) {
    URL.revokeObjectURL(posterUrl.value);
    posterUrl.value = '';
  }
  posterImageId.value = imageId;
  if (!imageId) return;
  try {
    const blob = await api.blob(`/api/briefings/images/${imageId}`, 30000);
    posterUrl.value = URL.createObjectURL(blob);
  } catch {
    posterUrl.value = '';
  }
}

/* 机场中文名，AIRAC 数据库，查不到就只显示 ICAO，失败静默降级*/
async function fetchAirportName(icao) {
  if (!icao) return '';
  try {
    const data = await api.get(`/api/nav/airports?q=${encodeURIComponent(icao)}`);
    const hit = (data.airports || []).find((a) => a.icao === icao);
    return hit?.name || '';
  } catch {
    return '';
  }
}

async function loadAirportNames() {
  depName.value = await fetchAirportName(event.value?.dep);
  arrName.value = await fetchAirportName(event.value?.arr);
}

/* ---------- 报名剩余倒计时：总小时:分:秒，开赛后归零 ---------- */
function tickCountdown() {
  const ev = event.value;
  if (!ev?.start_time || ['ongoing', 'ended', 'cancelled'].includes(ev.status)) {
    countdown.value = '00:00:00';
    return;
  }
  const target = new Date(String(ev.start_time).replace(' ', 'T')).getTime();
  const diff = Math.floor((target - Date.now()) / 1000);
  if (!Number.isFinite(diff) || diff <= 0) {
    countdown.value = '00:00:00';
    return;
  }
  const p = (n) => String(n).padStart(2, '0');
  countdown.value = `${p(Math.floor(diff / 3600))}:${p(Math.floor((diff % 3600) / 60))}:${p(diff % 60)}`;
}
let countdownTimer = 0;

/* ---------- 席位制报名：飞行员 / 管制员 ---------- */
const CALLSIGN_KEY = 'ctyfly_last_callsign';

function storedCallsign() {
  try {
    return localStorage.getItem(CALLSIGN_KEY) || '';
  } catch {
    return '';
  }
}

async function lastCallsign() {
  // 优先用本机记住的上次呼号；没有再取最近一次报名记录的呼号兜底
  const saved = storedCallsign();
  if (saved) return saved;
  try {
    const data = await api.get('/api/events/signups/mine');
    return data.signups?.[0]?.callsign || '';
  } catch {
    return '';
  }
}

/* 未登录统一先跳登录页，登录后回到简报页 */
function requireLogin() {
  router.push({ name: 'login', query: { redirect: route.fullPath } });
}

async function signupPilot() {
  if (pilotBusy.value) return;
  if (!auth.isLoggedIn) {
    requireLogin();
    return;
  }
  const callsign = pilotForm.value.callsign.trim();
  const aircraft = pilotForm.value.aircraft.trim();
  if (!callsign) {
    showToast('请填写呼号');
    return;
  }
  if (!aircraft) {
    showToast('请填写机型');
    return;
  }
  pilotBusy.value = true;
  try {
    await api.post(`/api/events/${eventId.value}/signup`, {
      role: 'pilot',
      callsign,
      aircraft,
    });
    try { localStorage.setItem(CALLSIGN_KEY, callsign); } catch { /* 存储不可用仅影响下次预填 */ }
    showToast(my.value.signed ? '报名信息已更新' : '报名成功');
    showPilotForm.value = false;
    await load();
  } catch (err) {
    showToast(err.message);
  }
  pilotBusy.value = false;
}

async function signupAtc(pos) {
  if (posBusyId.value) return;
  if (!auth.isLoggedIn) {
    requireLogin();
    return;
  }
  // 已有其他报名，飞行员或另一席位：提示将被替换
  if (my.value.signed) {
    const ok = await confirmModal({
      title: '变更报名',
      confirmText: '确认报名该席位',
      message: `将「${my.value.role === 'atc' ? '已占用的席位' : '飞行员报名'}」变更为席位 ${pos.name}？原报名会被替换。`,
    });
    if (!ok) return;
  }
  posBusyId.value = pos.id;
  try {
    await api.post(`/api/events/${eventId.value}/signup`, { role: 'atc', positionId: pos.id });
    showToast(`已报名席位 ${pos.name}`);
    await load();
  } catch (err) {
    showToast(err.message);
  }
  posBusyId.value = 0;
}

async function cancelSignup() {
  if (posBusyId.value || pilotBusy.value) return;
  if (!auth.isLoggedIn) {
    requireLogin();
    return;
  }
  const roleText = my.value.role === 'atc'
    ? `管制员席位，${atcPositions.value.find((p) => p.id === my.value.positionId)?.name || my.value.positionId}`
    : `飞行员，${my.value.callsign} / ${my.value.aircraft || '机型未填'}`;
  const ok = await confirmModal({
    title: '取消报名',
    danger: true,
    confirmText: '取消报名',
    message: `确认取消本次活动的${roleText}报名？`,
  });
  if (!ok) return;
  posBusyId.value = -1;
  try {
    await api.post(`/api/events/${eventId.value}/cancel`, {});
    showToast('已取消报名');
    await load();
  } catch (err) {
    showToast(err.message);
  }
  posBusyId.value = 0;
}

/* 席位状态：本人占用 / 已被他人占用 / 空闲 */
function posState(pos) {
  if (my.value.signed && my.value.role === 'atc' && my.value.positionId === pos.id) return 'mine';
  return pos.taken ? 'taken' : 'free';
}

onMounted(() => {
  load();
  countdownTimer = setInterval(tickCountdown, 1000);
});
onBeforeUnmount(() => {
  clearInterval(countdownTimer);
  if (posterUrl.value) URL.revokeObjectURL(posterUrl.value);
});
</script>

<template>
  <div class="page">
    <div v-if="loading" class="loading">加载中…</div>
    <template v-else-if="event">
      <!-- 顶部 header 卡 -->
      <div class="card glass header-card">
        <div class="header-left">
          <router-link class="back-link" to="/events">
            <Icon name="chevron" :size="14" style="transform: rotate(90deg)" /> 返回活动
          </router-link>
          <div class="header-title">{{ event.title }}</div>
          <div class="header-sub">
            {{ depFull }}
            -
            {{ arrFull }}
          </div>
        </div>
        <span class="tag" :class="statusMeta.tag">{{ statusMeta.text }}</span>
      </div>

      <!-- 中部两栏：左海报 / 右信息卡 -->
      <div class="brief-top">
        <div class="poster card glass">
          <img v-if="posterUrl" :src="posterUrl" alt="活动海报" />
          <div v-else class="poster-fallback">{{ event.title }}</div>
        </div>

        <div class="card glass info-card">
          <div class="card-title info-title"><Icon name="file" :size="16" /> 活动简报</div>
          <div class="kv-list">
            <div class="kv-row">
              <div class="kv-key">活动时间</div>
              <div class="kv-val">{{ fmtTime(event.start_time) }} ~ {{ fmtTime(event.end_time) }}</div>
            </div>
            <div class="kv-row">
              <div class="kv-key">起飞机场</div>
              <div class="kv-val">{{ depFull }}</div>
            </div>
            <div class="kv-row">
              <div class="kv-key">到达机场</div>
              <div class="kv-val">{{ arrFull }}</div>
            </div>
            <div class="kv-row">
              <div class="kv-key">发布人</div>
              <div class="kv-val">{{ event.creator_cid || event.creator || '官方' }}</div>
            </div>
            <div v-if="event.route" class="kv-row">
              <div class="kv-key">航路</div>
              <div class="kv-val kv-wrap">{{ event.route }}</div>
            </div>
            <div v-if="event.distance_nm != null && event.distance_nm !== ''" class="kv-row">
              <div class="kv-key">飞行距离</div>
              <div class="kv-val">{{ event.distance_nm }} nm</div>
            </div>
            <div v-if="event.notams" class="kv-row">
              <div class="kv-key">NOTAMS</div>
              <div class="kv-val kv-wrap">{{ event.notams }}</div>
            </div>
            <!-- 报名操作：席位制 -->
            <div class="kv-row kv-actions">
              <div class="kv-key">报名操作</div>
              <div class="kv-val">
                <!-- 未登录：先去登录 -->
                <template v-if="!auth.isLoggedIn">
                  <button class="btn btn-primary btn-block" @click="requireLogin">登录后报名</button>
                </template>
                <!-- 已报名，飞行员：展示呼号/机型 + 取消报名-->
                <template v-else-if="my.signed && my.role !== 'atc'">
                  <div class="signed-line">
                    已报名，{{ my.callsign }} / {{ my.aircraft || '机型未填' }}
                  </div>
                  <div class="signed-actions">
                    <button v-if="signupOpen" class="btn btn-ghost btn-sm" @click="showPilotForm = !showPilotForm">
                      修改呼号/机型
                    </button>
                    <button v-if="signupOpen" class="btn btn-ghost btn-sm" @click="cancelSignup">取消报名</button>
                  </div>
                </template>
                <!-- 已报名，管制员：展示所占用席位 + 取消报名-->
                <template v-else-if="my.signed">
                  <div class="signed-line">
                    已报名管制席位
                    {{ atcPositions.find((p) => p.id === my.positionId)?.name || ('#' + my.positionId) }}
                  </div>
                  <div class="signed-actions">
                    <button v-if="signupOpen" class="btn btn-ghost btn-sm" @click="cancelSignup">取消报名</button>
                  </div>
                  <div class="signed-hint">可在下方席位列表更换席位</div>
                </template>
                <!-- 未报名：飞行员内联报名表单 -->
                <template v-else>
                  <div v-if="!signupOpen" class="signed-hint">该活动已停止报名</div>
                  <template v-else>
                    <button class="btn btn-primary btn-block" @click="showPilotForm = !showPilotForm">
                      {{ showPilotForm ? '收起飞行员报名' : '飞行员报名' }}
                    </button>
                    <form v-if="showPilotForm" class="pilot-form" @submit.prevent="signupPilot">
                      <input
                        v-model="pilotForm.callsign"
                        class="input"
                        maxlength="16"
                        placeholder="呼号，如 CUA1234"
                      />
                      <input
                        v-model="pilotForm.aircraft"
                        class="input"
                        maxlength="16"
                        placeholder="机型，如 A320"
                      />
                      <button class="btn btn-primary btn-block" type="submit" :disabled="pilotBusy">
                        {{ pilotBusy ? '提交中…' : '确认报名' }}
                      </button>
                    </form>
                  </template>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部统计卡一行 4 张，统一白卡-->
      <div class="brief-stats">
        <div class="card glass stat-card">
          <div class="stat-num">{{ pilotCount }}</div>
          <div class="stat-label">飞行员报名数</div>
        </div>
        <div class="card glass stat-card">
          <div class="stat-num">{{ atcCount }}</div>
          <div class="stat-label">管制员报名数</div>
        </div>
        <div class="card glass stat-card">
          <div class="stat-num stat-num-time">{{ countdown }}</div>
          <div class="stat-label">报名剩余时间</div>
        </div>
        <div class="card glass stat-card">
          <div class="stat-num stat-num-status">
            <span class="tag" :class="statusMeta.tag">{{ statusMeta.text }}</span>
          </div>
          <div class="stat-label">活动状态</div>
        </div>
      </div>

      <!-- 管制席位报名区，席位制-->
      <div v-if="atcPositions.length" class="card glass pos-card">
        <div class="card-title pos-title"><Icon name="radar" :size="16" /> 管制席位</div>
        <div class="pos-grid">
          <div
            v-for="pos in atcPositions"
            :key="pos.id"
            class="pos-item"
            :class="{ 'pos-disabled': posState(pos) === 'taken' }"
          >
            <div class="pos-head">
              <span class="pos-name">{{ pos.name }}</span>
              <span v-if="pos.rating" class="tag tag-blue">{{ pos.rating }}</span>
            </div>
            <div class="pos-freq">{{ pos.frequency || '频率待定' }}</div>
            <div class="pos-foot">
              <!-- 本人占用：可取消 -->
              <template v-if="posState(pos) === 'mine'">
                <span class="pos-state pos-state-mine">我占用</span>
                <button
                  v-if="signupOpen"
                  class="btn btn-ghost btn-sm"
                  :disabled="posBusyId === pos.id"
                  @click="cancelSignup"
                >取消报名</button>
              </template>
              <!-- 被他人占用：灰态 -->
              <template v-else-if="posState(pos) === 'taken'">
                <span class="pos-state">
                  {{ pos.taken.callsign || pos.taken.username }} · CID {{ pos.taken.cid }}
                </span>
              </template>
              <!-- 等级不达标：禁用并说明 -->
              <template v-else-if="pos.eligible === false">
                <span class="pos-state pos-state-mismatch">等级不达标</span>
              </template>
              <!-- 空闲：可报名 -->
              <template v-else>
                <span class="pos-state pos-state-free">空闲</span>
                <button
                  v-if="signupOpen"
                  class="btn btn-primary btn-sm"
                  :disabled="!!posBusyId"
                  @click="signupAtc(pos)"
                >{{ posBusyId === pos.id ? '报名中…' : '立即报名' }}</button>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 报名名单 -->
      <div class="card glass roster-card">
        <div class="roster-head">
          <div class="card-title">报名名单</div>
          <SegmentedTabs v-model="tab" :options="rosterTabs" />
        </div>
        <div v-if="!rosterList.length" class="empty">暂无{{ tab === 'atc' ? '管制员' : '飞行员' }}报名</div>
        <template v-else>
          <div v-for="(s, i) in rosterList" :key="i" class="list-item">
            <div class="list-main">
              <div class="list-title">
                <template v-if="tab === 'atc'">
                  <span v-if="s.position_name" class="tag tag-blue" style="margin-right: 8px">{{ s.position_name }}</span>
                  {{ s.callsign || s.username }}
                </template>
                <template v-else>{{ s.callsign || s.username }}</template>
              </div>
              <div class="list-sub">
                <template v-if="tab === 'atc'">{{ s.username }} · CID {{ s.cid }}</template>
                <template v-else>{{ s.aircraft || '机型未填' }} · {{ s.username }} · CID {{ s.cid }}</template>
              </div>
            </div>
            <div class="list-actions list-sub">{{ fmtTime(s.created_at) }}</div>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* ---------- 顶部 header 卡 ---------- */
.header-card {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 16px;
}
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--text-2);
  margin-bottom: 8px;
}
.back-link:hover { color: var(--blue); }
.header-title {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.4px;
  line-height: 1.25;
}
.header-sub {
  margin-top: 6px;
  color: var(--text-2);
  font-size: 14px;
}

/* ---------- 中部两栏，左 2/3 右 1/3，窄屏堆叠 ----------*/
.brief-top {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 900px) {
  .brief-top { grid-template-columns: 1fr; }
}
.poster {
  padding: 0;
  overflow: hidden;
  min-height: 300px;
  display: flex;
  flex-direction: column;
}
.poster img {
  width: 100%;
  flex: 1;
  min-height: 260px;
  object-fit: cover;
  display: block;
}
/* 海报图由管理后台「活动管理」维护，简报页只负责展示 */
/* 无图兜底：品牌蓝纯色块 + 居中标题白字，纯平，无渐变*/
.poster-fallback {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 32px;
  background: var(--blue);
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.4;
  border-radius: inherit;
}
.info-title {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 12px;
}

/* ---------- 键值对列表 ---------- */
.kv-list { font-size: 13.5px; }
.kv-row {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--surface);
}
.kv-row:last-child { border-bottom: none; padding-bottom: 2px; }
.kv-key {
  flex-shrink: 0;
  width: 72px;
  color: var(--gray);
  font-size: 12.5px;
  padding-top: 1px;
}
.kv-val { flex: 1; min-width: 0; color: var(--text); word-break: break-word; }
.kv-wrap { white-space: pre-wrap; }
.kv-actions { align-items: flex-start; }

/* ---------- 飞行员内联报名表单 / 已报名状态 ---------- */
.pilot-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}
.signed-line {
  font-size: 13.5px;
  color: var(--text);
  margin-bottom: 8px;
}
.signed-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.signed-hint {
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--gray);
}

/* ---------- 统计卡，统一白卡，窄屏 2 列 ----------*/
.brief-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 900px) {
  .brief-stats { grid-template-columns: repeat(2, 1fr); }
}
.stat-card { padding: 18px 16px; text-align: center; }
.stat-num {
  font-size: 26px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 4px;
  font-variant-numeric: tabular-nums;
}
.stat-num-time { letter-spacing: 1px; }
.stat-num-status { font-size: 14px; }
.stat-label { color: var(--gray); font-size: 12.5px; }

/* ---------- 管制席位报名区 ---------- */
.pos-card { margin-bottom: 16px; }
.pos-title {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 12px;
}
.pos-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.pos-item {
  border: 1px solid var(--border);
  border-radius: var(--radius, 12px);
  padding: 12px 14px;
  background: var(--surface-solid);
}
/* 被他人占用：整卡灰态 */
.pos-item.pos-disabled { opacity: 0.62; }
.pos-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.pos-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}
.pos-freq {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.pos-foot {
  margin-top: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.pos-state {
  font-size: 12.5px;
  color: var(--gray);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pos-state-free { color: var(--blue); }
.pos-state-mine { color: var(--text); }
.pos-state-mismatch { color: var(--red); }

/* ---------- 报名名单 ---------- */
.roster-card { margin-bottom: 16px; }
.roster-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
</style>
