<script setup>
import { onMounted, ref } from 'vue';
import { api } from '../../api.js';
import { showToast } from '../../utils.js';
import { confirmModal } from '../../modal.js';
import SelectMenu from '../../components/SelectMenu.vue';
import CheckBox from '../../components/CheckBox.vue';
import UserTag from '../../components/UserTag.vue';

const items = ref([]);
const loading = ref(true);
const saving = ref(false);

const form = ref({ name: '', description: '', price: 500, type: 'title', payload: '', active: true });
const typeOptions = [
  { value: 'title', label: '称号（显示在用户名旁）' },
  { value: 'badge', label: '徽章' },
];

async function load() {
  loading.value = true;
  try {
    const d = await api.get('/api/admin/shop/items');
    items.value = d.items;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

async function create() {
  saving.value = true;
  try {
    await api.post('/api/admin/shop/items', form.value);
    showToast('商品已上架');
    form.value = { name: '', description: '', price: 500, type: 'title', payload: '', active: true };
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    saving.value = false;
  }
}

async function toggleActive(item) {
  try {
    await api.put(`/api/admin/shop/items/${item.id}`, {
      name: item.name, description: item.description, price: item.price,
      type: item.type, payload: item.payload, active: !item.active,
    });
    showToast(item.active ? '已下架' : '已上架');
    load();
  } catch (err) {
    showToast(err.message);
  }
}

async function removeItem(item) {
  const ok = await confirmModal({
    title: '下架商品', danger: true, confirmText: '下架',
    message: `确定要下架「${item.name}」吗？已购买的玩家不受影响。`,
  });
  if (!ok) return;
  try {
    await api.delete(`/api/admin/shop/items/${item.id}`);
    showToast('已下架');
    load();
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">商城管理</div>
      <div class="page-desc">上架虚拟商品（称号 / 徽章），玩家用飞行工资购买</div>
    </div>

    <div class="glass card" style="margin-bottom: 16px">
      <div class="card-title">上架新商品</div>
      <div class="grid grid-2">
        <div class="field"><label class="label">商品名称</label><input v-model="form.name" class="input" maxlength="20" placeholder="如 元老称号" /></div>
        <div class="field">
          <label class="label">类型</label>
          <SelectMenu v-model="form.type" :options="typeOptions" />
        </div>
        <div class="field">
          <label class="label">价格</label>
          <input v-model.number="form.price" class="input" type="number" min="0" />
        </div>
        <div class="field">
          <label class="label">
            称号文字 / 徽章内容
            <span class="optional">徽章可填 icon:star、icon:diamond、icon:crown、icon:bolt、icon:wings，显示矢量图标</span>
          </label>
          <input v-model="form.payload" class="input" maxlength="20" placeholder="如 元老 或 icon:star" />
        </div>
      </div>
      <div class="field">
        <label class="label">商品说明</label>
        <textarea v-model="form.description" class="textarea" rows="2" maxlength="200"></textarea>
      </div>
      <div style="display: flex; gap: 16px; align-items: center">
        <CheckBox v-model="form.active" variant="switch" label="立即上架" />
        <button class="btn btn-primary" :disabled="saving" @click="create">{{ saving ? '提交中…' : '上架商品' }}</button>
      </div>
    </div>

    <div class="glass card">
      <div class="card-title">商品列表（{{ items.length }}）</div>
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else-if="items.length">
        <div v-for="i in items" :key="i.id" class="list-item">
          <div class="list-main">
            <div class="list-title">
              {{ i.name }}
              <span class="tag" :class="i.type === 'title' ? 'tag-blue' : 'tag-purple'" style="margin-left: 6px">
                {{ i.type === 'title' ? '称号' : '徽章' }}
              </span>
              <span v-if="!i.active" class="tag tag-red" style="margin-left: 6px">已下架</span>
            </div>
            <div class="list-sub">{{ i.description || '暂无说明' }}</div>
            <div class="list-sub">价格 {{ i.price }} · 佩戴效果：</div>
            <div style="margin-top: 6px">
              <UserTag
                :badge="i.type === 'badge' ? i.payload : ''"
                :title="i.type === 'title' ? i.payload : ''"
              >示例飞行员</UserTag>
            </div>
          </div>
          <div style="display: flex; gap: 8px">
            <button class="btn btn-ghost btn-sm" @click="toggleActive(i)">{{ i.active ? '下架' : '上架' }}</button>
            <button class="btn btn-danger btn-sm" @click="removeItem(i)">删除</button>
          </div>
        </div>
      </template>
      <div v-else class="empty">暂无商品</div>
    </div>
  </div>
</template>
