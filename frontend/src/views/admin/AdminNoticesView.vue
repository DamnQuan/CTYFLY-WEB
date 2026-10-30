<script setup>
import { onMounted, ref, computed } from 'vue';
import { api } from '../../api.js';
import { fmtTime, showToast, localDate } from '../../utils.js';
import { useAuthStore } from '../../stores/auth.js';
import { confirmModal } from '../../modal.js';
import CheckBox from '../../components/CheckBox.vue';
import SegmentedTabs from '../../components/SegmentedTabs.vue';

const auth = useAuthStore();
const canNotices = computed(() => auth.can('manage_notices'));   // 更新日志与公告共用该能力

const tab = ref('notices');
const tabs = computed(() => [
  { value: 'notices', label: '公告' },
  ...(canNotices.value ? [{ value: 'changelogs', label: '更新日志' }] : []),
]);

const notices = ref([]);
const form = ref({ title: '', content: '', pinned: true });
const loading = ref(true);
const submitting = ref(false);   // 发布防重复提交

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/admin/notices');
    notices.value = data.notices;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

async function add() {
  if (submitting.value) return;
  submitting.value = true;
  try {
    await api.post('/api/admin/notices', form.value);
    showToast('公告已发布');
    form.value = { title: '', content: '', pinned: true };
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    submitting.value = false;
  }
}

async function remove(n) {
  const ok = await confirmModal({
    title: '删除公告', danger: true, confirmText: '删除',
    message: `确认删除公告「${n.title}」？`,
  });
  if (!ok) return;
  try {
    await api.delete(`/api/admin/notices/${n.id}`);
    showToast('已删除');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

/* ---------- 更新日志 ---------- */
const changelogs = ref([]);
const clLoading = ref(false);
const clLoaded = ref(false);
const clForm = ref({ version: '', title: '', body: '', releasedAt: localDate() });
const clSubmitting = ref(false);   // 提交防重复锁

async function loadChangelogs() {
  clLoading.value = true;
  try {
    const data = await api.get('/api/changelogs');
    changelogs.value = data.changelogs || [];
    clLoaded.value = true;
  } catch (err) {
    showToast(err.message);
  }
  clLoading.value = false;
}

function switchTab(v) {
  tab.value = v;
  if (v === 'changelogs' && !clLoaded.value) loadChangelogs();
}

async function addChangelog() {
  if (clSubmitting.value) return;
  if (!clForm.value.title.trim()) { showToast('请填写标题'); return; }
  if (!clForm.value.body.trim()) { showToast('请填写更新内容'); return; }
  clSubmitting.value = true;
  try {
    await api.post('/api/admin/changelogs', {
      version: clForm.value.version.trim(),
      title: clForm.value.title.trim(),
      body: clForm.value.body,
      releasedAt: clForm.value.releasedAt || localDate(),
    });
    showToast('更新日志已发布');
    clForm.value = { version: '', title: '', body: '', releasedAt: localDate() };
    loadChangelogs();
  } catch (err) {
    showToast(err.message);
  } finally {
    clSubmitting.value = false;
  }
}

async function removeChangelog(c) {
  const ok = await confirmModal({
    title: '删除更新日志', danger: true, confirmText: '删除',
    message: `确认删除更新日志「${c.version || c.title}」？`,
  });
  if (!ok) return;
  try {
    await api.delete(`/api/admin/changelogs/${c.id}`);
    showToast('已删除');
    loadChangelogs();
  } catch (err) {
    showToast(err.message);
  }
}

function clSummary(c) {
  const text = (c.body || '').trim();
  return text.length > 60 ? `${text.slice(0, 60)}…` : text;
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">公告管理</div>
      <div class="page-desc">发布社区公告，新公告默认置顶显示在仪表盘顶部，可手动取消</div>
    </div>

    <SegmentedTabs v-model="tab" :options="tabs" style="margin-bottom: 16px" @update:model-value="switchTab" />

    <!-- 公告 tab -->
    <template v-if="tab === 'notices'">
      <div class="glass card" style="margin-bottom: 16px">
        <div class="card-title">发布新公告</div>
        <div class="field"><label class="label">标题</label><input v-model="form.title" class="input" maxlength="20" /></div>
        <div class="field"><label class="label">内容</label><textarea v-model="form.content" class="textarea" maxlength="2000"></textarea></div>
        <div style="display: flex; gap: 14px; align-items: center">
          <CheckBox v-model="form.pinned" variant="switch" label="置顶显示" />
          <button class="btn btn-primary" :disabled="submitting" @click="add">
            {{ submitting ? '发布中…' : '发布公告' }}
          </button>
        </div>
      </div>

      <div class="glass card">
        <div class="card-title">已有公告，{{ notices.length }}</div>
        <div v-if="loading" class="loading">加载中…</div>
        <template v-else-if="notices.length">
          <div v-for="n in notices" :key="n.id" class="list-item">
            <div class="list-main">
              <div class="list-title">
                <span v-if="n.pinned" class="tag tag-red" style="margin-right: 6px">置顶</span>{{ n.title }}
              </div>
              <div class="list-sub">{{ n.content || '—' }}</div>
              <div class="list-sub">{{ fmtTime(n.created_at) }}</div>
            </div>
            <button class="btn btn-danger btn-sm" @click="remove(n)">删除</button>
          </div>
        </template>
        <div v-else class="empty">暂无公告</div>
      </div>
    </template>

    <!-- 更新日志 tab -->
    <template v-else-if="tab === 'changelogs'">
      <div class="glass card" style="margin-bottom: 16px">
        <div class="card-title">发布新更新日志</div>
        <div class="field">
          <label class="label">版本号 <span class="optional">选填</span></label>
          <input v-model="clForm.version" class="input" maxlength="20" placeholder="v1.1.0" />
        </div>
        <div class="field"><label class="label">标题</label><input v-model="clForm.title" class="input" maxlength="20" /></div>
        <div class="field"><label class="label">发布日期</label><input v-model="clForm.releasedAt" class="input" style="max-width: 180px" /></div>
        <div class="field"><label class="label">更新内容</label><textarea v-model="clForm.body" class="textarea" maxlength="4000"></textarea></div>
        <button class="btn btn-primary" :disabled="clSubmitting" @click="addChangelog">
          {{ clSubmitting ? '发布中…' : '发布更新日志' }}
        </button>
      </div>

      <div class="glass card">
        <div class="card-title">已有更新日志，{{ changelogs.length }}</div>
        <div v-if="clLoading" class="loading">加载中…</div>
        <template v-else-if="changelogs.length">
          <div v-for="c in changelogs" :key="c.id" class="list-item">
            <div class="list-main">
              <div class="list-title">
                <span v-if="c.version" class="tag tag-blue" style="margin-right: 6px">{{ c.version }}</span>{{ c.title }}
              </div>
              <div class="list-sub">{{ clSummary(c) || '—' }}</div>
              <div class="list-sub">{{ c.released_at }}</div>
            </div>
            <button class="btn btn-danger btn-sm" @click="removeChangelog(c)">删除</button>
          </div>
        </template>
        <div v-else class="empty">暂无更新记录</div>
      </div>
    </template>
  </div>
</template>
