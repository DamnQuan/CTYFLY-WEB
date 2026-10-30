<script setup>
/**
 * 统一风格日期选择器，替代原生 date / datetime-local / month 控件
 * mode: date → YYYY-MM-DD ｜ datetime → YYYY-MM-DDTHH:mm ｜ month → YYYY-MM
 * 面板 Teleport 到 body，避免被相邻卡片的层叠上下文遮挡，按触发框定位
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import Icon from './Icon.vue';

const props = defineProps({
  modelValue: { type: String, default: '' },
  mode: { type: String, default: 'date' },
  placeholder: { type: String, default: '选择日期' },
  clearable: { type: Boolean, default: true },
});
const emit = defineEmits(['update:modelValue']);

const WEEK = ['一', '二', '三', '四', '五', '六', '日'];

const rootEl = ref(null);
const triggerEl = ref(null);
const panelEl = ref(null);
const open = ref(false);
const panel = ref('day'); // day | month | year
const panelStyle = ref({});

const now = new Date();
const viewYear = ref(now.getFullYear());
const viewMonth = ref(now.getMonth());
const yearPage = ref(Math.floor(now.getFullYear() / 12) * 12);
const picked = ref({ y: null, mo: null, d: null });
const hour = ref('00');
const minute = ref('00');

const pad = (n) => String(n).padStart(2, '0');

function parse(value) {
  const m = String(value || '').match(/^(\d{4})-(\d{2})(?:-(\d{2}))?(?:[T ](\d{2}):(\d{2}))?/);
  if (!m) return null;
  return { y: +m[1], mo: +m[2], d: m[3] ? +m[3] : null, h: m[4] ?? '00', mi: m[5] ?? '00' };
}

function syncFromValue() {
  const v = parse(props.modelValue);
  if (v) {
    viewYear.value = v.y;
    viewMonth.value = v.mo - 1;
    yearPage.value = Math.floor(v.y / 12) * 12;
    picked.value = { y: v.y, mo: v.mo, d: v.d };
    hour.value = v.h;
    minute.value = v.mi;
  } else {
    const d = new Date();
    viewYear.value = d.getFullYear();
    viewMonth.value = d.getMonth();
    yearPage.value = Math.floor(d.getFullYear() / 12) * 12;
    picked.value = { y: null, mo: null, d: null };
    hour.value = pad(d.getHours());
    minute.value = '00';
  }
}
syncFromValue();
watch(() => props.modelValue, syncFromValue);

const displayText = computed(() => {
  if (!props.modelValue) return '';
  const v = parse(props.modelValue);
  if (!v) return props.modelValue;
  if (props.mode === 'month') return `${v.y}-${pad(v.mo)}`;
  if (props.mode === 'datetime') return `${v.y}-${pad(v.mo)}-${pad(v.d)} ${v.h}:${v.mi}`;
  return `${v.y}-${pad(v.mo)}-${pad(v.d)}`;
});

const monthLabel = computed(() => `${viewYear.value} 年 ${viewMonth.value + 1} 月`);
const days = computed(() => {
  const first = new Date(viewYear.value, viewMonth.value, 1);
  const offset = (first.getDay() + 6) % 7;
  const total = new Date(viewYear.value, viewMonth.value + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < offset; i++) cells.push({ empty: true, key: `e${i}` });
  for (let d = 1; d <= total; d++) {
    cells.push({
      empty: false, d, key: `d${d}`,
      today: isToday(viewYear.value, viewMonth.value + 1, d),
      selected: picked.value.y === viewYear.value && picked.value.mo === viewMonth.value + 1 && picked.value.d === d,
    });
  }
  return cells;
});
const years = computed(() => Array.from({ length: 12 }, (_, i) => yearPage.value + i));
const months = computed(() => Array.from({ length: 12 }, (_, i) => i + 1));

function isToday(y, mo, d) {
  const t = new Date();
  return t.getFullYear() === y && t.getMonth() + 1 === mo && t.getDate() === d;
}
function isSelectedMonth(mo) {
  return picked.value.y === viewYear.value && picked.value.mo === mo;
}

/* ---------- 定位：Teleport 到 body 后按触发框计算 ---------- */
function updatePosition() {
  const rect = triggerEl.value?.getBoundingClientRect();
  if (!rect) return;
  const width = Math.max(rect.width, 288);
  const panelH = props.mode === 'datetime' ? 440 : 360;
  let left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
  let top;
  if (window.innerHeight - rect.bottom < panelH && rect.top > panelH) {
    top = Math.max(8, rect.top - panelH - 8); // 上方展开
  } else {
    top = rect.bottom + 8;
  }
  panelStyle.value = { left: `${left}px`, top: `${top}px`, width: `${width}px` };
}

function toggle() {
  open.value = !open.value;
  if (open.value) {
    panel.value = props.mode === 'month' ? 'month' : 'day';
    syncFromValue();
    nextTick(updatePosition);
  }
}
function onWindowChange() {
  if (open.value) updatePosition();
}
onMounted(() => {
  window.addEventListener('scroll', onWindowChange, true);
  window.addEventListener('resize', onWindowChange);
});
onUnmounted(() => {
  window.removeEventListener('scroll', onWindowChange, true);
  window.removeEventListener('resize', onWindowChange);
});

function prevMonth() {
  if (viewMonth.value === 0) { viewMonth.value = 11; viewYear.value -= 1; } else viewMonth.value -= 1;
}
function nextMonth() {
  if (viewMonth.value === 11) { viewMonth.value = 0; viewYear.value += 1; } else viewMonth.value += 1;
}
function prevYearPage() { yearPage.value -= 12; }
function nextYearPage() { yearPage.value += 12; }

function commit(value) {
  emit('update:modelValue', value);
  open.value = false;
}

function pickDay(cell) {
  if (cell.empty) return;
  picked.value = { y: viewYear.value, mo: viewMonth.value + 1, d: cell.d };
  const base = `${viewYear.value}-${pad(viewMonth.value + 1)}-${pad(cell.d)}`;
  if (props.mode === 'datetime') return; // 等选定时间后确认
  commit(base);
}
function pickMonth(mo) {
  viewMonth.value = mo - 1;
  if (props.mode === 'month') return commit(`${viewYear.value}-${pad(mo)}`);
  panel.value = 'day';
}
function pickYear(y) {
  viewYear.value = y;
  panel.value = 'month';
}
function commitDateTime() {
  if (!picked.value.d) return;
  commit(`${picked.value.y}-${pad(picked.value.mo)}-${pad(picked.value.d)}T${hour.value}:${minute.value}`);
}
function clearValue() {
  emit('update:modelValue', '');
  open.value = false;
}
function setToday() {
  const t = new Date();
  const base = `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;
  if (props.mode === 'month') return commit(`${t.getFullYear()}-${pad(t.getMonth() + 1)}`);
  if (props.mode === 'datetime') {
    hour.value = pad(t.getHours());
    minute.value = '00';
    picked.value = { y: t.getFullYear(), mo: t.getMonth() + 1, d: t.getDate() };
    return commitDateTime();
  }
  commit(base);
}

function onDocClick(e) {
  if (!open.value) return;
  const t = e.target;
  if (rootEl.value?.contains(t) || panelEl.value?.contains(t)) return;
  open.value = false;
}
function onKey(e) {
  if (e.key === 'Escape') open.value = false;
}
onMounted(() => {
  document.addEventListener('mousedown', onDocClick);
  document.addEventListener('keydown', onKey);
});
onUnmounted(() => {
  document.removeEventListener('mousedown', onDocClick);
  document.removeEventListener('keydown', onKey);
});
</script>

<template>
  <div ref="rootEl" class="dp">
    <button ref="triggerEl" type="button" class="dp-trigger" :class="{ 'is-empty': !displayText }" @click="toggle">
      <span class="dp-value">{{ displayText || placeholder }}</span>
      <Icon name="calendar" :size="15" class="dp-icon" />
    </button>

    <Teleport to="body">
      <transition name="dp-pop">
        <div v-if="open" ref="panelEl" class="dp-panel" :style="panelStyle">
          <!-- 日视图 -->
          <template v-if="panel === 'day'">
            <div class="dp-head">
              <button type="button" class="dp-nav" @click="prevMonth"><Icon name="chevron" :size="14" style="transform: rotate(90deg)" /></button>
              <button type="button" class="dp-title" @click="panel = 'month'">{{ monthLabel }}</button>
              <button type="button" class="dp-nav" @click="nextMonth"><Icon name="chevron" :size="14" style="transform: rotate(-90deg)" /></button>
            </div>
            <div class="dp-week">
              <span v-for="w in WEEK" :key="w">{{ w }}</span>
            </div>
            <div class="dp-grid">
              <button
                v-for="c in days" :key="c.key" type="button"
                class="dp-day" :class="{ empty: c.empty, today: c.today, selected: c.selected }"
                :disabled="c.empty" @click="pickDay(c)"
              >{{ c.empty ? '' : c.d }}</button>
            </div>
          </template>

          <!-- 月视图 -->
          <template v-else-if="panel === 'month'">
            <div class="dp-head">
              <button type="button" class="dp-nav" @click="prevYearPage"><Icon name="chevron" :size="14" style="transform: rotate(90deg)" /></button>
              <button type="button" class="dp-title" @click="panel = 'year'">{{ viewYear }} 年</button>
              <button type="button" class="dp-nav" @click="nextYearPage"><Icon name="chevron" :size="14" style="transform: rotate(-90deg)" /></button>
            </div>
            <div class="dp-grid dp-grid-3">
              <button
                v-for="m in months" :key="m" type="button"
                class="dp-cell" :class="{ selected: isSelectedMonth(m) }" @click="pickMonth(m)"
              >{{ m }} 月</button>
            </div>
          </template>

          <!-- 年视图 -->
          <template v-else>
            <div class="dp-head">
              <button type="button" class="dp-nav" @click="prevYearPage"><Icon name="chevron" :size="14" style="transform: rotate(90deg)" /></button>
              <span class="dp-title static">{{ yearPage }} - {{ yearPage + 11 }}</span>
              <button type="button" class="dp-nav" @click="nextYearPage"><Icon name="chevron" :size="14" style="transform: rotate(-90deg)" /></button>
            </div>
            <div class="dp-grid dp-grid-3">
              <button
                v-for="y in years" :key="y" type="button"
                class="dp-cell" :class="{ selected: y === viewYear }" @click="pickYear(y)"
              >{{ y }}</button>
            </div>
          </template>

          <!-- 时间选择，datetime 模式：自绘滚动列表-->
          <div v-if="mode === 'datetime' && panel === 'day'" class="dp-time">
            <span class="dp-time-label">时间</span>
            <div class="dp-scroll">
              <button
                v-for="h in 24" :key="h" type="button" class="dp-time-item"
                :class="{ active: hour === pad(h - 1) }" @click="hour = pad(h - 1)"
              >{{ pad(h - 1) }}</button>
            </div>
            <span class="dp-colon">:</span>
            <div class="dp-scroll">
              <button
                v-for="m in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]" :key="m"
                type="button" class="dp-time-item" :class="{ active: minute === pad(m) }" @click="minute = pad(m)"
              >{{ pad(m) }}</button>
            </div>
          </div>

          <div class="dp-foot">
            <button type="button" class="dp-link" @click="setToday">{{ mode === 'month' ? '本月' : '今天' }}</button>
            <div style="display: flex; gap: 8px">
              <button v-if="clearable" type="button" class="dp-link muted" @click="clearValue">清除</button>
              <button v-if="mode === 'datetime' && panel === 'day'" type="button" class="dp-confirm" @click="commitDateTime">确定</button>
            </div>
          </div>
        </div>
      </transition>
    </Teleport>
  </div>
</template>

<style scoped>
.dp { position: relative; width: 100%; }

.dp-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 11px 14px;
  font-size: 15px;
  font-family: inherit;
  text-align: left;
  color: var(--text);
  background: var(--glass-strong);
  border: 1px solid var(--input-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.dp-trigger:focus,
.dp-trigger:hover { border-color: var(--blue); }
.dp-trigger:focus { box-shadow: 0 0 0 3.5px rgba(0, 113, 227, 0.18); outline: none; }
.dp-trigger.is-empty .dp-value { color: var(--gray); }
.dp-value { font-variant-numeric: tabular-nums; }
.dp-icon { color: var(--gray); flex-shrink: 0; }
</style>

<style>
/* 面板 Teleport 到 body，使用全局样式，不受卡片层叠上下文影响*/
.dp-panel {
  position: fixed;
  z-index: 1000;
  padding: 14px;
  background: var(--modal-bg);
  backdrop-filter: blur(28px) saturate(180%);
  -webkit-backdrop-filter: blur(28px) saturate(180%);
  border: 1px solid var(--glass-border);
  border-radius: 18px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.2);
}

.dp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 10px;
}
.dp-title {
  flex: 1;
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  cursor: pointer;
  padding: 4px;
  border-radius: 8px;
}
.dp-title:hover { background: var(--surface); }
.dp-title.static { cursor: default; }
.dp-nav {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
}
.dp-nav:hover { background: var(--surface); color: var(--text); }

.dp-week {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  margin-bottom: 4px;
}
.dp-week span {
  text-align: center;
  font-size: 11.5px;
  color: var(--gray);
  padding: 4px 0;
}

.dp-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
.dp-grid-3 { grid-template-columns: repeat(3, 1fr); gap: 6px; }

.dp-day, .dp-cell {
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  color: var(--text);
  border-radius: 9px;
  cursor: pointer;
  font-variant-numeric: tabular-nums;
  transition: background 0.12s ease, color 0.12s ease;
}
.dp-day { height: 32px; }
.dp-cell { height: 34px; }
.dp-day:hover, .dp-cell:hover { background: var(--surface-strong); }
.dp-day.empty { visibility: hidden; }
.dp-day.today { color: var(--blue); font-weight: 600; }
.dp-day.selected, .dp-cell.selected { background: var(--blue); color: #fff; font-weight: 600; }

.dp-time {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.dp-time-label { font-size: 12.5px; color: var(--text-2); margin: 6px 2px 0 0; flex-shrink: 0; }
.dp-colon { color: var(--text-2); line-height: 28px; }
.dp-scroll {
  flex: 1;
  max-height: 104px;
  overflow-y: auto;
  padding: 2px;
  border-radius: 10px;
  background: var(--surface);
}
.dp-time-item {
  display: block;
  width: 100%;
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  color: var(--text);
  padding: 5px 0;
  border-radius: 7px;
  cursor: pointer;
  font-variant-numeric: tabular-nums;
  transition: background 0.12s ease, color 0.12s ease;
}
.dp-time-item:hover { background: var(--surface-strong); }
.dp-time-item.active { background: var(--blue); color: #fff; font-weight: 600; }

.dp-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.dp-link {
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--blue);
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 8px;
}
.dp-link:hover { background: var(--surface); }
.dp-link.muted { color: var(--text-2); }
.dp-confirm {
  border: none;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 500;
  color: #fff;
  background: var(--blue);
  padding: 5px 14px;
  border-radius: 980px;
  cursor: pointer;
}
.dp-confirm:hover { background: var(--blue-hover); }

/* 弹出动画 */
.dp-pop-enter-active { transition: opacity 0.2s ease, transform 0.26s cubic-bezier(0.34, 1.4, 0.64, 1); }
.dp-pop-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.dp-pop-enter-from { opacity: 0; transform: translateY(-6px) scale(0.97); }
.dp-pop-leave-to { opacity: 0; transform: translateY(-4px) scale(0.98); }
</style>
