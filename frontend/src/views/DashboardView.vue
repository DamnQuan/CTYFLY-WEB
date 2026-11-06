<script setup>
import { ref, computed, onMounted } from 'vue';
import { api } from '../api.js';
import { useAuthStore } from '../stores/auth.js';
import { fmtTime, localDate } from '../utils.js';
import Icon from '../components/Icon.vue';
import UserAvatar from '../components/UserAvatar.vue';

const auth = useAuthStore();
const data = ref(null);
const loading = ref(true);

onMounted(async () => {
  try {
    data.value = await api.get('/api/dashboard');
  } catch (err) {
    /* 忽略，页面保持空态 */
  }
  loading.value = false;
});

function greeting() {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 11) return '早上好';
  if (h < 13) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

const me = computed(() => data.value?.me || null);
const todos = computed(() => data.value?.todos || []);
const recentFlights = computed(() => data.value?.recentFlights || []);

/* 快捷入口：紧凑文字链 */
const quickLinks = [
  { to: '/va/dispatch', label: '飞行签派', desc: '生成放行单' },
  { to: '/va/pirep', label: '提交报告', desc: 'ACARS 核验' },
  { to: '/events', label: '连飞活动', desc: '报名与日程' },
  { to: '/nav/airport-map', label: '机场地面图', desc: '全球 2090 机场' },
];

/* ---------- 活动月历 ---------- */
const calYear = ref(new Date().getFullYear());
const calMonth = ref(new Date().getMonth()); // 0-based
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

const monthEvents = computed(() => {
  const map = {};
  for (const e of data.value?.calendarEvents || []) {
    const day = (e.start_time || '').slice(0, 10);
    if (!day) continue;
    (map[day] = map[day] || []).push(e);
  }
  return map;
});

const calCells = computed(() => {
  const first = new Date(calYear.value, calMonth.value, 1);
  const cells = [];
  for (let i = first.getDay() - 1; i >= 0; i -= 1) {
    cells.push({ day: new Date(calYear.value, calMonth.value, 0).getDate() - i, dim: true, key: `p${i}` });
  }
  const days = new Date(calYear.value, calMonth.value + 1, 0).getDate();
  for (let d = 1; d <= days; d += 1) {
    const ds = `${calYear.value}-${String(calMonth.value + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    cells.push({ day: d, dim: false, key: ds, date: ds, events: monthEvents.value[ds] || [] });
  }
  while (cells.length % 7 !== 0) cells.push({ dim: true, key: `n${cells.length}` });
  return cells;
});

function calShift(delta) {
  const d = new Date(calYear.value, calMonth.value + delta, 1);
  calYear.value = d.getFullYear();
  calMonth.value = d.getMonth();
}

function calToday() {
  calYear.value = new Date().getFullYear();
  calMonth.value = new Date().getMonth();
}

const isThisMonth = computed(() => {
  const n = new Date();
  return n.getFullYear() === calYear.value && n.getMonth() === calMonth.value;
});

function hhmm(t) {
  return typeof t === 'string' && t.length >= 16 ? t.slice(11, 16) : '';
}
</script>

<template>
  <div>
    <div class="page">
    <!-- 欢迎区 -->
    <div class="dash-head">
      <UserAvatar class="dash-avatar" :user="auth.user" :size="56" />
      <div class="dash-id">
        <div class="dash-greeting">{{ greeting() }}，{{ auth.user?.username }}</div>
        <div class="dash-meta">
          <strong>CID {{ auth.user?.cid }}</strong>
          <span v-if="auth.user?.is_controller" class="tag tag-blue">管制员 {{ auth.user?.rating }}</span>
          <span v-else class="tag">飞行员 {{ auth.user?.pilot_rank }}</span>
          <template v-if="me?.airline">
            <span class="tag tag-blue">{{ me.airline.name }}（{{ me.airline.icao }}）</span>
            <span v-if="me.airline.position" class="tag">{{ me.airline.position }}</span>
          </template>
        </div>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <template v-else-if="data">
      <!-- 待办提醒条：只放当前用户能直接处理的事 -->
      <div v-if="todos.length" class="todo-strip">
        <a v-for="(t, i) in todos" :key="i" class="todo-item" :href="t.link">
          <span class="todo-dot"></span>{{ t.text }}
          <span class="todo-go">去处理 →</span>
        </a>
      </div>

      <!-- 社区公告：新公告默认置顶，放在仪表盘最上面 -->
      <div v-if="data.notices.length" class="glass card" style="margin-bottom: 16px">
        <div class="card-title"><Icon name="megaphone" :size="16" /> 社区公告</div>
        <div v-for="(n, i) in data.notices" :key="n.id" class="notice-row">
          <div class="notice-main">
            <span v-if="i === 0" class="tag tag-blue" style="margin-right: 8px">最新</span>
            <span class="notice-title">{{ n.title }}</span>
          </div>
          <time class="notice-date">{{ n.created_at?.slice(0, 10) }}</time>
        </div>
      </div>

      <!-- 我的飞行数据 -->
      <div class="grid grid-4">
        <div class="stat">
          <div class="stat-num">{{ me ? me.hours.toFixed(1) : '0.0' }}<span class="stat-unit">h</span></div>
          <div class="stat-label">累计时长</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ me?.flights ?? 0 }}</div>
          <div class="stat-label">已通过航班</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ (me?.balance ?? 0).toLocaleString() }}</div>
          <div class="stat-label">钱包余额</div>
        </div>
        <div class="stat">
          <div class="stat-num stat-sm">{{ me?.airline ? me.airline.name : '未加入' }}</div>
          <div class="stat-label">所在航司{{ me?.airline?.position ? ' · ' + me.airline.position : '' }}</div>
        </div>
      </div>

      <!-- 快捷入口：紧凑文字链 -->
      <div class="grid grid-4" style="margin-top: 16px">
        <router-link v-for="q in quickLinks" :key="q.to" :to="q.to" class="glass card quick-card">
          <div class="quick-label">{{ q.label }} <span class="quick-arrow">→</span></div>
          <div class="quick-desc">{{ q.desc }}</div>
        </router-link>
      </div>

      <!-- 活动月历 -->
      <div class="glass card" style="margin-top: 16px">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 12px">
          <div class="card-title" style="margin: 0"><Icon name="calendar" :size="16" /> 活动月历</div>
          <div style="display: flex; align-items: center; gap: 6px">
            <button class="btn btn-ghost btn-sm" @click="calShift(-1)" aria-label="上个月">‹</button>
            <span class="cal-month">{{ calYear }} 年 {{ calMonth + 1 }} 月</span>
            <button class="btn btn-ghost btn-sm" @click="calShift(1)" aria-label="下个月">›</button>
            <button class="btn btn-ghost btn-sm" :class="{ 'btn-primary': !isThisMonth }" @click="calToday">今天</button>
          </div>
        </div>
        <div class="cal-grid">
          <div v-for="w in WEEKDAYS" :key="w" class="cal-weekday">{{ w }}</div>
          <div v-for="cell in calCells" :key="cell.key" class="cal-cell" :class="{ 'cal-dim': cell.dim, 'cal-today': cell.date === localDate() }">
            <div v-if="cell.day" class="cal-day">{{ cell.day }}</div>
            <div v-for="(e, i) in cell.events || []" :key="i" class="cal-event" :class="`cal-${e.status || 'upcoming'}`" :title="`${e.title}（${e.dep} → ${e.arr}）`">
              <span class="cal-event-time">{{ hhmm(e.start_time) }}</span>
              <span class="cal-event-title">{{ e.title }}</span>
            </div>
          </div>
        </div>
        <div class="card-sub" style="margin-top: 10px; display: flex; gap: 14px; flex-wrap: wrap">
          <span><span class="cal-dot cal-upcoming"></span>报名中</span>
          <span><span class="cal-dot cal-ongoing"></span>进行中</span>
          <span><span class="cal-dot cal-done"></span>已结束</span>
        </div>
      </div>

      <div class="grid grid-2" style="margin-top: 16px">
        <!-- 最近飞行记录 -->
        <div class="glass card">
          <div class="card-title"><Icon name="trending" :size="16" /> 最近飞行</div>
          <template v-if="recentFlights.length">
            <div v-for="(f, i) in recentFlights" :key="i" class="rank-row">
              <UserAvatar :user="f" :size="30" />
              <div class="rank-main">
                <div class="rank-name">{{ f.username }} · {{ f.dep }} → {{ f.arr }}</div>
                <div class="rank-cid">{{ f.flight_date }}</div>
              </div>
              <span class="rank-hours">{{ f.hours }} h</span>
            </div>
          </template>
          <div v-else class="empty">暂无飞行记录，从飞行签派页开始第一次飞行</div>
        </div>

        <!-- 飞行时长排行榜 -->
        <div class="glass card">
          <div class="card-title"><Icon name="trending" :size="16" /> 飞行时长排行</div>
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
          <div v-else class="empty">暂无飞行数据</div>
        </div>
      </div>

      <div class="glass card" style="margin-top: 16px">
        <!-- 我报名的活动 -->
        <div class="card-title"><Icon name="calendar" :size="16" /> 我报名的活动</div>
        <template v-if="data.mySignups.length">
          <div v-for="(e, i) in data.mySignups" :key="i" class="row">
            <div class="row-main">
              <div class="row-title">{{ e.title }}</div>
              <div class="row-meta">
                <span class="tag tag-blue">{{ e.dep }} → {{ e.arr }}</span>
                <time>{{ fmtTime(e.start_time) }}</time>
              </div>
            </div>
          </div>
        </template>
        <div v-else class="empty">
          <div class="empty-icon"><Icon name="calendar" :size="22" /></div>
          <div>暂无报名活动，去活动页看看排期</div>
        </div>
      </div>

      <!-- 平台概览，次要信息收在页脚行-->
      <div class="card-sub" style="text-align: center; margin-top: 18px">
        平台概览 · 注册用户 {{ data.counters.totalUsers }} · 管制员 {{ data.counters.totalControllers }} · 当前在线 {{ data.counters.onlineUsers }} · 进行中活动 {{ data.upcomingEvents.length }}
      </div>
    </template>
  </div>
  </div>
</template>

<style scoped>
/* ---- 欢迎区 ---- */
.dash-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 26px;
}
.dash-avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid rgba(255, 255, 255, 0.8);
  box-shadow: var(--shadow);
  flex-shrink: 0;
}
.dash-id { min-width: 0; }
.dash-greeting {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.4px;
  line-height: 1.3;
}
.dash-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 5px;
  font-size: 14px;
  color: var(--text-2);
}
.dash-meta strong { color: var(--text); font-weight: 600; letter-spacing: 0.2px; }

/* ---- 待办提醒条 ---- */
.todo-strip { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.todo-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 16px;
  border-radius: 12px;
  background: var(--glass-strong);
  border: 1px solid rgba(255, 159, 10, 0.35);
  color: var(--text);
  font-size: 13.5px;
  text-decoration: none;
  transition: border-color 0.15s ease;
}
.todo-item:hover { border-color: var(--orange); }
.todo-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--orange); flex-shrink: 0; }
.todo-go { margin-left: auto; color: var(--blue); font-size: 12.5px; flex-shrink: 0; }

/* ---- 快捷入口：紧凑文字链，无图标块 ----*/
.quick-card {
  text-decoration: none;
  padding: 14px 18px;
  transition: border-color 0.18s ease;
}
.quick-card:hover { border-color: rgba(10, 132, 255, 0.45); }
.quick-label { font-size: 14.5px; font-weight: 600; color: var(--text); }
.quick-arrow { color: var(--text-2); font-weight: 400; margin-left: 2px; transition: color 0.15s ease, margin-left 0.15s ease; }
.quick-card:hover .quick-arrow { color: var(--blue); margin-left: 6px; }
.quick-desc { font-size: 12.5px; color: var(--text-2); margin-top: 3px; }

/* ---- 活动月历 ---- */
.cal-month { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; min-width: 96px; text-align: center; }
.cal-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6px;
}
.cal-weekday {
  text-align: center;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
  padding: 4px 0 8px;
}
.cal-cell {
  min-height: 76px;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 6px;
  background: var(--glass-strong);
  overflow: hidden;
}
.cal-dim { opacity: 0.35; }
.cal-today { border-color: var(--blue); box-shadow: 0 0 0 2px rgba(10, 132, 255, 0.18); }
.cal-day {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 4px;
  font-variant-numeric: tabular-nums;
}
.cal-event {
  font-size: 11px;
  line-height: 1.35;
  border-radius: 6px;
  padding: 2px 5px;
  margin-bottom: 3px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.cal-event-time { font-weight: 700; margin-right: 4px; font-variant-numeric: tabular-nums; }
.cal-upcoming { background: rgba(10, 132, 255, 0.16); color: var(--blue); }
.cal-ongoing { background: rgba(48, 209, 88, 0.18); color: #1a7f37; }
.cal-done { background: var(--surface); color: var(--text-2); }
.cal-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 3px;
  margin-right: 4px;
  vertical-align: baseline;
}
@media (max-width: 620px) {
  .cal-cell { min-height: 54px; padding: 4px; }
  .cal-event-title { display: none; }
}

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

/* ---- 列表行 ---- */
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 2px;
  border-bottom: 1px solid var(--border);
}
.row:last-child { border-bottom: none; }
.row-main { min-width: 0; }
.row-title { font-size: 14.5px; font-weight: 500; }
.row-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--text-2);
}
.row-meta time { font-variant-numeric: tabular-nums; }

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
.notice-main { display: flex; align-items: center; min-width: 0; }
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

.stat-unit { font-size: 14px; font-weight: 600; margin-left: 2px; color: var(--text-2); }
.stat-sm { font-size: 17px; }
</style>
