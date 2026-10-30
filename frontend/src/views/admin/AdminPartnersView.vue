<script setup>
import { onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { fmtTime, showToast } from '../../utils.js';
import { confirmModal } from '../../modal.js';

const partners = ref([]);
const loading = ref(true);
const busy = ref(false);
const form = ref({ name: '', url: '', logo: '', description: '', sort: 0 });
const editing = ref(null);          // 正在编辑的伙伴 id
const editForm = ref({ name: '', url: '', logo: '', description: '', sort: 0 });
const logoInput = ref(null);

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/admin/partners');
    partners.value = data.partners;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

function pickLogo() {
  logoInput.value?.click();
}

async function onLogoChange(ev) {
  const file = ev.target.files?.[0];
  ev.target.value = '';
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const data = await api.upload('/api/uploads/partner-logo', fd);
    if (editing.value) editForm.value.logo = data.url;
    else form.value.logo = data.url;
    showToast('Logo 已上传');
  } catch (err) {
    showToast(err.message);
  }
}

async function add() {
  if (!form.value.name.trim() || !form.value.url.trim()) { showToast('名称与链接必填'); return; }
  busy.value = true;
  try {
    const data = await api.post('/api/admin/partners', {
      name: form.value.name.trim(),
      url: form.value.url.trim(),
      logo: form.value.logo,
      description: form.value.description.trim(),
      sort: Number(form.value.sort) || 0,
    });
    showToast(data.message || '已添加');
    form.value = { name: '', url: '', logo: '', description: '', sort: 0 };
    await load();
  } catch (err) {
    showToast(err.message);
  }
  busy.value = false;
}

function startEdit(p) {
  editing.value = p.id;
  editForm.value = { name: p.name, url: p.url, logo: p.logo || '', description: p.description || '', sort: p.sort || 0 };
}

async function saveEdit(p) {
  busy.value = true;
  try {
    await api.put(`/api/admin/partners/${p.id}`, editForm.value);
    showToast('已更新');
    editing.value = null;
    await load();
  } catch (err) {
    showToast(err.message);
  }
  busy.value = false;
}

async function toggle(p) {
  try {
    const data = await api.patch(`/api/admin/partners/${p.id}/enabled`, { enabled: p.enabled ? 0 : 1 });
    showToast(data.message || '已切换');
    await load();
  } catch (err) {
    showToast(err.message);
  }
}

async function remove(p) {
  const ok = await confirmModal({
    title: '删除合作伙伴', danger: true, confirmText: '删除',
    message: `确认删除「${p.name}」？`,
  });
  if (!ok) return;
  try {
    await api.delete(`/api/admin/partners/${p.id}`);
    showToast('已删除');
    await load();
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">合作伙伴</div>
      <div class="page-desc">管理首页底部合作伙伴展示位；上架后立即在首页可见</div>
    </div>

    <div class="glass card" style="margin-bottom: 16px">
      <div class="card-title">新增合作伙伴</div>
      <div class="input-row">
        <div class="field" style="flex: 1">
          <label class="label">名称</label>
          <input v-model="form.name" class="input" maxlength="20" placeholder="如 CW 平台" />
        </div>
        <div class="field" style="flex: 1.4">
          <label class="label">链接</label>
          <input v-model="form.url" class="input" placeholder="https://..." maxlength="200" />
        </div>
        <div class="field" style="flex: 0 0 140px">
          <label class="label">排序，小在前</label>
          <input v-model="form.sort" class="input" type="number" min="0" max="999" />
        </div>
      </div>
      <div class="field" style="margin-top: 10px">
        <label class="label">简介 <span class="optional">选填，展示在伙伴卡片上</span></label>
        <input v-model="form.description" class="input" maxlength="20" placeholder="一句话介绍这个合作伙伴" />
      </div>
      <div style="display: flex; gap: 14px; align-items: center; flex-wrap: wrap">
        <button class="btn btn-ghost btn-sm" @click="pickLogo">{{ form.logo ? '已上传 Logo ✓' : '上传 Logo' }}</button>
        <span v-if="form.logo" class="card-sub">{{ form.logo }}</span>
        <button class="btn btn-primary" :disabled="busy" @click="add">添加</button>
      </div>
      <input ref="logoInput" type="file" accept="image/*" style="display: none" @change="onLogoChange" />
    </div>

    <div class="glass card">
      <div class="card-title">合作伙伴，{{ partners.length }}</div>
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else-if="partners.length">
        <div v-for="p in partners" :key="p.id" class="list-item" style="flex-wrap: wrap">
          <div class="list-main">
            <template v-if="editing === p.id">
              <div class="input-row">
                <input v-model="editForm.name" class="input" style="flex: 0 0 160px" maxlength="20" />
                <input v-model="editForm.url" class="input" style="flex: 1" maxlength="200" />
                <input v-model="editForm.sort" class="input" type="number" style="flex: 0 0 90px" min="0" max="999" />
              </div>
              <input v-model="editForm.description" class="input" style="margin-top: 8px" maxlength="20" placeholder="简介，选填" />
            </template>
            <template v-else>
              <div class="list-title">
                <span class="tag" :class="p.enabled ? 'tag-green' : 'tag'" style="margin-right: 8px">
                  {{ p.enabled ? '展示中' : '已下架' }}
                </span>
                {{ p.name }}
              </div>
              <div class="list-sub">{{ p.url }} · 排序 {{ p.sort }} · {{ fmtTime(p.created_at) }}</div>
              <div v-if="p.description" class="list-sub">简介：{{ p.description }}</div>
              <div v-else class="list-sub" style="opacity: 0.6">无简介</div>
            </template>
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap">
            <template v-if="editing === p.id">
              <button class="btn btn-primary btn-sm" :disabled="busy" @click="saveEdit(p)">保存</button>
              <button class="btn btn-ghost btn-sm" @click="editing = null">取消</button>
            </template>
            <template v-else>
              <button class="btn btn-ghost btn-sm" @click="startEdit(p)">编辑</button>
              <button class="btn btn-ghost btn-sm" @click="toggle(p)">{{ p.enabled ? '下架' : '上架' }}</button>
              <button class="btn btn-danger btn-sm" @click="remove(p)">删除</button>
            </template>
          </div>
        </div>
      </template>
      <div v-else class="empty">暂无合作伙伴</div>
    </div>
  </div>
</template>
