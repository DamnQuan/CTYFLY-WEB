<script setup>
/**
 * 成就徽章墙：进度全部由后端按真实数据算，见 routers/achievements.py 的 METRIC_SQL，
 * 前端只负责展示与分类筛选。分类按钮用项目既有的 .seg 分段控件，没有原生 <select>。
 */
import { computed, onMounted, ref } from 'vue';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import Icon from '../components/Icon.vue';

const loading = ref(true);
const items = ref([]);
const stats = ref({ total: 0, unlocked: 0, rewardEarned: 0, categories: {} });
const activeCat = ref('all');

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/achievements');
    items.value = data.items || [];
    stats.value = data.stats || stats.value;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}

onMounted(load);

const cats = computed(() => {
  const seen = new Set(items.value.map((i) => i.category));
  return [
    { key: 'all', label: '全部' },
    ...Object.entries(stats.value.categories || {})
      .filter(([k]) => seen.has(k))
      .map(([k, v]) => ({ key: k, label: v })),
  ];
});

const shown = computed(() =>
  activeCat.value === 'all' ? items.value : items.value.filter((i) => i.category === activeCat.value),
);
const unlockedCount = computed(() => items.value.filter((i) => i.unlocked).length);
const percent = computed(() =>
  stats.value.total ? Math.round((unlockedCount.value / stats.value.total) * 100) : 0,
);

function fmt(n) {
  return Number(n || 0).toLocaleString('zh-CN');
}
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 58vw, 1120px)">
    <div class="page-header">
      <div class="page-title">成就徽章</div>
      <div class="page-desc">
        飞行、运营与安全里程碑 · 进度由服务器按真实数据结算，达标自动解锁并发放奖励
      </div>
    </div>

    <div class="glass card">
      <div class="ach-stats">
        <div class="stat">
          <div class="stat-num">{{ unlockedCount }} / {{ stats.total }}</div>
          <div class="stat-label">已解锁徽章</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ percent }}%</div>
          <div class="stat-label">完成度</div>
        </div>
        <div class="stat">
          <div class="stat-num">{{ fmt(stats.rewardEarned) }}</div>
          <div class="stat-label">成就奖励，游戏币</div>
        </div>
      </div>
      <div class="ach-bar"><span :style="{ width: percent + '%' }"></span></div>
    </div>

    <div class="glass card" style="margin-top: 16px">
      <div class="seg ach-seg">
        <button
          v-for="c in cats" :key="c.key" class="seg-btn"
          :class="{ on: activeCat === c.key }" @click="activeCat = c.key"
        >{{ c.label }}</button>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="!shown.length" class="empty">
        <div class="empty-icon"><Icon name="award" :size="22" /></div>
        <div>这个分类下还没有徽章</div>
      </div>

      <div v-else class="ach-grid">
        <div
          v-for="a in shown" :key="a.id" class="ach-card"
          :class="{ unlocked: a.unlocked }"
        >
          <div class="ach-icon"><Icon :name="a.icon || 'award'" :size="22" /></div>
          <div class="ach-body">
            <div class="ach-name">
              {{ a.name }}
              <span class="tag" :class="a.unlocked ? 'tag-green' : 'tag-blue'" style="margin-left: 6px">
                {{ a.unlocked ? '已解锁' : a.categoryLabel }}
              </span>
            </div>
            <div class="ach-desc">{{ a.description }}</div>
            <div class="ach-progress">
              <div class="ach-track"><span :style="{ width: a.percent + '%' }"></span></div>
              <span class="ach-num">{{ a.progress }} / {{ a.threshold }}</span>
            </div>
            <div class="ach-foot">
              <span><Icon name="diamond" :size="12" /> {{ fmt(a.reward) }}</span>
              <span v-if="a.unlocked">解锁于 {{ a.unlockedAt?.slice(0, 10) }}</span>
              <span v-else-if="a.eventLabel">{{ a.eventLabel }} 时自动结算</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ach-stats { display: flex; gap: 18px; flex-wrap: wrap; }
.ach-bar {
  margin-top: 14px; height: 8px; border-radius: 999px;
  background: var(--surface-strong); overflow: hidden;
}
.ach-bar span { display: block; height: 100%; border-radius: 999px; background: var(--blue); transition: width 0.4s ease; }
.ach-seg { margin-bottom: 16px; }
.ach-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.ach-card {
  display: flex; gap: 12px; padding: 14px 16px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
  background: var(--surface);
  opacity: 0.72;
  transition: opacity 0.2s ease, border-color 0.2s ease, transform 0.16s ease;
}
.ach-card.unlocked { opacity: 1; border-color: rgba(0, 113, 227, 0.35); }
.ach-card:hover { transform: translateY(-2px); }
.ach-icon {
  width: 42px; height: 42px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  background: var(--surface-strong); color: var(--text-2); flex-shrink: 0;
}
.ach-card.unlocked .ach-icon { color: var(--blue); background: rgba(0, 113, 227, 0.12); }
.ach-body { min-width: 0; flex: 1; }
.ach-name { font-size: 14.5px; font-weight: 600; display: flex; align-items: center; flex-wrap: wrap; }
.ach-desc { font-size: 12.5px; color: var(--text-2); margin-top: 4px; line-height: 1.5; }
.ach-progress { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
.ach-track { flex: 1; height: 6px; border-radius: 999px; background: var(--surface-strong); overflow: hidden; }
.ach-track span { display: block; height: 100%; border-radius: 999px; background: var(--blue); }
.ach-num { font-size: 11.5px; color: var(--text-2); white-space: nowrap; }
.ach-foot {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; margin-top: 8px; font-size: 11.5px; color: var(--text-2);
  flex-wrap: wrap;
}
.ach-foot span { display: inline-flex; align-items: center; gap: 4px; }
</style>
