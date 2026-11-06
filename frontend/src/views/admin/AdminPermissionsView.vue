<script setup>
/**
 * 权限管理
 *
 * 三个入口：
 *   按用户 —— 用户列表 + 每人一行细分权限复选框，主视图，最直观
 *   按角色 —— 角色能力矩阵，ADM / SUP / USER
 *   按管制等级 —— rating 能力矩阵，飞行员 / OBS..I3 / SUP / ADM
 *   节点分布 —— 后台每个菜单节点需要哪项能力、当前谁有
 *
 * 权限计算，后端 capabilities_for 同源：
 *   有效 = role ∪ rating ∪ 个人放开 − 个人收回
 * 所以「按用户」里取消勾选能真的把继承来的权限收回去，而不是只改了显示。
 */
import { computed, onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { showToast } from '../../utils.js';
import CheckBox from '../../components/CheckBox.vue';

const TABS = [
  { key: 'user', label: '按用户' },
  { key: 'role', label: '按角色' },
  { key: 'rating', label: '按管制等级' },
  { key: 'nodes', label: '节点分布' },
];
const tab = ref('user');

const loading = ref(true);
const saving = ref('');

// ---- 按用户 ----
const users = ref([]);
const userCaps = ref([]);
const roleCounts = ref({});
const totalCount = ref(0);
const userRoleFilter = ref('');
const q = ref('');

// ---- 按角色 / 按等级 / 节点分布 ----
const capabilities = ref([]);
const roles = ref([]);
const ratings = ref([]);
const nodes = ref([]);
const matrix = ref({});
const ratingMatrix = ref({});
const activeRating = ref('SUP');

const ROLE_TEXT = { admin: 'ADM 管理员', sup: 'SUP 主管', user: 'USER 用户' };
const ROLE_CLS = { admin: 'tag tag-red', sup: 'tag tag-purple', user: 'tag' };

const roleFilters = computed(() => [
  { key: '', label: `全部 ${totalCount.value}` },
  ...['admin', 'sup', 'user'].map((k) => ({
    key: k,
    label: `${ROLE_TEXT[k]} ${roleCounts.value[k] || 0} 人`,
  })),
]);

onMounted(load);

async function load() {
  loading.value = true;
  try {
    const [up, pm] = await Promise.all([
      api.get(`/api/admin/user-permissions?q=${encodeURIComponent(q.value)}&role=${userRoleFilter.value}`),
      api.get('/api/admin/permissions'),
    ]);
    users.value = up.users;
    userCaps.value = up.capabilities;
    roleCounts.value = up.roleCounts;
    totalCount.value = up.totalCount;

    capabilities.value = pm.capabilities;
    roles.value = pm.roles;
    ratings.value = pm.ratings || [];
    nodes.value = pm.nodes || [];
    matrix.value = pm.matrix;
    ratingMatrix.value = pm.ratingMatrix || {};
    if (!ratings.value.some((r) => r.key === activeRating.value)) {
      activeRating.value = ratings.value[0]?.key || '';
    }
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}

/** 某用户在某个能力上的当前有效状态 */
function hasCap(u, key) {
  return (u.effective || []).includes(key);
}

/** 是否来自个人覆盖，用于在界面上标出来*/
function isOverridden(u, key) {
  return Object.prototype.hasOwnProperty.call(u.overrides || {}, key);
}

async function toggleUserCap(u, key) {
  const on = hasCap(u, key);
  saving.value = `${u.id}:${key}`;
  try {
    await api.put('/api/admin/user-permissions', { userId: u.id, capability: key, allowed: !on });
    const set = new Set(u.effective || []);
    if (on) set.delete(key); else set.add(key);
    u.effective = [...set];
    u.overrides = { ...(u.overrides || {}), [key]: !on };
    showToast(`${u.username} 的「${key}」已${on ? '收回' : '放开'}`);
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = '';
  }
}

async function toggleRole(role, cap) {
  if (role === 'admin') return;   // ADM 角色恒有全部权限，不可修改
  const next = !matrix.value[role][cap];
  saving.value = `${role}:${cap}`;
  try {
    await api.put('/api/admin/permissions', { role, capability: cap, allowed: next });
    matrix.value[role][cap] = next;
    showToast(`${role.toUpperCase()} 的「${cap}」已${next ? '开启' : '关闭'}`);
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = '';
  }
}

async function toggleRating(rating, cap) {
  const next = !(ratingMatrix.value[rating]?.[cap]);
  saving.value = `r:${rating}:${cap}`;
  try {
    await api.put('/api/admin/rating-permissions', { rating, capability: cap, allowed: next });
    if (!ratingMatrix.value[rating]) ratingMatrix.value[rating] = {};
    ratingMatrix.value[rating][cap] = next;
    showToast(`${rating} 的「${cap}」已${next ? '开启' : '关闭'}`);
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = '';
  }
}

function grantedCount(rating) {
  const m = ratingMatrix.value[rating] || {};
  return capabilities.value.filter((c) => m[c.key]).length;
}

function ownersOf(cap) {
  const out = [];
  for (const r of roles.value) {
    if (r.key === 'admin' || matrix.value[r.key]?.[cap]) out.push(r.key.toUpperCase());
  }
  for (const r of ratings.value) {
    if (ratingMatrix.value[r.key]?.[cap]) out.push(r.key);
  }
  return out;
}

function search() {
  load();
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">权限管理</div>
      <div class="page-desc">
        为每个用户分配细分管理权限。有效权限 = 角色 ∪ 管制等级 ∪ 个人放开，再减去个人收回 ——
        所以在这里取消勾选能真的把继承来的权限收回。
      </div>
    </div>

    <div class="perm-tabs">
      <button
        v-for="t in TABS"
        :key="t.key"
        type="button"
        class="perm-tab"
        :class="{ on: tab === t.key }"
        @click="tab = t.key"
      >{{ t.label }}</button>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <!-- ==================== 按用户 ==================== -->
    <div v-else-if="tab === 'user'" class="glass card">
      <div class="list-toolbar">
        <div class="input-row" style="max-width: 320px; margin: 0">
          <input v-model="q" class="input" placeholder="搜索 CID / 用户名" @keyup.enter="search" />
          <button class="btn btn-primary" @click="search">搜索</button>
        </div>
        <div class="filter-pills">
          <button
            v-for="f in roleFilters"
            :key="f.key || 'all'"
            type="button"
            class="pill"
            :class="{ on: userRoleFilter === f.key }"
            @click="userRoleFilter = f.key; load()"
          >{{ f.label }}</button>
        </div>
      </div>

      <div class="table-wrap perm-scroll" style="margin-top: 14px">
        <table class="table perm-table">
          <thead>
            <tr>
              <th style="min-width: 64px">CID</th>
              <th style="min-width: 110px">用户名</th>
              <th style="min-width: 110px">权限等级</th>
              <th style="min-width: 96px">细分权限</th>
              <th v-for="c in userCaps" :key="c.key" class="cap-col" :title="c.label">
                {{ c.short }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td><code>{{ u.cid }}</code></td>
              <td>
                <div style="font-weight: 500">{{ u.username }}</div>
                <div class="list-sub">{{ u.rating }}</div>
              </td>
              <td>
                <span :class="ROLE_CLS[u.role] || 'tag'">{{ ROLE_TEXT[u.role] || u.role }}</span>
              </td>
              <td>
                <span class="list-sub">{{ (u.effective || []).length }} / {{ userCaps.length }}</span>
              </td>
              <td
                v-for="c in userCaps"
                :key="c.key"
                class="cap-col"
                :class="{ overridden: isOverridden(u, c.key) }"
              >
                <CheckBox
                  :model-value="hasCap(u, c.key)"
                  :disabled="saving === `${u.id}:${c.key}`"
                  @update:model-value="toggleUserCap(u, c.key)"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!users.length" class="empty">没有匹配的用户，试试调整搜索或筛选条件</div>
    </div>

    <!-- ==================== 按角色 ==================== -->
    <div v-else-if="tab === 'role'" class="glass card">
      <div class="card-title">角色能力矩阵（按职务）</div>
      <div class="card-sub">ADM 角色恒有全部权限，不可修改；勾选即生效，越权访问会自动记入审计日志</div>
      <div class="table-wrap perm-scroll">
        <table class="table">
          <thead>
            <tr>
              <th style="min-width: 200px">能力</th>
              <th v-for="r in roles" :key="r.key" style="text-align: center; min-width: 110px">
                {{ r.label }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in capabilities" :key="c.key">
              <td>
                <div style="font-weight: 500">{{ c.label }}</div>
                <div class="list-sub"><code>{{ c.key }}</code></div>
              </td>
              <td v-for="r in roles" :key="r.key" style="text-align: center">
                <CheckBox
                  :model-value="r.key === 'admin' || !!matrix[r.key]?.[c.key]"
                  :disabled="r.key === 'admin' || saving === `${r.key}:${c.key}`"
                  @update:model-value="toggleRole(r.key, c.key)"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ==================== 按管制等级 ==================== -->
    <div v-else-if="tab === 'rating'" class="glass card">
      <div class="card-title">管制等级能力矩阵（rating）</div>
      <div class="card-sub">
        选中一个管制等级，勾选它能使用的后台节点。默认只有 <strong>SUP / ADM</strong> 全开。
      </div>
      <div class="rating-pills">
        <button
          v-for="r in ratings"
          :key="r.key"
          type="button"
          class="pill stacked"
          :class="{ on: r.key === activeRating }"
          @click="activeRating = r.key"
        >
          <span>{{ r.label }}</span>
          <span class="pill-meta">{{ grantedCount(r.key) }}/{{ capabilities.length }}</span>
        </button>
      </div>
      <div class="cap-grid">
        <label
          v-for="c in capabilities"
          :key="c.key"
          class="cap-item"
          :class="{ dim: saving === `r:${activeRating}:${c.key}` }"
        >
          <CheckBox
            :model-value="!!ratingMatrix[activeRating]?.[c.key]"
            :disabled="saving === `r:${activeRating}:${c.key}`"
            @update:model-value="toggleRating(activeRating, c.key)"
          />
          <span class="cap-text">
            <span class="cap-label">{{ c.label }}</span>
            <code class="cap-key">{{ c.key }}</code>
          </span>
        </label>
      </div>
    </div>

    <!-- ==================== 节点分布 ==================== -->
    <div v-else class="glass card">
      <div class="card-title">后台节点分布</div>
      <div class="card-sub">每个后台菜单节点需要哪项能力，以及当前哪些角色 / 管制等级已经拿到它</div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr><th style="min-width: 150px">节点</th><th style="min-width: 170px">所需能力</th><th>已授予</th></tr>
          </thead>
          <tbody>
            <tr v-for="n in nodes" :key="n.to">
              <td>
                <div style="font-weight: 500">{{ n.label }}</div>
                <div class="list-sub"><code>{{ n.to }}</code></div>
              </td>
              <td><code>{{ n.cap }}</code></td>
              <td>
                <span v-for="o in ownersOf(n.cap)" :key="o" class="tag tag-blue" style="margin: 2px 4px 2px 0">{{ o }}</span>
                <span v-if="!ownersOf(n.cap).length" class="list-sub">无人可见</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ---------- 顶部页签 ---------- */
.perm-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 14px;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: var(--surface);
}
.perm-tab {
  padding: 7px 14px;
  border: 0;
  border-radius: 8px;
  background: none;
  color: var(--text-2);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}
.perm-tab.on { background: var(--blue); color: #fff; }

/* ---------- 工具条与筛选 ---------- */
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}
.filter-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.pill {
  padding: 6px 13px;
  border: 1px solid var(--border);
  border-radius: 980px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.14s ease;
}
.pill:hover { border-color: var(--blue); }
.pill.on { background: var(--blue); border-color: var(--blue); color: #fff; }
.pill.stacked { display: flex; flex-direction: column; align-items: center; gap: 1px; border-radius: 10px; }
.pill-meta { font-size: 11px; opacity: 0.75; }

/* ---------- 按用户表格 ---------- */
.perm-table :deep(td), .perm-table :deep(th) { white-space: nowrap; }
.cap-col { text-align: center; min-width: 62px; }
/* 个人覆盖过的格子加个底色，一眼看出「这条不是继承来的」 */
.cap-col.overridden { background: rgba(10, 132, 255, 0.1); }

/* ---------- 权限矩阵横向滚动，桌面 1440px 下列多时滚动而非裁切 ----------*/
/* .table-wrap 全局已有 overflow-x:auto，这里显式兜底并约束宽度 */
.perm-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; max-width: 100%; }
.perm-scroll .table { min-width: max-content; }

.rating-pills { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 6px; }
.cap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
  margin-top: 14px;
}
.cap-item {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  cursor: pointer;
}
.cap-item.dim { opacity: 0.55; }
.cap-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.cap-label { font-size: 13px; }
.cap-key { font-size: 11px; color: var(--gray); }
</style>
