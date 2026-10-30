<script setup>
/**
 * 可复用的「主次可切换」模块化仪表盘，管理后台 · 数据概览专用，见交接文档 §22/§24/§24.7。
 *
 * 模块集，2026-10-10 站长定稿：后台指标，默认主模块，原数据概览内容、
 * 站内活跃趋势，底部通栏、最近飞行、飞行时长排行、社区公告 —— 共 5 个。
 * 活动月历 / 我的飞行数据 / 快捷入口 已按要求移除。
 *
 * 槽位固定、模块流动：main 槽位，内容区 3/4 宽、约 60vh 高里的模块就是主模块，
 * 拖拽交换后主次层级随槽位切换；布局存 localStorage 并做完整性校验，
 * 模块集变化导致旧数据非法时，回退默认并写回存储，真正重迁移。
 */
import { ref, reactive, onBeforeUnmount } from 'vue';
import { api } from '../api.js';
import Icon from './Icon.vue';
import UserAvatar from './UserAvatar.vue';
import DashTrendChart from './DashTrendChart.vue';
import TrendLine from './TrendLine.vue';

const data = ref(null);
const trend = ref(null);
const metric = ref('requests');

/* 后台指标模块的数据，原数据概览页内容：非管理员访问会 403，模块内降级为提示*/
const adminStats = ref(null);
const adminTrend = ref([]);
const adminError = ref('');

Promise.allSettled([
  api.get('/api/dashboard'),
  api.get('/api/dashboard/trend?days=14'),
  api.get('/api/admin/stats'),
]).then(([d, t, a]) => {
  if (d.status === 'fulfilled') data.value = d.value;
  if (t.status === 'fulfilled') trend.value = t.value;
  if (a.status === 'fulfilled') {
    adminStats.value = a.value.stats;
    adminTrend.value = a.value.trend || [];
  } else {
    adminError.value = a.reason?.message || '需要管理员权限';
  }
});

/* ---------- 模块与槽位 ---------- */
const MODULE_TITLE = {
  admin: '后台指标',
  chart: '站内活跃趋势',
  flights: '最近飞行',
  rank: '飞行时长排行',
  notices: '社区公告',
};
const MODULE_ICON = {
  admin: 'shield',
  chart: 'trending',
  flights: 'plane',
  rank: 'crown',
  notices: 'megaphone',
};
const SLOT_ORDER = ['main', 'side1', 'side2', 'side3', 'wide'];
const DEFAULT_LAYOUT = {
  main: 'admin',
  side1: 'rank',
  side2: 'flights',
  side3: 'notices',
  wide: 'chart',
};
const LAYOUT_KEY = 'ctyfly_dash_layout';

/* 校验：槽位齐全、且每个模块恰好出现一次；否则回退默认并写回存储
   模块集变化后旧数据自动重迁移，不会带着非法布局渲染*/
function validLayout(o) {
  if (!o || typeof o !== 'object') return null;
  const all = Object.keys(MODULE_TITLE);
  const got = SLOT_ORDER.map((s) => o[s]);
  if (got.some((k) => !all.includes(k))) return null;
  if (new Set(got).size !== all.length) return null;
  return o;
}
function loadLayout() {
  try {
    const parsed = validLayout(JSON.parse(localStorage.getItem(LAYOUT_KEY) || 'null'));
    if (parsed) return parsed;
  } catch { /* 忽略坏数据 */ }
  const fallback = { ...DEFAULT_LAYOUT };
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(fallback)); } catch { /* 忽略 */ }
  return fallback;
}
const slots = reactive(loadLayout());
function saveLayout() {
  try { localStorage.setItem(LAYOUT_KEY, JSON.stringify({ ...slots })); } catch { /* 忽略 */ }
}
function resetLayout() {
  Object.assign(slots, DEFAULT_LAYOUT);
  saveLayout();
}
function swapSlots(a, b) {
  const t = slots[a];
  slots[a] = slots[b];
  slots[b] = t;
  saveLayout();
}
function makeMain(slot) {
  if (slot !== 'main' && slots[slot]) swapSlots(slot, 'main');
}

/* ---------- 拖拽换位 ---------- */
const drag = ref(null);            // { from, key, title }
const ghost = ref({ x: 0, y: 0 });
const dropSlot = ref('');

function slotRects() {
  const map = {};
  for (const el of document.querySelectorAll('.dash-slot')) {
    map[el.dataset.slot] = el.getBoundingClientRect();
  }
  return map;
}
/* 每次移动都重新量：槽位高度会随换位/窗口变化，缓存会指错位置 */
function hitSlot(x, y) {
  const map = slotRects();
  for (const [key, r] of Object.entries(map)) {
    if (r.width && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return key;
  }
  return '';
}
function startDrag(ev, slot) {
  if (ev.pointerType === 'mouse' && ev.button !== 0) return;
  ev.preventDefault();
  drag.value = { from: slot, key: slots[slot], title: MODULE_TITLE[slots[slot]] };
  ghost.value = { x: ev.clientX, y: ev.clientY };
  dropSlot.value = '';
  window.addEventListener('pointermove', onDragMove);
  window.addEventListener('pointerup', onDragEnd);
  window.addEventListener('pointercancel', onDragEnd);
  window.addEventListener('keydown', onDragKey);
  document.body.style.userSelect = 'none';
}
function onDragMove(ev) {
  if (!drag.value) return;
  ghost.value = { x: ev.clientX, y: ev.clientY };
  const hit = hitSlot(ev.clientX, ev.clientY);
  dropSlot.value = hit && hit !== drag.value.from ? hit : '';
}
function onDragKey(ev) {
  if (ev.key === 'Escape') cleanupDrag();
}
function onDragEnd() {
  if (!drag.value) return;
  const from = drag.value.from;
  const to = dropSlot.value;
  cleanupDrag();
  if (to && to !== from) swapSlots(from, to);
}
function cleanupDrag() {
  drag.value = null;
  dropSlot.value = '';
  window.removeEventListener('pointermove', onDragMove);
  window.removeEventListener('pointerup', onDragEnd);
  window.removeEventListener('pointercancel', onDragEnd);
  window.removeEventListener('keydown', onDragKey);
  document.body.style.userSelect = 'none';
}
onBeforeUnmount(cleanupDrag);
</script>

<template>
  <!-- 工具栏：resetLayout 此前是无调用点的死代码，ESLint no-unused-vars 抓出，
       说明「恢复默认布局」的入口一直没接上 —— 用户拖乱之后只能清 localStorage 才能复原。
       2026-10-11 补上按钮；resetLayout 本身已经会 saveLayout 持久化，行为正确。-->
  <div class="dash-toolbar">
    <span class="dash-hint">拖动模块标题栏右侧的把手可换位，按 Esc 取消本次拖动</span>
    <button class="btn btn-ghost btn-sm" type="button" @click="resetLayout">
      <Icon name="grid" :size="13" /> 恢复默认布局
    </button>
  </div>
  <div class="dash-grid" :class="{ 'is-dragging': !!drag }">
    <section
      v-for="slotKey in SLOT_ORDER"
      :key="slotKey"
      class="dash-slot"
      :class="[`slot-${slotKey}`, { 'is-drop': dropSlot === slotKey, 'is-source': drag && drag.from === slotKey }]"
      :data-slot="slotKey"
    >
      <div class="dash-mod glass" :class="{ 'is-main': slotKey === 'main' }">
        <div class="dash-mod-head">
          <div class="dash-mod-title">
            <Icon :name="MODULE_ICON[slots[slotKey]]" :size="16" />
            <span>{{ MODULE_TITLE[slots[slotKey]] }}</span>
            <span v-if="slotKey === 'main'" class="dash-main-tag">主模块</span>
          </div>
          <div class="dash-mod-tools">
            <button v-if="slotKey !== 'main'" class="dash-tool" @click="makeMain(slotKey)">设为主模块</button>
            <button
              class="dash-grip"
              type="button"
              :aria-label="`拖动「${MODULE_TITLE[slots[slotKey]]}」换位`"
              @pointerdown="startDrag($event, slotKey)"
            >
              <i></i><i></i><i></i>
            </button>
          </div>
        </div>

        <div class="dash-mod-body" :class="{ 'is-chart': slots[slotKey] === 'chart' }">
          <!-- ① 后台指标，原数据概览页内容，默认主模块-->
          <template v-if="slots[slotKey] === 'admin'">
            <div v-if="adminError" class="empty">{{ adminError }}，后台指标仅管理员可见</div>
            <template v-else-if="adminStats">
              <div class="mod-grid mod-grid-stat">
                <div class="stat"><div class="stat-num">{{ adminStats.total }}</div><div class="stat-label">注册用户</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.today }}</div><div class="stat-label">今日新增</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.controllers }}</div><div class="stat-label">在职管制员</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.pendingApps }}</div><div class="stat-label">待审申请</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.pendingApprovals }}</div><div class="stat-label">待审批，双人复核</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.openTickets }}</div><div class="stat-label">未关工单</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.events }}</div><div class="stat-label">进行中活动</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.airlines }}</div><div class="stat-label">在营虚拟航司</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.todayLogins }}</div><div class="stat-label">今日成功登录</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.failedLogins }}</div><div class="stat-label">24h 登录失败</div></div>
                <div class="stat"><div class="stat-num">{{ adminStats.riskEvents }}</div><div class="stat-label">24h 风险事件</div></div>
              </div>
              <div class="admin-trend">
                <div class="card-title">近 7 天注册趋势</div>
                <div v-if="!adminTrend.length" class="empty">暂无数据</div>
                <TrendLine v-else :points="adminTrend" />
              </div>
            </template>
            <div v-else class="loading">加载中…</div>
          </template>

          <!-- ② 核心图表，底部通栏-->
          <template v-else-if="slots[slotKey] === 'chart'">
            <div class="chart-switch">
              <button
                v-for="m in [{ k: 'requests', t: '请求量' }, { k: 'reports', t: '飞行报告' }, { k: 'users', t: '新增用户' }]"
                :key="m.k"
                class="btn btn-sm"
                :class="metric === m.k ? 'btn-primary' : 'btn-ghost'"
                @click="metric = m.k"
              >{{ m.t }}</button>
              <span v-if="trend" class="chart-totals">
                近 14 天 · 飞行 {{ trend.totals.hours }} h · 报告 {{ trend.totals.reports }} 份 · 新增 {{ trend.totals.users }} 人
              </span>
            </div>
            <DashTrendChart :series="trend?.days || []" :metric="metric" />
          </template>

          <!-- ③ 最近飞行 -->
          <template v-else-if="slots[slotKey] === 'flights'">
            <template v-if="data.recentFlights.length">
              <div v-for="(f, i) in data.recentFlights" :key="i" class="rank-row">
                <UserAvatar :user="f" :size="30" />
                <div class="rank-main">
                  <div class="rank-name">{{ f.username }} · {{ f.dep }} → {{ f.arr }}</div>
                  <div class="rank-cid">{{ f.flight_date }}</div>
                </div>
                <span class="rank-hours">{{ f.hours }} h</span>
              </div>
            </template>
            <div v-else class="empty">还没有飞行记录</div>
          </template>

          <!-- ④ 飞行时长排行 -->
          <template v-else-if="slots[slotKey] === 'rank'">
            <template v-if="data.topPilots.length">
              <div v-for="(p, i) in data.topPilots" :key="p.cid" class="rank-row">
                <span class="rank-no" :class="`rank-${i + 1}`">{{ i + 1 }}</span>
                <UserAvatar :user="p" :size="30" />
                <div class="rank-main">
                  <div class="rank-name">{{ p.username }}</div>
                  <div class="rank-cid">CID {{ p.cid }}</div>
                </div>
                <span class="rank-hours">{{ p.total_hours?.toFixed(1) }} h</span>
              </div>
            </template>
            <div v-else class="empty">还没有飞行记录</div>
          </template>

          <!-- ⑤ 社区公告 -->
          <template v-else-if="slots[slotKey] === 'notices'">
            <div v-for="n in data.notices" :key="n.id" class="notice-row">
              <div class="notice-title">{{ n.title }}</div>
              <time class="notice-date">{{ n.created_at?.slice(0, 10) }}</time>
            </div>
            <div v-if="!data.notices.length" class="empty">
              <div class="empty-icon"><Icon name="megaphone" :size="22" /></div>
              <div>暂无公告</div>
            </div>
          </template>
        </div>
      </div>
    </section>
  </div>

  <!-- 拖拽时跟随指针的幽灵卡片 -->
  <div v-if="drag" class="dash-ghost" :style="{ left: `${ghost.x}px`, top: `${ghost.y}px` }">
    {{ drag.title }}
  </div>
</template>

<style scoped>
/* ---- 模块栅格：主槽位占 3/4 宽、约 60vh 高，首屏一半以上，通栏图表在底部 ----*/
/* 工具栏，恢复默认布局入口*/
.dash-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.dash-hint { font-size: 12.5px; color: var(--gray); }

.dash-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.slot-main { grid-column: 1 / 4; grid-row: 1 / 4; min-height: 60vh; }
.slot-side1 { grid-column: 4; grid-row: 1; }
.slot-side2 { grid-column: 4; grid-row: 2; }
.slot-side3 { grid-column: 4; grid-row: 3; }
.slot-wide { grid-column: 1 / 5; grid-row: 4; min-height: 300px; }

.dash-slot { min-width: 0; display: flex; }
.dash-slot.is-source { opacity: 0.45; }

/* 模块卡 */
.dash-mod {
  padding: 18px 20px 20px;
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  transition: box-shadow 0.18s ease, border-color 0.18s ease;
}
.dash-mod.is-main { padding: 20px 24px 24px; }
.dash-slot.is-drop .dash-mod {
  border-color: rgba(10, 132, 255, 0.55);
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.16), var(--shadow);
}
.dash-grid.is-dragging .dash-mod { transition: none; }

.dash-mod-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.dash-mod-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.2px;
  min-width: 0;
}
.dash-main-tag {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--blue);
  background: rgba(10, 132, 255, 0.12);
  border-radius: 6px;
  padding: 2px 7px;
}
.dash-mod-tools { margin-left: auto; display: flex; align-items: center; gap: 6px; }
.dash-tool {
  border: none;
  background: transparent;
  color: var(--text-2);
  font-size: 12px;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 8px;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease;
}
.dash-mod:hover .dash-tool, .dash-tool:focus-visible { opacity: 1; }
.dash-tool:hover { color: var(--blue); background: rgba(10, 132, 255, 0.1); }

/* 拖拽手柄：三点竖排，不用图标字体，纯 CSS*/
.dash-grip {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: 7px;
  background: transparent;
  cursor: grab;
  touch-action: none;
}
.dash-grip i { width: 3px; height: 3px; border-radius: 50%; background: var(--gray); display: block; }
.dash-grip:hover { background: var(--surface); }
.dash-grip:active { cursor: grabbing; }

.dash-mod-body { flex: 1; min-height: 0; min-width: 0; display: flex; flex-direction: column; }
.dash-mod-body.is-chart { gap: 8px; }

/* 拖拽时跟随指针的幽灵卡片 */
.dash-ghost {
  position: fixed;
  z-index: 60;
  transform: translate(-50%, -50%);
  padding: 8px 14px;
  border-radius: 10px;
  background: var(--blue);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  pointer-events: none;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
}

/* 后台指标模块的统计卡栅格：按容器宽度自适应 */
.mod-grid { display: grid; gap: 12px; }
.mod-grid-stat { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.admin-trend { margin-top: 16px; }

/* 图表模块的切换与合计行 */
.chart-switch { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.chart-totals { font-size: 12.5px; color: var(--text-2); margin-left: auto; }

/* ---- 排行榜 ---- */
.rank-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 2px;
  border-bottom: 1px solid var(--border);
}
.rank-row:last-child { border-bottom: none; }
.rank-no {
  width: 22px;
  height: 22px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  background: var(--surface);
  color: var(--text-2);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.rank-1 { background: rgba(255, 159, 10, 0.18); color: #b26a00; }
.rank-2 { background: rgba(148, 163, 184, 0.22); color: #475569; }
.rank-3 { background: rgba(180, 121, 73, 0.18); color: #9a5b2d; }
.rank-main { min-width: 0; flex: 1; }
.rank-name { font-size: 13.5px; font-weight: 500; }
.rank-cid { font-size: 11.5px; color: var(--gray); }
.rank-hours {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

/* ---- 公告行 ---- */
.notice-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 12px 2px;
  border-bottom: 1px solid var(--border);
}
.notice-row:last-child { border-bottom: none; }
.notice-title {
  font-size: 14px;
  font-weight: 500;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.notice-date {
  font-size: 12.5px;
  color: var(--gray);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  flex-shrink: 0;
}

/* ---- 窄屏：全部单列堆叠，主模块在最前，拖拽仍然可用 ---- */
@media (max-width: 1100px) {
  .dash-grid { grid-template-columns: minmax(0, 1fr); }
  .slot-main,
  .slot-side1, .slot-side2, .slot-side3,
  .slot-wide {
    grid-column: 1;
    grid-row: auto;
  }
  .slot-main { min-height: 52vh; }
}
</style>
