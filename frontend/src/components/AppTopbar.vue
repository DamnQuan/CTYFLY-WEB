<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { getConsent } from '../consent.js';
import { getTheme, setTheme } from '../theme.js';
import SegmentedTabs from './SegmentedTabs.vue';
import Icon from './Icon.vue';
// 站点标志：走构建产物，文件名带 hash，可长期缓存
import logoMark from '../assets/logo-mark.webp';

const props = defineProps({
  showBrand: { type: Boolean, default: false },
  // 顶部栏导航模式下内联复用本组件，时钟/时区/主题：只去掉 bar 外壳，不重复实现
  compact: { type: Boolean, default: false },
});

/* ---------- 滚动收拢，纯前端行为 ----------
 * 状态一：页面在顶部 —— 外层全宽、无背景，与页面融合；
 * 状态二：scrollY 越过阈值 —— 内层胶囊收窄居中、白底圆角阴影，样式见 main.css .topbar-shell。
 * 只在独立顶栏，非 topbar-inline 内联复用时启用，内联形态跟随 .topnav 自己的外壳。*/
const isCompact = ref(false);
const SCROLL_THRESHOLD = 50;
function onScroll() {
  isCompact.value = window.scrollY > SCROLL_THRESHOLD;
}

/* 时区：utc | bj，持久化，尊重存储同意*/
const TZ_KEY = 'ctyfly_tz';
const tz = ref((() => {
  try { return localStorage.getItem(TZ_KEY) === 'bj' ? 'bj' : 'utc'; } catch { return 'utc'; }
})());
const theme = ref(getTheme());
const timeText = ref('');

const tzOptions = [
  { value: 'utc', label: 'UTC' },
  { value: 'bj', label: '北京时间' },
];
const themeOptions = [
  { value: 'auto', label: 'AUTO' },
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
];

let timer = null;
function tick() {
  const now = new Date();
  // 本地时间 -> 目标时区，UTC 或 UTC+8
  const target = new Date(now.getTime() + now.getTimezoneOffset() * 60000 + (tz.value === 'bj' ? 8 : 0) * 3600000);
  const p = (n) => String(n).padStart(2, '0');
  timeText.value =
    `${target.getFullYear()}-${p(target.getMonth() + 1)}-${p(target.getDate())} ` +
    `${p(target.getHours())}:${p(target.getMinutes())}:${p(target.getSeconds())}`;
}

onMounted(() => {
  tick();
  timer = setInterval(tick, 1000);
  if (!props.compact) {
    onScroll();   // 处理带定位刷新/回退进页面的情况，不能假设一定在顶部
    window.addEventListener('scroll', onScroll, { passive: true });
  }
});
onUnmounted(() => {
  clearInterval(timer);
  // 组件卸载必须摘掉滚动监听，否则长会话里会累积无名监听器，内存泄漏
  window.removeEventListener('scroll', onScroll);
});

function setTz(v) {
  tz.value = v;
  // 用户选择"仅必需"时：本次会话内生效但不持久化
  if (getConsent() !== 'essential') {
    try { localStorage.setItem(TZ_KEY, v); } catch { /* 忽略 */ }
  }
  tick();
}

/* ---------- 深色/浅色切换：从按钮位置圆形扩散覆盖全屏，反向切换原路收回 ----------
 * 用 View Transitions API 做「新主题从点击点扩散」；不支持或用户要求减少动效时直接切换。
 * 点击坐标由主题控件的 pointerdown 记录，SegmentedTabs 不回调事件对象。*/
let themeClickPoint = null;
const themeControlEl = ref(null);
function rememberThemePoint(e) {
  if (e && typeof e.clientX === 'number') themeClickPoint = { x: e.clientX, y: e.clientY };
}
function prefersReducedMotion() {
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
function setThemeMode(v) {
  const prev = theme.value;
  theme.value = v;
  // 位置：优先用刚点的那一下；没有，如键盘操作就退回主题控件中心
  let point = themeClickPoint;
  if (!point) {
    const el = themeControlEl.value?.getBoundingClientRect();
    point = el
      ? { x: el.left + el.width / 2, y: el.top + el.height / 2 }
      : { x: window.innerWidth - 60, y: 40 };
  }
  themeClickPoint = null;

  const startVT = document.startViewTransition?.bind(document);
  // 同主题重复点击、不支持 VT、减少动效 → 直接切
  if (!startVT || prefersReducedMotion() || prev === v) {
    setTheme(v);
    return;
  }

  const { x, y } = point;
  // 半径取到最远角，保证圆能覆盖整屏
  const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  const transition = startVT(() => setTheme(v));
  transition.ready.then(() => {
    document.documentElement.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
      {
        duration: 460,
        easing: 'ease-in-out',
        pseudoElement: '::view-transition-new(root)',
      },
    );
  }).catch(() => { /* 过渡被取消：主题已在回调里切换完成，无需补救 */ });
}
</script>

<template>
  <component :is="compact ? 'div' : 'header'" :class="compact ? 'topbar-inline' : 'topbar'">
    <!-- 壳层 = 胶囊本体：滚动收拢只改这一层，宽度/边距/圆角/阴影/背景，
         内部结构与间距两种状态完全一致；内联复用时 display:contents 透明化-->
    <div class="topbar-shell" :class="{ compact: isCompact }">
      <div class="topbar-clock">
        <router-link v-if="showBrand" class="topbar-logo" to="/">
          <img class="brand-mark" :src="logoMark" alt="" width="20" height="20" /> CTYFLY
        </router-link>
        <span class="topbar-label">{{ tz === 'utc' ? 'UTC 时间：' : '北京时间：' }}</span>
        <span class="topbar-time">{{ timeText }}</span>
      </div>

      <div class="topbar-controls">
        <slot name="actions" />
        <a
          class="topbar-github"
          href="https://github.com/yuanshen-123-ui/CTYFLY-WEB"
          target="_blank"
          rel="noopener noreferrer"
          title="GitHub 开源仓库"
          aria-label="GitHub 开源仓库"
        >
          <Icon name="github" :size="16" />
        </a>
        <SegmentedTabs collapsible :options="tzOptions" :model-value="tz" @update:model-value="setTz" />
        <!-- 主题控件：pointerdown 记录点击位置，供「圆形扩散」过渡作为圆心 -->
        <span ref="themeControlEl" class="theme-control" @pointerdown="rememberThemePoint">
          <SegmentedTabs collapsible :options="themeOptions" :model-value="theme" @update:model-value="setThemeMode" />
        </span>
      </div>
    </div>
  </component>
</template>
