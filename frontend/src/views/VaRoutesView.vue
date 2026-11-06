<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import { useVaStore } from '../stores/va.js';
import Icon from '../components/Icon.vue';

const va = useVaStore();
const router = useRouter();
const routes = ref([]);
const loading = ref(true);

onMounted(async () => {
  await va.fetch();
  if (!va.joined) {
    loading.value = false;
    return;
  }
  try {
    const data = await api.get(`/api/airlines/${va.membership.airlineId}/routes`);
    routes.value = data.routes || [];
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
});

function goDispatch(r) {
  router.push({ path: '/va/dispatch', query: { routeId: r.id } });
}
</script>

<template>
  <div class="page" style="max-width: clamp(720px, 54vw, 1080px)">
    <div class="page-header">
      <div class="page-title">航线列表</div>
      <div class="page-desc">
        {{ va.membership ? `${va.membership.name}（${va.membership.icao}） · CEO 发布的航线` : '' }}
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!va.joined" class="glass card">
      <div class="empty">
        <div class="empty-icon"><Icon name="plane" :size="22" /></div>
        <div>你还没有加入航司</div>
        <router-link class="btn btn-primary btn-sm" to="/airlines">去航司列表加入</router-link>
      </div>
    </div>

    <template v-else>
      <div v-if="!routes.length" class="glass card">
        <div class="empty">
          <div class="empty-icon"><Icon name="plane" :size="22" /></div>
          <div>CEO 还没有发布航线</div>
          <div class="card-sub">请联系 CEO 在航司管理中添加航线</div>
        </div>
      </div>

      <div v-else class="glass card">
        <div class="card-title"><Icon name="plane" :size="16" /> 共 {{ routes.length }} 条航线</div>
        <div v-for="r in routes" :key="r.id" class="list-item">
          <div class="list-main">
            <div class="list-title">
              <span class="tag" style="background: var(--surface-strong); margin-right: 8px">{{ r.flight_no || '—' }}</span>
              {{ r.dep }} → {{ r.arr }}
            </div>
            <div class="list-sub">
              {{ r.aircraft || '机型不限' }}
              · {{ r.distance_nm ? `${Math.round(r.distance_nm)} nm` : '距离未测' }}
              · 工资 {{ r.base_salary }}
              <template v-if="r.notes"> · {{ r.notes }}</template>
            </div>
          </div>
          <button class="btn btn-primary btn-sm" @click="goDispatch(r)">去签派</button>
        </div>
      </div>
    </template>
  </div>
</template>
