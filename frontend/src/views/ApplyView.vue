<script setup>
import { computed, ref, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { api } from '../api.js';
import { fmtTime, APP_STATUS, showToast } from '../utils.js';

const route = useRoute();

// 当前申请类型由侧边栏二级菜单，子路由驱动：/apply/controller | /apply/staff
const tab = computed(() => route.meta.tab || 'controller');
const myApps = ref([]);
const loading = ref(true);
const submitting = ref(false);
const error = ref('');

const controllerForm = ref({ nickname: '', hours: '', experience: '', motivation: '' });
const staffForm = ref({ nickname: '', availableTime: '', motivation: '' });

async function load() {
  loading.value = true;
  try {
    const data = await api.get('/api/applications/mine');
    myApps.value = data.applications;
  } catch (err) {
    showToast(err.message);
  }
  loading.value = false;
}
onMounted(load);

async function submit() {
  error.value = '';
  submitting.value = true;
  try {
    if (tab.value === 'controller') {
      await api.post('/api/applications', { type: 'controller', ...controllerForm.value });
    } else {
      await api.post('/api/applications', { type: 'staff', ...staffForm.value });
    }
    showToast('申请已提交，请耐心等待审核');
    controllerForm.value = { nickname: '', hours: '', experience: '', motivation: '' };
    staffForm.value = { nickname: '', availableTime: '', motivation: '' };
    load();
  } catch (err) {
    error.value = err.message;
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">申请中心</div>
      <div class="page-desc">管制员申请与职员申请，审核结果将在申请列表中更新</div>
    </div>

    <div class="glass card" style="max-width: 720px">
      <div v-if="error" class="alert alert-err">{{ error }}</div>

      <template v-if="tab === 'controller'">
        <div class="card-title">管制员申请</div>
        <div class="card-sub">成为 CTY 管制团队的一员，为连飞活动提供管制服务</div>
        <div class="grid grid-2">
          <div class="field"><label class="label">称呼 <span style="color: var(--red)">*</span></label><input v-model="controllerForm.nickname" class="input" maxlength="20" placeholder="例如呼号或昵称" /></div>
          <div class="field"><label class="label">累计连飞时长 <span style="color: var(--red)">*</span></label><input v-model="controllerForm.hours" class="input" placeholder="如 120 小时" /></div>
          <div class="field" style="grid-column: 1 / -1"><label class="label">管制经验 <span style="color: var(--red)">*</span></label><input v-model="controllerForm.experience" class="input" placeholder="如 有 XX 平台 S2 放单经验" /></div>
        </div>
        <div class="field">
          <label class="label">申请动机</label>
          <textarea v-model="controllerForm.motivation" class="textarea" placeholder="谈谈您为什么想成为管制员…"></textarea>
        </div>
      </template>

      <template v-else>
        <div class="card-title">职员申请</div>
        <div class="card-sub">加入 CTY 运营团队，参与社区管理、活动策划与技术支持</div>
        <div class="grid grid-2">
          <div class="field"><label class="label">称呼 <span style="color: var(--red)">*</span></label><input v-model="staffForm.nickname" class="input" maxlength="20" placeholder="例如呼号或昵称" /></div>
          <div class="field"><label class="label">可参与工作时间 <span style="color: var(--red)">*</span></label>
            <input v-model="staffForm.availableTime" class="input" placeholder="如 工作日晚 19:00-23:00，周末全天" />
          </div>
        </div>
        <div class="field">
          <label class="label">申请理由 <span style="color: var(--red)">*</span></label>
          <textarea v-model="staffForm.motivation" class="textarea" placeholder="您的特长、经验与期望负责的方向…"></textarea>
        </div>
      </template>

      <button class="btn btn-primary btn-lg" :disabled="submitting" @click="submit">
        {{ submitting ? '提交中…' : '提交申请' }}
      </button>
    </div>

    <div class="glass card" style="max-width: 720px; margin-top: 16px">
      <div class="card-title">我的申请记录</div>
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else>
        <div v-for="a in myApps" :key="a.id" class="list-item">
          <div class="list-main">
            <div class="list-title">
              <span class="tag" :class="a.type === 'controller' ? 'tag-blue' : 'tag-purple'" style="margin-right: 8px">
                {{ a.type === 'controller' ? '管制员' : '职员' }}
              </span>
              {{ a.nickname }} · {{ fmtTime(a.created_at) }}
            </div>
            <div class="list-sub" v-if="a.review_note">审核意见：{{ a.review_note }}</div>
          </div>
          <span class="tag" :class="APP_STATUS[a.status]?.cls">{{ APP_STATUS[a.status]?.text }}</span>
        </div>
        <div v-if="!myApps.length" class="empty">暂无申请记录</div>
      </template>
    </div>
  </div>
</template>
