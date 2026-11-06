<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { api } from '../../api.js';
import { fmtTime, EVENT_STATUS, showToast } from '../../utils.js';
import { confirmModal } from '../../modal.js';
import DatePicker from '../../components/DatePicker.vue';
import AirportInput from '../../components/AirportInput.vue';
import { compressImage } from '../../imageCompress.js';

const events = ref([]);
const loading = ref(true);
const showCreate = ref(false);
const submitting = ref(false);   // 创建/保存防重复提交
const editingId = ref(null);     // 非空 = 正在编辑该活动
const EMPTY_FORM = { title: '', description: '', dep: '', arr: '', startTime: '', endTime: '', route: '', distanceNm: null, notams: '' };
const form = ref({ ...EMPTY_FORM });
const planningRoute = ref(false);
let routePlanSeq = 0;            // 自动规划请求序号：仅接受最新一次结果
let routeTimer = null;

// 起降机场都填好 4 位 ICAO 且航路为空时，自动规划航路，防抖 800ms
watch([() => form.value.dep, () => form.value.arr], ([d, a]) => {
  clearTimeout(routeTimer);
  if (form.value.route) return;
  const dep = (d || '').trim().toUpperCase();
  const arr = (a || '').trim().toUpperCase();
  if (dep.length !== 4 || arr.length !== 4 || dep === arr) return;
  routeTimer = setTimeout(() => fetchRoute(dep, arr), 800);
});

async function fetchRoute(dep, arr) {
  const seq = ++routePlanSeq;
  planningRoute.value = true;
  try {
    const plan = await api.post('/api/nav/routes/plan', { origin: dep, destination: arr });
    if (seq !== routePlanSeq) return;   // 已有更新的规划请求，丢弃旧结果
    if (plan.routeString) {
      form.value.route = plan.routeString;
      if (plan.totalDistance) form.value.distanceNm = Math.round(plan.totalDistance);
      showToast('航路已自动获取');
    } else {
      showToast('未能规划出航路，请手动填写');
    }
  } catch {
    showToast('航路规划失败，请手动填写');
  } finally {
    planningRoute.value = false;
  }
}

// 手动触发：用当前表单里的起降机场重新规划
function autoFetchRoute() {
  const dep = (form.value.dep || '').trim().toUpperCase();
  const arr = (form.value.arr || '').trim().toUpperCase();
  if (dep.length !== 4 || arr.length !== 4) { showToast('请先填写 4 位起降机场'); return; }
  fetchRoute(dep, arr);
}

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/admin/events');
    events.value = data.events;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

/* ==================== 活动海报，简报页头图 ====================
 * 海报属于活动内容维护，统一在管理后台操作。后端接口不变，POST /api/events/{id}/briefing/images，
 * DELETE /api/briefings/images/{id}，仍只有管理员可用。
 * 文件选择必须靠隐藏 input 触发，浏览器唯一途径，可见 UI 全部是自研按钮，与航司 Logo 上传同款。
 */
const poster = ref({ imageId: null, url: '', busy: false });
const posterInput = ref(null);
const canManagePoster = computed(() => !!editingId.value);

function revokePoster() {
  if (poster.value.url) {
    URL.revokeObjectURL(poster.value.url);
    poster.value.url = '';
  }
}

async function loadPoster(eventId) {
  revokePoster();
  poster.value = { imageId: null, url: '', busy: false };
  if (!eventId) return;
  try {
    const detail = await api.get(`/api/events/${eventId}`);
    const imageId = detail.posterImageId || null;
    poster.value.imageId = imageId;
    if (imageId) {
      const blob = await api.blob(`/api/briefings/images/${imageId}`, 30000);
      poster.value.url = URL.createObjectURL(blob);
    }
  } catch {
    // 海报取不到不影响编辑活动本身，静默降级为「未设置」
  }
}

function pickPoster() {
  posterInput.value?.click();
}

async function onPosterChange(ev) {
  const raw = ev.target.files?.[0];
  ev.target.value = '';
  if (!raw || !editingId.value) return;
  if (!raw.type.startsWith('image/')) {
    showToast('仅支持 PNG / JPG / WebP / GIF 图片');
    return;
  }
  poster.value.busy = true;
  try {
    // 上传前先 Canvas 压缩到 2MB 内，否则手机直出的 5~8MB 图会撞后端/nginx 上限
    const { file, compressed, originalSize } = await compressImage(raw, {
      maxBytes: 2 * 1024 * 1024,
      maxDim: 2560,
    });
    const mb = (n) => `${(n / 1024 / 1024).toFixed(2)} MB`;
    if (file.size > 5 * 1024 * 1024) {
      showToast(`图片压缩后仍有 ${mb(file.size)}，已超过 5 MB，请换一张更小的图`);
      poster.value.busy = false;
      return;
    }
    const fd = new FormData();
    fd.append('file', file);
    await api.upload(`/api/events/${editingId.value}/briefing/images`, fd);
    showToast(compressed ? `海报已更新，${mb(originalSize)} → ${mb(file.size)}` : '海报已更新');
    await loadPoster(editingId.value);
  } catch (err) {
    showToast(err.message);
  }
  poster.value.busy = false;
}

async function removePoster() {
  if (!poster.value.imageId) return;
  const ok = await confirmModal({
    title: '移除活动海报', danger: true, confirmText: '移除',
    message: '确定要移除吗？移除后活动简报页会显示默认标题块。',
  });
  if (!ok) return;
  try {
    await api.delete(`/api/briefings/images/${poster.value.imageId}`);
    showToast('海报已移除');
    await loadPoster(editingId.value);
  } catch (err) {
    showToast(err.message);
  }
}

onBeforeUnmount(revokePoster);

function openCreate() {
  editingId.value = null;
  form.value = { ...EMPTY_FORM };
  showCreate.value = !showCreate.value;
}

function openEdit(e) {
  editingId.value = e.id;
  form.value = {
    title: e.title || '',
    description: e.description || '',
    dep: e.dep || '',
    arr: e.arr || '',
    startTime: e.start_time || '',
    endTime: e.end_time || '',
    route: e.route || '',
    distanceNm: e.distance_nm ?? null,
    notams: e.notams || '',
  };
  loadPoster(e.id);
  showCreate.value = true;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function cancelForm() {
  showCreate.value = false;
  editingId.value = null;
  form.value = { ...EMPTY_FORM };
  revokePoster();
  poster.value = { imageId: null, url: '', busy: false };
}

async function submitForm() {
  if (submitting.value) return;
  submitting.value = true;
  try {
    if (editingId.value) {
      await api.put(`/api/admin/events/${editingId.value}`, form.value);
      showToast('活动已保存');
    } else {
      await api.post('/api/admin/events', form.value);
      showToast('活动创建成功');
    }
    cancelForm();
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    submitting.value = false;
  }
}

async function setStatus(e, status) {
  try {
    await api.patch(`/api/admin/events/${e.id}`, { status });
    e.status = status;
    showToast('状态已更新');
  } catch (err) {
    showToast(err.message);
  }
}

async function remove(e) {
  const ok = await confirmModal({
    title: '删除活动', danger: true, confirmText: '删除',
    message: `确定要删除活动「${e.title}」吗？该操作不可撤销。`,
  });
  if (!ok) return;
  try {
    await api.delete(`/api/admin/events/${e.id}`);
    showToast('已删除');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

/* ==================== 管制席位管理 ==================== */
// 每个活动可展开席位管理区：席位列表，含占用者+ 添加表单
const posPanelId = ref(null);      // 当前展开席位管理的活动 id
const posList = ref([]);
const posLoading = ref(false);
const posBusy = ref(false);        // 添加/删除防重复提交
const EMPTY_POS = { name: '', rating: '', frequency: '', sort: 0 };
const posForm = ref({ ...EMPTY_POS });

function togglePosPanel(e) {
  if (posPanelId.value === e.id) {
    posPanelId.value = null;
    posList.value = [];
    return;
  }
  posPanelId.value = e.id;
  loadPositions(e.id);
}

async function loadPositions(eventId) {
  posLoading.value = true;
  try {
    const data = await api.get(`/api/admin/events/${eventId}/atc-positions`);
    posList.value = data.positions || [];
  } catch (err) {
    showToast(err.message);
  }
  posLoading.value = false;
}

async function addPosition(e) {
  if (posBusy.value) return;
  if (!posForm.value.name.trim()) {
    showToast('请填写席位名称');
    return;
  }
  posBusy.value = true;
  try {
    await api.post(`/api/admin/events/${e.id}/atc-positions`, {
      name: posForm.value.name.trim(),
      rating: posForm.value.rating.trim().toUpperCase(),
      frequency: posForm.value.frequency.trim(),
      sort: Number(posForm.value.sort) || 0,
    });
    showToast('席位已添加');
    posForm.value = { ...EMPTY_POS };
    loadPositions(e.id);
  } catch (err) {
    showToast(err.message);
  }
  posBusy.value = false;
}

async function removePosition(e, pos) {
  const owner = pos.taken ? `当前由 ${pos.taken.username}（CID ${pos.taken.cid}）占用，将同时删除其报名。` : '';
  const ok = await confirmModal({
    title: '删除席位', danger: true, confirmText: '删除',
    message: `确定要删除席位「${pos.name}」吗？${owner}`,
  });
  if (!ok) return;
  try {
    await api.delete(`/api/admin/events/${e.id}/atc-positions/${pos.id}`);
    showToast('席位已删除');
    loadPositions(e.id);
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px">
      <div>
        <div class="page-title">活动管理</div>
        <div class="page-desc">连飞活动的创建、编辑、开始 / 结束 / 取消与删除统一在此管理，前台活动页仅可报名</div>
      </div>
      <button class="btn btn-dark" @click="openCreate">{{ showCreate && !editingId ? '收起' : '+ 创建活动' }}</button>
    </div>

    <div v-if="showCreate" class="glass card" style="margin-bottom: 16px">
      <div class="card-title">{{ editingId ? '编辑活动' : '创建新活动' }}</div>
      <div class="grid grid-2">
        <div class="field"><label class="label">活动标题</label><input v-model="form.title" class="input" maxlength="20" placeholder="CTY 周五之夜" /></div>
        <div class="field">
          <label class="label">航线</label>
          <div class="input-row">
            <AirportInput v-model="form.dep" placeholder="起飞 ZBAA" />
            <AirportInput v-model="form.arr" placeholder="落地 ZSPD" />
          </div>
        </div>
        <div class="field">
          <label class="label">开始时间</label>
          <DatePicker v-model="form.startTime" mode="datetime" placeholder="选择开始日期与时间" />
        </div>
        <div class="field">
          <label class="label">结束时间</label>
          <DatePicker v-model="form.endTime" mode="datetime" placeholder="选择结束日期与时间" />
        </div>
      </div>
      <div class="field">
        <label class="label">活动说明</label>
        <textarea v-model="form.description" class="textarea" placeholder="活动详情、管制开放范围、注意事项…"></textarea>
      </div>
      <div class="grid grid-2">
        <div class="field">
          <label class="label">航路</label>
          <div style="display: flex; gap: 8px; align-items: center">
            <input v-model="form.route" class="input" maxlength="200" placeholder="如 ELKUR W40 YQG W142 ..." style="flex: 1; min-width: 0" />
            <button
              class="btn btn-ghost btn-sm"
              style="flex-shrink: 0"
              :disabled="planningRoute"
              type="button"
              @click="autoFetchRoute"
            >{{ planningRoute ? '规划中…' : '自动获取航路' }}</button>
          </div>
        </div>
        <div class="field">
          <label class="label">飞行距离（nm）</label>
          <input v-model.number="form.distanceNm" class="input" type="number" min="0" step="0.1" placeholder="如 1078" />
        </div>
      </div>
      <div class="field">
        <label class="label">NOTAMS</label>
        <textarea v-model="form.notams" class="textarea" rows="2" maxlength="500" placeholder="飞行注意事项、特殊限制…"></textarea>
      </div>
      <!-- 活动海报只在「编辑」时出现：新建活动还没 id，无法挂图中 -->
      <div v-if="canManagePoster" class="field">
        <label class="label">活动海报（活动简报页头图）</label>
        <div class="poster-admin">
          <div class="poster-thumb">
            <img v-if="poster.url" :src="poster.url" alt="活动海报" />
            <span v-else class="poster-empty">未设置</span>
          </div>
          <div class="poster-actions">
            <div style="display: flex; gap: 8px; flex-wrap: wrap">
              <button class="btn btn-ghost btn-sm" type="button" :disabled="poster.busy" @click="pickPoster">
                {{ poster.busy ? '上传中…' : (poster.url ? '更换海报' : '上传海报') }}
              </button>
              <button v-if="poster.imageId" class="btn btn-danger btn-sm" type="button" @click="removePoster">
                移除
              </button>
            </div>
            <div class="field-hint-text" style="padding-top: 6px">
              建议 16:9 或 4:3；支持 PNG / JPG / WebP / GIF。前端会自动压缩到 2 MB 内再上传，服务端单张上限 5 MB
            </div>
          </div>
        </div>
        <input ref="posterInput" type="file" accept="image/*" style="display: none" @change="onPosterChange" />
      </div>
      <div style="display: flex; gap: 10px; flex-wrap: wrap">
        <button class="btn btn-primary" :disabled="submitting" @click="submitForm">
          {{ submitting ? '保存中…' : (editingId ? '保存修改' : '发布活动') }}
        </button>
        <button class="btn btn-ghost" @click="cancelForm">取消</button>
      </div>
    </div>

    <div class="glass card">
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else-if="events.length">
        <div v-for="e in events" :key="e.id" class="list-item">
          <div class="list-main">
            <div class="list-title">
              <span :class="['tag', EVENT_STATUS[e.status]?.cls]" style="margin-right: 8px">{{ EVENT_STATUS[e.status]?.text }}</span>
              {{ e.title }}
            </div>
            <div class="list-sub">
              <span class="tag tag-blue">{{ e.dep }} → {{ e.arr }}</span>
              <span style="margin-left: 8px">{{ fmtTime(e.start_time) }} ~ {{ fmtTime(e.end_time) }}</span>
            </div>
            <div class="list-sub">发起人 {{ e.creator || '官方' }} · {{ e.signup_count }} 人报名</div>
          </div>
          <div style="display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end">
            <button class="btn btn-ghost btn-sm" @click="openEdit(e)">编辑</button>
            <button class="btn btn-ghost btn-sm" @click="togglePosPanel(e)">
              {{ posPanelId === e.id ? '收起席位' : '管制席位' }}
            </button>
            <button v-if="e.status === 'upcoming'" class="btn btn-ghost btn-sm" @click="setStatus(e, 'ongoing')">开始</button>
            <button v-if="e.status === 'ongoing'" class="btn btn-ghost btn-sm" @click="setStatus(e, 'ended')">结束</button>
            <button v-if="['upcoming', 'ongoing'].includes(e.status)" class="btn btn-ghost btn-sm" @click="setStatus(e, 'cancelled')">取消活动</button>
            <button class="btn btn-danger btn-sm" @click="remove(e)">删除</button>
          </div>

          <!-- 管制席位管理区，按行展开，位于该活动行内-->
          <div v-if="posPanelId === e.id" class="pos-panel">
          <div class="pos-panel-title">管制席位管理</div>
          <div v-if="posLoading" class="loading">加载中…</div>
          <template v-else>
            <div v-if="!posList.length" class="empty">暂无席位，请在下方添加</div>
            <div v-else class="pos-list">
              <div v-for="pos in posList" :key="pos.id" class="list-item">
                <div class="list-main">
                  <div class="list-title">
                    {{ pos.name }}
                    <span v-if="pos.rating" class="tag tag-blue" style="margin-left: 8px">{{ pos.rating }}</span>
                  </div>
                  <div class="list-sub">
                    {{ pos.frequency || '频率待定' }} · 排序 {{ pos.sort }} ·
                    <template v-if="pos.taken">占用者 {{ pos.taken.username }}，CID {{ pos.taken.cid }}</template>
                    <template v-else>空闲</template>
                  </div>
                </div>
                <button class="btn btn-danger btn-sm" @click="removePosition(e, pos)">删除</button>
              </div>
            </div>
          </template>
          <div class="pos-add">
            <input v-model="posForm.name" class="input" maxlength="16" placeholder="席位名称（如 ZBAA_TWR）" />
            <input v-model="posForm.rating" class="input" maxlength="8" placeholder="等级（如 S1）" style="max-width: 110px" />
            <input v-model="posForm.frequency" class="input" maxlength="12" placeholder="频率（如 121.600）" style="max-width: 140px" />
            <input v-model.number="posForm.sort" class="input" type="number" min="0" placeholder="排序" style="max-width: 90px" />
            <button class="btn btn-primary btn-sm" :disabled="posBusy" @click="addPosition(e)">添加席位</button>
          </div>
          </div>
        </div>
      </template>
      <div v-else class="empty">暂无活动，可点击右上角创建</div>
    </div>
  </div>
</template>

<style scoped>
/* ---------- 活动海报，编辑表单内 ----------*/
.poster-admin {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  flex-wrap: wrap;
}
.poster-thumb {
  width: 200px;
  aspect-ratio: 16 / 9;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--surface-solid);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.poster-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.poster-empty { font-size: 12.5px; color: var(--gray); }
.poster-actions { flex: 1; min-width: 180px; }

/* ---------- 管制席位管理区 ---------- */
/* 面板独占整行：list-item 是 flex 横排，不换行会把面板挤在按钮旁、活动信息被压成一字一行 */
.list-item { flex-wrap: wrap; }
.pos-panel {
  flex-basis: 100%;
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius, 12px);
  background: var(--surface-solid);
}
.pos-panel-title {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 8px;
}
.pos-list { margin-bottom: 10px; }
.pos-add {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.pos-add .input { flex: 1; min-width: 140px; }
</style>
