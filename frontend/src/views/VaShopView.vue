<script setup>
import { ref, computed, onMounted } from 'vue';
import { api } from '../api.js';
import { fmtTime, showToast } from '../utils.js';
import { useVaStore } from '../stores/va.js';
import Icon from '../components/Icon.vue';

const va = useVaStore();
const items = ref([]);
const orders = ref([]);
const balance = ref(0);
const maxPrice = 500000;
const loading = ref(true);
const buying = ref(0);
const presets = ref([]);

/* CEO 管理表单 */
const showForm = ref(false);
const editingId = ref(0);
const savingItem = ref(false);   // 保存防重复提交
const form = ref({ name: '', description: '', price: 100000, stock: -1 });

const activeItems = computed(() => items.value.filter((i) => i.active));

async function loadAll() {
  const aid = va.membership.airlineId;
  const [itemsData, ordersData] = await Promise.all([
    api.get(`/api/airlines/${aid}/shop/items`),
    api.get(`/api/airlines/${aid}/shop/orders`),
  ]);
  items.value = itemsData.items || [];
  balance.value = itemsData.balance || 0;
  orders.value = ordersData.orders || [];
  if (va.isCEO && !presets.value.length) {
    try {
      const p = await api.get(`/api/airlines/${aid}/shop/presets`);
      presets.value = p.presets || [];
    } catch { /* 预设拉取失败不阻塞 */ }
  }
}

onMounted(async () => {
  await va.fetch();
  if (!va.joined) {
    loading.value = false;
    return;
  }
  try {
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});

async function buy(item) {
  buying.value = item.id;
  try {
    const d = await api.post(`/api/airlines/${va.membership.airlineId}/shop/buy/${item.id}`);
    showToast(d.message);
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
  buying.value = 0;
}

function usePreset(p) {
  form.value = { name: p.name, description: p.description, price: p.price, stock: -1 };
  showForm.value = true;
  editingId.value = 0;
}

function editItem(item) {
  form.value = { name: item.name, description: item.description, price: item.price, stock: item.stock };
  editingId.value = item.id;
  showForm.value = true;
}

async function saveItem() {
  if (savingItem.value) return;
  if (form.value.name.trim().length < 2) { showToast('奖品名称至少 2 个字'); return; }
  const price = Number(form.value.price) || 0;
  if (price < 0 || price > maxPrice) { showToast(`价格需在 0 - ${maxPrice} 之间`); return; }
  savingItem.value = true;
  try {
    const body = { name: form.value.name, description: form.value.description, price, stock: Number(form.value.stock) };
    const d = editingId.value
      ? await api.put(`/api/airlines/${va.membership.airlineId}/shop/items/${editingId.value}`, body)
      : await api.post(`/api/airlines/${va.membership.airlineId}/shop/items`, body);
    showToast(d.message || '已保存');
    showForm.value = false;
    editingId.value = 0;
    await loadAll();
  } catch (err) {
    showToast(err.message);
  } finally {
    savingItem.value = false;
  }
}

async function removeItem(item) {
  try {
    const d = await api.delete(`/api/airlines/${va.membership.airlineId}/shop/items/${item.id}`);
    showToast(d.message || '已下架');
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
}

async function handle(order, action) {
  try {
    const d = await api.post(`/api/airlines/${va.membership.airlineId}/shop/orders/${order.id}/handle`, { action });
    showToast(d.message || '已处理');
    await loadAll();
  } catch (err) {
    showToast(err.message);
  }
}

const ceoPending = computed(() => orders.value.filter((o) => o.status === 'pending'));
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 56vw, 1100px)">
    <div class="page-header">
      <div class="page-title">航司商城</div>
      <div class="page-desc">
        {{ va.membership ? `${va.membership.name}，${va.membership.icao}专属奖品 · 货款进公司账上` : '' }}
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!va.joined" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="shop" :size="22" /></div>
        <div>你还没有加入航司</div>
        <router-link class="btn btn-primary btn-sm" to="/airlines">去航司列表加入</router-link>
      </div>
    </div>

    <template v-else>
      <!-- CEO：奖品管理 -->
      <div v-if="va.isCEO" class="glass card">
        <div class="card-title" style="display: flex; align-items: center; gap: 10px">
          <Icon name="briefcase" :size="16" /> 奖品管理
          <button class="btn btn-primary btn-sm" style="margin-left: auto" @click="showForm = !showForm">
            {{ showForm ? '收起' : '上架新奖品' }}
          </button>
        </div>

        <div v-if="showForm" style="margin-top: 10px">
          <div v-if="presets.length && !editingId" class="field">
            <label class="label">奖品预设，点选后可改名改价</label>
            <div class="input-row" style="flex-wrap: wrap; gap: 8px">
              <button
                v-for="p in presets" :key="p.name"
                class="btn btn-ghost btn-sm" @click="usePreset(p)"
              >{{ p.name }} · 建议 {{ p.price }}</button>
            </div>
          </div>
          <div class="field">
            <label class="label">奖品名称</label>
            <input v-model="form.name" class="input" maxlength="20" placeholder="如限量机模，1:200" />
          </div>
          <div class="field">
            <label class="label">奖品说明</label>
            <textarea v-model="form.description" class="textarea" rows="2" maxlength="200"></textarea>
          </div>
          <div class="input-row">
            <div class="field" style="flex: 1">
              <label class="label">兑换价格，上限 500,000</label>
              <input v-model="form.price" class="input" type="number" min="0" :max="maxPrice" />
            </div>
            <div class="field" style="flex: 1">
              <label class="label">限量，-1 = 不限量</label>
              <input v-model="form.stock" class="input" type="number" min="-1" max="9999" />
            </div>
          </div>
          <div style="display: flex; gap: 8px">
            <button class="btn btn-primary" :disabled="savingItem" @click="saveItem">
              {{ savingItem ? '保存中…' : (editingId ? '保存修改' : '确认上架') }}
            </button>
            <button v-if="showForm" class="btn btn-ghost" @click="showForm = false; editingId = 0">取消</button>
          </div>
        </div>

        <div v-for="i in activeItems" :key="i.id" class="list-item">
          <div class="list-main">
            <div class="list-title">{{ i.name }}</div>
            <div class="list-sub">
              价格 {{ i.price }} · {{ i.stock < 0 ? '不限量' : `限量 ${i.stock}，已兑 ${i.sold}` }}
              <template v-if="i.description"> · {{ i.description }}</template>
            </div>
          </div>
          <div style="display: flex; gap: 8px">
            <button class="btn btn-ghost btn-sm" @click="editItem(i)">编辑</button>
            <button class="btn btn-ghost btn-sm" @click="removeItem(i)">下架</button>
          </div>
        </div>
        <div v-if="!activeItems.length" class="card-sub">还没有上架奖品</div>
      </div>

      <!-- 成员：兑换 -->
      <div class="glass card" :style="va.isCEO ? 'margin-top: 16px' : ''">
        <div class="card-title">
          <Icon name="shop" :size="16" /> 可兑换奖品
          <span class="card-sub" style="margin: 0 0 0 8px">我的余额 {{ balance }}</span>
        </div>
        <div v-if="!activeItems.length" class="empty">
          <div class="empty-icon"><Icon name="shop" :size="22" /></div>
          <div>公司还没有上架奖品</div>
        </div>
        <div v-for="i in activeItems" :key="i.id" class="list-item">
          <div class="list-main">
            <div class="list-title">{{ i.name }}</div>
            <div class="list-sub">
              {{ i.description || '暂无说明' }}
              · <template v-if="i.stock >= 0">剩余 {{ i.remaining }} 份 · </template>价格 {{ i.price }}
            </div>
          </div>
          <button
            v-if="!i.owned" class="btn btn-primary btn-sm"
            :disabled="balance < i.price || buying === i.id || (i.stock >= 0 && i.remaining <= 0)"
            @click="buy(i)"
          >{{ buying === i.id ? '兑换中…' : (i.stock >= 0 && i.remaining <= 0) ? '已售罄' : balance < i.price ? '余额不足' : '兑换' }}</button>
          <span v-else class="tag tag-green">已兑换</span>
        </div>
      </div>

      <!-- 订单 -->
      <div class="glass card" style="margin-top: 16px">
        <div class="card-title">
          <Icon name="ticket" :size="16" />
          {{ va.isCEO ? '兑换订单，含全体成员' : '我的兑换记录' }}
          <span v-if="va.isCEO && ceoPending.length" class="tag tag-orange" style="margin-left: 8px">
            {{ ceoPending.length }} 单待发放
          </span>
        </div>
        <div v-if="!orders.length" class="empty">
          <div class="empty-icon"><Icon name="ticket" :size="22" /></div>
          <div>暂无兑换记录</div>
        </div>
        <div v-for="o in orders" :key="o.id" class="list-item">
          <div class="list-main">
            <div class="list-title">
              <span class="tag" :class="o.status === 'delivered' ? 'tag-green' : o.status === 'pending' ? 'tag-orange' : 'tag'" style="margin-right: 8px">
                {{ o.status === 'delivered' ? '已发放' : o.status === 'pending' ? '待发放' : '已取消' }}
              </span>
              {{ o.item_name }}
              <span v-if="va.isCEO" class="card-sub" style="margin-left: 6px">{{ o.username }}，{{ o.cid }}</span>
            </div>
            <div class="list-sub">花费 {{ o.price }} · {{ fmtTime(o.created_at) }}</div>
          </div>
          <div v-if="va.isCEO && o.status === 'pending'" style="display: flex; gap: 8px">
            <button class="btn btn-primary btn-sm" @click="handle(o, 'deliver')">标记发放</button>
            <button class="btn btn-ghost btn-sm" @click="handle(o, 'cancel')">取消退款</button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
