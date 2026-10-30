<script setup>
import { ref } from 'vue';
import { router } from './router/index.js';
import { toast } from './utils.js';
import AppShell from './AppShell.vue';
import AppModal from './components/AppModal.vue';
import CookieConsent from './components/CookieConsent.vue';

// 路由懒加载进度：新页面加载期间顶部显示加载条
const routeLoading = ref(false);
let showTimer = null;
router.beforeEach((to, from, next) => {
  // 延迟 120ms 再显示，避免快速切换时进度条闪烁
  clearTimeout(showTimer);
  showTimer = setTimeout(() => {
    routeLoading.value = true;
  }, 120);
  next();
});
router.afterEach(() => {
  clearTimeout(showTimer);
  routeLoading.value = false;
});
router.onError(() => {
  clearTimeout(showTimer);
  routeLoading.value = false;
});
</script>

<template>
  <div class="aurora"></div>

  <!-- 路由加载条 -->
  <transition name="toast-fade">
    <div v-if="routeLoading" class="route-progress"></div>
  </transition>

  <AppShell />
  <AppModal />
  <CookieConsent />
  <transition name="toast-fade">
    <div v-if="toast.visible" class="toast">{{ toast.message }}</div>
  </transition>
</template>
