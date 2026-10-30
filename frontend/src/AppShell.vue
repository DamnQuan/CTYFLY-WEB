<script setup>
import { computed, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import Sidebar from './components/Sidebar.vue';
import TopNav from './components/TopNav.vue';
import AppTopbar from './components/AppTopbar.vue';
import DeskPet from './components/DeskPet.vue';
import FloatingButton from './components/FloatingButton.vue';
import OnboardingTour from './components/OnboardingTour.vue';
import Icon from './components/Icon.vue';
import { installViewSync } from './diag.js';
import { useAuthStore } from './stores/auth.js';
import { petEnabled } from './pet.js';
import { tourDone } from './tour.js';
import { useNavLayout } from './navlayout.js';
import { initVersionCheck } from './versionCheck.js';

const auth = useAuthStore();
// 导航布局偏好：'side'，默认或 'top'；窄屏自动回退侧边抽屉，见 navlayout.js
// isCollapsed：侧边栏收拢成图标栏，仅侧边栏布局 + 宽屏生效，见 navlayout.js
const { isTopLayout, navLayout, isNarrow, isCollapsed } = useNavLayout();

/* ---------- 布局切换过渡，侧边栏 ⇄ 顶部栏 ----------
 * Sidebar 与 TopNav 结构不同，直接 v-if 硬切会让主内容瞬间横跳 240px，跳变可见。
 * 编排成三段式，把「结构性换挂载」藏进主内容不可见的窗口里：
 *   0ms 旧导航开始退出，滑出 + 淡出，主内容开始淡出
 *   ~190ms 主内容已不可见 → 此刻才真正换挂载 + margin 240↔0，重排发生在看不见的时候
 *   ~190ms 新导航入场，顶部栏下落 / 侧边栏滑入，主内容淡入并轻轻上浮归位
 *   ~520ms 清理过渡类
 * 只在「用户主动切换」时播放：watch 的是 navLayout 偏好而非 isTopLayout ——
 * 视口跨过 860px 触发的窄屏回退必须瞬时生效，不能跟着窗口缩放播动画。
 * prefers-reduced-motion 下跳过编排直接换，见 CSS 与下方 reduce 分支。
 */
const switching = ref(false);
const swapped = ref(false);          // 是否已到「换挂载」时刻
const leavingLayout = ref('');       // 正在退出的布局：'side' | 'top'
let swapTimers = [];

/** 过渡期间壳层处于哪种布局：换挂载，190ms 之前 = 旧布局，正在退出，之后 = 新布局，正在入场
 *  注意不能写成 switching ? swapped : isTopLayout —— 那样 top→side 方向会在 t=0 立刻换挂载，
 *  旧导航的退出动画没机会播、margin 也在可见状态下跳变，两个方向只有一个是好的，踩过。*/
const shellNavTop = computed(() => {
  if (!switching.value) return isTopLayout.value;
  const enteringTop = navLayout.value === 'top';
  return swapped.value ? enteringTop : !enteringTop;
});

watch(navLayout, () => {
  // 守卫只有一条：窄屏下翻转偏好，生效布局不变，没有过渡可播。
  //不要写 isTopLayout === enteringTop —— 宽屏下翻偏好它必然相等，会把动画整个跳过
  if (isNarrow.value) return;
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) return;

  switching.value = true;
  swapped.value = false;
  leavingLayout.value = navLayout.value === 'top' ? 'side' : 'top';
  swapTimers.forEach(clearTimeout);
  swapTimers = [
    setTimeout(() => { swapped.value = true; }, 190),
    setTimeout(() => {
      switching.value = false;
      swapped.value = false;
      leavingLayout.value = '';
    }, 520),
  ];
});
onBeforeUnmount(() => swapTimers.forEach(clearTimeout));

const route = useRoute();
const router = useRouter();
// 落地页、认证页、政策页与隐私政策不渲染侧边栏，顶栏带 Logo，其余页面侧边栏 + 纯功能顶栏。
// 路由尚未解析出 name 时按「独立页」处理：否则首帧会误挂载侧边栏，
// 触发它 onMounted 里的路由预热，未登录用户在登录页就会白下 9 个业务页面 chunk。
const noSidebar = computed(() => {
  if (!route.name) return true;
  return ['home', 'login', 'register', 'forgot', 'cookies', 'public-airline', 'privacy', 'about', 'terms', 'survey'].includes(route.name);
});
const sidebarOpen = ref(false);
// 移动端抽屉不再随路由变化自动收起，站长 2026-10-06 要求：
// 点菜单项导航后抽屉保持展开，由用户点遮罩/抽屉内的叉来收起

// 视图若未跟随路由更新，数秒内自动恢复，并由诊断面板留下记录
onMounted(() => installViewSync(router));

// 长驻标签页检测部署更新，toast 提醒刷新，SPA 旧标签页不会自动换 JS，见 versionCheck.js
onMounted(() => initVersionCheck());

// 液态玻璃，仅导航层：顶栏/侧栏/弹层。动态 import 保持首屏 chunk 不变；
// 浏览器不支持或初始化失败时保持纯 CSS 磨砂，不影响功能。
let lgDispose = null;
onMounted(async () => {
  try {
    const { initLiquidGlass } = await import('./lib/liquidGlass.js');
    lgDispose = initLiquidGlass();
  } catch { /* 回退纯 CSS 磨砂 */ }
});
onUnmounted(() => {
  if (lgDispose) {
    lgDispose();
    lgDispose = null;
  }
});

/* ---------- 回到顶部：FloatingButton 通用组件的一个实例 ----------
   滚过 400px 才出现；位置放在桌宠上方，桌宠固定在右下角，身体高约 135px。
   组件本身是纯 props 驱动，位置/尺寸/颜色/圆角/阴影/图标/文案/点击，
   这里只演示一种用法，换别的用途不需要改组件。*/
const showToTop = ref(false);
function onShellScroll() {
  showToTop.value = window.scrollY > 400;
}
function toTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
onMounted(() => {
  window.addEventListener('scroll', onShellScroll, { passive: true });
  onShellScroll();
});
onUnmounted(() => window.removeEventListener('scroll', onShellScroll));
</script>

<template>
  <!-- 独立页面：顶栏带 Logo，无侧边栏 -->
  <div v-if="noSidebar" class="plain-shell">
    <AppTopbar show-brand />
    <!--
      注意：这里刻意不用 <transition mode="out-in"> 包裹 router-view。
      标签页在后台时浏览器不执行动画，退场动画的 transitionend 不触发，
      旧页面就会一直退不了场、新页面永不挂载——表现为「导航了但页面不变、点不动，
      只能刷新恢复」。视图切换必须即时生效，不能依赖动画完成。
    -->
    <div class="view-host" :data-view-route="route.fullPath">
      <router-view />
    </div>
  </div>

  <!-- 工作台页面：侧边栏，默认或顶部栏导航 + 顶栏-->
  <div v-else class="app-shell" :class="{ 'nav-top': shellNavTop, 'nav-switching': switching, 'nav-collapsed': isCollapsed && !shellNavTop }">
    <!-- 顶部栏模式：导航横排 + 悬停通栏面板，顶栏控件已内联进去，不再单独渲染 AppTopbar -->
    <TopNav
      v-if="shellNavTop"
      :class="{ 'nav-exit-top': switching && leavingLayout === 'top' }"
    />
    <template v-else>
      <Sidebar
        :open="sidebarOpen"
        :class="{ 'nav-exit-side': switching && leavingLayout === 'side' }"
        @close="sidebarOpen = false"
      />
      <button
        class="menu-fab"
        :class="{ 'is-open': sidebarOpen }"
        :title="sidebarOpen ? '关闭菜单' : '打开菜单'"
        @click="sidebarOpen = !sidebarOpen"
      >
        <Icon :name="sidebarOpen ? 'x' : 'menu'" :size="17" />
      </button>
    </template>
    <main class="app-main">
      <AppTopbar v-if="!shellNavTop" />
      <!-- 同上：视图切换不得被转场动画门控 -->
      <div class="view-host" :data-view-route="route.fullPath">
        <router-view />
      </div>
    </main>
  </div>

  <!-- 桌面小鲸灵：仅登录用户可见；关掉后可在个人中心重新打开，详见 DeskPet.vue-->
  <DeskPet v-if="auth.isLoggedIn && petEnabled" />

  <!-- 回到顶部：FloatingButton 的一个实例，纯 props 配置；位置抬高避开右下角的桌宠-->
  <FloatingButton
    v-if="!noSidebar"
    class="to-top"
    icon="chevron"
    text="回到顶部"
    title="回到顶部"
    :visible="showToTop"
    :bottom="152"
    :right="24"
    :z-index="870"
    @click="toTop"
  />

  <!-- 新手引导：讲的是左侧边栏，因此只在侧边栏布局下出现；切换过渡期间也不出现 -->
  <OnboardingTour
    v-if="auth.isLoggedIn && !noSidebar && !tourDone && !isTopLayout && !switching"
    :is-staff="auth.isStaff"
    @open-sidebar="sidebarOpen = true"
  />
</template>
