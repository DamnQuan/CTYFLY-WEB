<script setup>
/**
 * 虚拟商城：用飞行工资购买称号 / 徽章
 */
import { onMounted, ref } from 'vue';
import { api } from '../api.js';
import { fmtTime, showToast } from '../utils.js';
import { confirmModal } from '../modal.js';
import { useAuthStore } from '../stores/auth.js';
import { useVaStore } from '../stores/va.js';
import Icon from '../components/Icon.vue';
import UserTag from '../components/UserTag.vue';

const auth = useAuthStore();
const va = useVaStore();

const items = ref([]);
const orders = ref([]);
const ownedIds = ref([]);
const balance = ref(0);
const equippedTitle = ref('');
const equippedBadge = ref('');
const loading = ref(true);
const buying = ref(0);

async function load() {
  loading.value = true;
  await va.fetch();
  if (!va.joined) {
    loading.value = false;
    return;
  }
  try {
    const [shopData, orderData] = await Promise.all([
      api.get('/api/shop/items'),
      api.get('/api/shop/orders'),
    ]);
    items.value = shopData.items;
    ownedIds.value = shopData.ownedIds;
    orders.value = orderData.orders;
    balance.value = orderData.balance;
    equippedTitle.value = orderData.equippedTitle;
    equippedBadge.value = orderData.equippedBadge;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

const has = (id) => ownedIds.value.includes(id);

/* 徽章 payload 的 icon:xxx 前缀 → 中文标签，与 Icon 组件可用图标对应*/
const ICON_LABELS = {
  diamond: '钻石', star: '星星', crown: '皇冠', bolt: '闪电', wings: '翅膀',
  heart: '爱心', award: '奖章', key: '钥匙', pin: '图钉', link: '链接', external: '外链',
};
function badgeLabel(payload) {
  if (payload.startsWith('icon:')) {
    const name = payload.slice(5);
    return ICON_LABELS[name] ? `${ICON_LABELS[name]}徽章` : name;
  }
  return payload;
}

async function buy(item) {
  const ok = await confirmModal({
    title: '确认购买',
    message: `花费 ${item.price} 购买「${item.name}」？购买后不可退款。当前余额 ${balance.value}。`,
    confirmText: '确认购买',
  });
  if (!ok) return;
  buying.value = item.id;
  try {
    const d = await api.post(`/api/shop/buy/${item.id}`);
    showToast(d.message);
    load();
  } catch (err) {
    showToast(err.message);
  } finally {
    buying.value = 0;
  }
}

async function toggleEquip(order) {
  try {
    const d = await api.post('/api/shop/equip', { order_id: order.id });
    showToast(d.message);
    load();
  } catch (err) {
    showToast(err.message);
  }
}
</script>

<template>
  <div class="page" style="max-width: clamp(760px, 62vw, 1240px)">
    <div class="page-header" style="display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 12px">
      <div>
        <div class="page-title">虚拟商城</div>
        <div class="page-desc">用飞行工资购买称号与徽章，展示在你的账号上</div>
      </div>
      <div style="text-align: right">
        <div style="font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums">{{ balance }}</div>
        <div class="stat-label">当前余额</div>
      </div>
    </div>

    <div
      v-if="!loading && !va.joined"
      class="glass card"
    >
      <div class="empty">
        <div class="empty-icon"><Icon name="shop" :size="22" /></div>
        <div>公共商城仅限已加入航司的成员</div>
        <router-link class="btn btn-primary btn-sm" to="/airlines">去航司列表加入</router-link>
      </div>
    </div>

    <div
      v-if="equippedTitle || equippedBadge"
      class="glass card"
      style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap"
    >
      <Icon name="award" :size="16" />
      <span style="font-size: 14px">当前展示效果：</span>
      <UserTag :badge="equippedBadge" :title="equippedTitle" size="lg">
        {{ auth.user?.username }}
      </UserTag>
      <span class="list-sub" style="margin-left: auto">
        {{ equippedBadge ? `徽章「${badgeLabel(equippedBadge)}」` : '未佩戴徽章' }} ·
        {{ equippedTitle ? `称号「${equippedTitle}」` : '未佩戴称号' }}
      </span>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <template v-else-if="va.joined">
      <div class="grid grid-3">
        <div v-for="item in items" :key="item.id" class="glass card" style="display: flex; flex-direction: column">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px">
            <div class="card-title" style="margin-bottom: 2px">{{ item.name }}</div>
            <span class="tag" :class="item.type === 'title' ? 'tag-blue' : 'tag-purple'">
              {{ item.type === 'title' ? '称号' : '徽章' }}
            </span>
          </div>
          <div class="card-sub" style="flex: 1">{{ item.description || '暂无说明' }}</div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 8px">
            <strong style="font-size: 18px; font-variant-numeric: tabular-nums">{{ item.price }}</strong>
            <button
              v-if="!has(item.id)"
              class="btn btn-primary btn-sm"
              :disabled="balance < item.price || buying === item.id"
              @click="buy(item)"
            >{{ buying === item.id ? '购买中…' : balance < item.price ? '余额不足' : '购买' }}</button>
            <span v-else class="tag tag-green">已拥有</span>
          </div>
        </div>
      </div>

      <div class="glass card" style="margin-top: 20px">
        <div class="card-title">我的物品，{{ orders.length }}</div>
        <div class="card-sub">称号与徽章各可装备一件，装备后会显示在你的用户名旁</div>
        <div v-for="o in orders" :key="o.id" class="list-item">
          <div class="list-main">
            <div class="list-title">
              <span class="tag" :class="o.item_type === 'title' ? 'tag-blue' : 'tag-purple'">
                {{ o.item_type === 'title' ? '称号' : '徽章' }}
              </span>
              <span style="margin-left: 8px">{{ o.item_name }}</span>
              <UserTag v-if="o.item_type === 'badge'" :badge="o.item_payload" size="sm" />
              <span v-if="o.equipped" class="tag tag-green" style="margin-left: 6px">已装备</span>
            </div>
            <div class="list-sub">花费 {{ o.price }} · 购买于 {{ fmtTime(o.created_at) }}</div>
          </div>
          <button
            class="btn btn-sm"
            :class="o.equipped ? 'btn-ghost' : 'btn-dark'"
            @click="toggleEquip(o)"
          >{{ o.equipped ? '卸下' : '装备' }}</button>
        </div>
        <div v-if="!orders.length" class="empty">
          <div class="empty-icon"><Icon name="shop" :size="22" /></div>
          <div>还没有购买任何物品</div>
        </div>
      </div>
    </template>
  </div>
</template>
