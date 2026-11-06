<script setup>
/**
 * 对外航司主页，无需登录，可分享链接 /va/{icao}
 */
import { onMounted, ref, computed } from 'vue';
import { useRoute } from 'vue-router';
import { api } from '../api.js';
import Icon from '../components/Icon.vue';
import UserTag from '../components/UserTag.vue';
import { showToast } from '../utils.js';

const route = useRoute();
const data = ref(null);
const loading = ref(true);
const error = ref('');

const airline = computed(() => data.value?.airline);

onMounted(async () => {
  try {
    data.value = await api.get(`/api/airlines/public/${route.params.icao}`);
  } catch (err) {
    error.value = err.message;
  }
  loading.value = false;
});

async function copyLink() {
  try {
    await navigator.clipboard.writeText(window.location.href);
    showToast('主页链接已复制');
  } catch {
    showToast('复制失败，请手动复制地址栏链接');
  }
}
</script>

<template>
  <div class="page" style="max-width: clamp(760px, 62vw, 1240px)">
    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="error" class="glass card" style="text-align: center; padding: 48px 24px">
      <div class="empty-icon" style="margin: 0 auto 12px"><Icon name="plane" :size="24" /></div>
      <div class="card-title">找不到该虚拟航司</div>
      <div class="card-sub">{{ error }}</div>
      <router-link class="btn btn-primary" to="/airlines">返回航司列表</router-link>
    </div>

    <template v-else-if="airline">
      <!-- 航司名片 -->
      <div class="glass card" style="padding: 32px">
        <div style="display: flex; gap: 20px; align-items: center; flex-wrap: wrap">
          <div class="va-logo" :style="airline.logo_url ? `background-image:url(${airline.logo_url})` : ''">
            {{ airline.icao }}
          </div>
          <div style="flex: 1; min-width: 220px">
            <h1 style="font-size: 28px; font-weight: 700; letter-spacing: -0.5px">{{ airline.name }}</h1>
            <div v-if="airline.slogan" class="va-slogan">{{ airline.slogan }}</div>
            <div style="color: var(--text-2); font-size: 14px; margin-top: 4px">
              {{ airline.icao }} · CEO {{ airline.ceo }} · 成立于 {{ airline.createdAt?.slice(0, 10) }}
            </div>
            <p style="color: var(--text-2); font-size: 14px; margin-top: 12px; line-height: 1.7">
              {{ airline.description || '这家航司还没有填写简介。' }}
            </p>
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px">
            <button class="btn btn-ghost btn-sm" @click="copyLink"><Icon name="link" :size="14" /> 复制主页链接</button>
            <router-link class="btn btn-primary btn-sm" to="/airlines"><Icon name="external" :size="14" /> 进入航司列表</router-link>
          </div>
        </div>

        <div v-if="airline.showStats" class="grid grid-4" style="margin-top: 24px">
          <div class="stat"><div class="stat-num">{{ airline.memberCount }}</div><div class="stat-label">在册成员</div></div>
          <div class="stat"><div class="stat-num">{{ airline.routeCount }}</div><div class="stat-label">运营航线</div></div>
          <div class="stat"><div class="stat-num">{{ airline.totalHours }}</div><div class="stat-label">累计飞行小时</div></div>
          <div class="stat"><div class="stat-num">{{ airline.totalFlights }}</div><div class="stat-label">已完成航班</div></div>
        </div>
      </div>

      <!-- 欢迎语 / 公告 -->
      <div v-if="airline.welcome" class="glass card va-welcome" style="margin-top: 16px">
        <div class="card-title"><Icon name="megaphone" :size="16" /> 欢迎语</div>
        <p class="va-welcome-text">{{ airline.welcome }}</p>
      </div>

      <!-- 机队 -->
      <div v-if="airline.showFleet && airline.fleet?.length" class="glass card" style="margin-top: 16px">
        <div class="card-title">机队</div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px">
          <span v-for="f in airline.fleet" :key="f" class="tag tag-blue">{{ f }}</span>
        </div>
      </div>

      <div v-if="airline.showRoutes || airline.showMembers" class="grid grid-2" style="margin-top: 16px">
        <!-- 航线网络 -->
        <div v-if="airline.showRoutes" class="glass card">
          <div class="card-title">航线网络，{{ data.routes.length }}</div>
          <div v-for="r in data.routes" :key="r.dep + r.arr + r.flight_no" class="list-item">
            <div class="list-main">
              <div class="list-title">
                <span class="tag tag-blue" style="margin-right: 8px">{{ r.dep }}-{{ r.arr }}</span>
                <span v-if="r.flight_no" class="tag">{{ r.flight_no }}</span>
              </div>
              <div class="list-sub" v-if="r.aircraft">机型 {{ r.aircraft }}</div>
            </div>
          </div>
          <div v-if="!data.routes.length" class="empty">暂未公布航线</div>
        </div>

        <!-- 成员名单 -->
        <div v-if="airline.showMembers" class="glass card">
          <div class="card-title">成员名单，{{ data.members.length }}</div>
          <div v-for="(m, i) in data.members" :key="m.cid + i" class="list-item">
            <div class="avatar-badge">{{ (m.username || '?')[0].toUpperCase() }}</div>
            <div class="list-main">
              <div class="list-title">
                <UserTag :badge="m.equipped_badge" :title="m.equipped_title">{{ m.username }}</UserTag>
                <span :class="m.role === 'ceo' ? 'tag tag-red' : 'tag tag-blue'" style="margin-left: 6px">
                  {{ m.role === 'ceo' ? 'CEO' : (m.pilot_rank || '学员') }}
                </span>
              </div>
              <div class="list-sub">CID {{ m.cid }}</div>
            </div>
          </div>
          <div v-if="!data.members.length" class="empty">暂无成员</div>
        </div>
      </div>

      <p style="text-align: center; color: var(--gray); font-size: 12.5px; margin-top: 32px">
        本页由 CTYFLY · 虚拟航司系统生成
      </p>
    </template>
  </div>
</template>

<style scoped>
/* 标语：紧跟航司名称 */
.va-slogan {
  margin-top: 6px;
  font-size: 14.5px;
  font-weight: 500;
  color: var(--blue);
}
/* 欢迎语区块：左侧强调条 */
.va-welcome { border-left: 3px solid var(--blue); }
.va-welcome-text {
  font-size: 14px;
  line-height: 1.75;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  margin-top: 6px;
}

/* 航司 Logo 与成员头像徽章，合并自原先误开的第二个 style 块*/
.va-logo {
  width: 84px;
  height: 84px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 20px;
  background: var(--blue);
  background-size: cover;
  color: #fff;
  font-weight: 700;
  font-size: 18px;
  letter-spacing: 1px;
}
.avatar-badge {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--blue);
  color: #fff;
  font-weight: 600;
  font-size: 14px;
}
</style>
