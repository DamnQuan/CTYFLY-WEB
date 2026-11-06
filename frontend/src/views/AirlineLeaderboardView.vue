<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import UserAvatar from '../components/UserAvatar.vue';
import UserTag from '../components/UserTag.vue';

const airlines = ref([]);
const pilots = ref([]);
const hours = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await api.get('/api/airlines/leaderboard');
    airlines.value = data.airlines;
    pilots.value = data.pilots;
    hours.value = data.hours || [];
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});

const RANKS = [
  { text: '1', cls: 'gold' },
  { text: '2', cls: 'silver' },
  { text: '3', cls: 'bronze' },
];
const medal = (i) => (i < 3 ? RANKS[i] : { text: String(i + 1), cls: '' });
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">排行榜</div>
      <div class="page-desc">航司排行，按累计飞行时长 · 飞行员活跃排行，按活动参与次数</div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else class="grid lb-grid">
      <div class="glass card">
        <div class="card-title">航司排行</div>
        <div class="list-item" v-for="(a, i) in airlines" :key="a.id">
          <span class="rank" :class="medal(i).cls">{{ medal(i).text }}</span>
          <div class="list-main">
            <div class="list-title">{{ a.icao }} {{ a.name }}</div>
            <div class="list-sub">{{ a.hours }} 飞行小时</div>
          </div>
          <span class="tag tag-blue">{{ a.members }} 名成员</span>
        </div>
        <div v-if="!airlines.length" class="empty">暂无航司，可创建或加入一家</div>
      </div>

      <div class="glass card">
        <div class="card-title">飞行员时长排行</div>
        <div class="list-item" v-for="(p, i) in hours" :key="p.user_id">
          <span class="rank" :class="medal(i).cls">{{ medal(i).text }}</span>
          <UserAvatar :user="p" :size="32" />
          <div class="list-main">
            <div class="list-title">
              <UserTag :badge="p.equipped_badge" :title="p.equipped_title" size="sm">{{ p.username }}</UserTag>
            </div>
            <div class="list-sub">CID {{ p.cid }}</div>
          </div>
          <span class="tag tag-orange">{{ p.hours }} 小时</span>
        </div>
        <div v-if="!hours.length" class="empty">暂无飞行记录，提交飞行报告后上榜</div>
      </div>

      <div class="glass card">
        <div class="card-title">飞行员活跃排行</div>
        <div class="list-item" v-for="(p, i) in pilots" :key="p.id">
          <span class="rank" :class="medal(i).cls">{{ medal(i).text }}</span>
          <UserAvatar :user="p" :size="32" />
          <div class="list-main">
            <div class="list-title">
              <UserTag :badge="p.equipped_badge" :title="p.equipped_title" size="sm">{{ p.username }}</UserTag>
            </div>
            <div class="list-sub">CID {{ p.cid }}</div>
          </div>
          <span class="tag tag-purple">{{ p.events }} 次活动</span>
        </div>
        <div v-if="!pilots.length" class="empty">暂无数据，参加连飞活动后上榜</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rank {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-weight: 700;
  font-size: 13px;
  color: var(--text-2);
  background: var(--surface);
  flex-shrink: 0;
}
.rank.gold { background: rgba(255, 204, 0, 0.3); color: var(--text); }
.rank.silver { background: rgba(142, 142, 147, 0.25); color: var(--text); }
.rank.bronze { background: rgba(205, 127, 50, 0.3); color: var(--text); }
.lb-grid { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
</style>
