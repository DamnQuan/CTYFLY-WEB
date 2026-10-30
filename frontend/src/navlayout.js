/**
 * 导航布局偏好，跨组件共享：'side' 左侧边栏，默认 / 'top' 顶部横排
 *
 * 与 pet.js 同款做法：写 localStorage，读写失败时本次会话内仍然生效。
 * 窄屏，≤860px，与 main.css 的移动端断点一致下顶部横排放不下，
 * 一律回退成侧边抽屉 —— isTopLayout 已经把这件事算好，组件直接用即可。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { getConsent } from './consent.js';

const KEY = 'ctyfly_nav_layout';
const NARROW_MAX = 860;

function read() {
  try {
    return localStorage.getItem(KEY) === 'top' ? 'top' : 'side';
  } catch {
    return 'side';
  }
}

function write(v) {
  // 用户选择「仅必需」存储同意时不落盘：本次会话内仍然生效
  if (getConsent() === 'essential') return;
  try {
    if (v === 'top') localStorage.setItem(KEY, 'top');
    else localStorage.removeItem(KEY);
  } catch { /* 忽略：会话内生效 */ }
}

export const navLayout = ref(read());

export function setNavLayout(v) {
  navLayout.value = v === 'top' ? 'top' : 'side';
  write(navLayout.value);
}

export function toggleNavLayout() {
  setNavLayout(navLayout.value === 'top' ? 'side' : 'top');
}

/** 视口是否窄屏，顶部横排不可用*/
const narrow = ref(false);
export const isNarrow = narrow;

export function installNavLayoutWatcher() {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {};
  const mq = window.matchMedia(`(max-width: ${NARROW_MAX}px)`);
  narrow.value = mq.matches;
  const onChange = (e) => { narrow.value = e.matches; };
  if (mq.addEventListener) mq.addEventListener('change', onChange);
  else mq.addListener(onChange);
  return () => {
    if (mq.removeEventListener) mq.removeEventListener('change', onChange);
    else mq.removeListener(onChange);
  };
}

/** 真正生效的布局：顶部偏好 + 窄屏 → 回退侧边栏 */
export const isTopLayout = computed(() => navLayout.value === 'top' && !narrow.value);

/* ---------- 侧边栏收拢，图标栏模式，2026-10-16 站长要求 ----------
 * 桌面端把侧边栏从 240px 收成 68px 的图标栏，内容区跟着回流；状态持久化，
 * 与布局偏好同款做法，仅必需同意时不落盘。窄屏是抽屉形态，不存在「收拢」，
 * 所以 isCollapsed 把 narrow 一并算进去 —— 组件直接用它即可。
 */
const COLLAPSE_KEY = 'ctyfly_nav_collapsed';

function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

function writeCollapsed(v) {
  if (getConsent() === 'essential') return;
  try {
    if (v) localStorage.setItem(COLLAPSE_KEY, '1');
    else localStorage.removeItem(COLLAPSE_KEY);
  } catch { /* 忽略：会话内生效 */ }
}

export const navCollapsed = ref(readCollapsed());

export function setNavCollapsed(v) {
  navCollapsed.value = !!v;
  writeCollapsed(navCollapsed.value);
}

export function toggleNavCollapsed() {
  setNavCollapsed(!navCollapsed.value);
}

/** 真正生效的收拢：窄屏是抽屉，不适用 */
export const isCollapsed = computed(() => navCollapsed.value && !narrow.value);

/** 组件里一行接入，AppShell 调用*/
export function useNavLayout() {
  let dispose = null;
  onMounted(() => { dispose = installNavLayoutWatcher(); });
  onUnmounted(() => { if (dispose) dispose(); });
  return {
    navLayout, isTopLayout, isNarrow, setNavLayout, toggleNavLayout,
    navCollapsed, isCollapsed, setNavCollapsed, toggleNavCollapsed,
  };
}
