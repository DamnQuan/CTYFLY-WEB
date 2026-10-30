<script setup>
/**
 * 新手引导，交互式
 *
 * 与「只看不动」版本的区别：action='click' 的步骤会要求用户真的点下去。
 * 做法是在遮罩上围绕高亮区域挖出 4 块挡板：
 *   - 高亮区域内的点击穿透到真实元素，菜单真的展开、页面真的跳转
 *   - 高亮区域外仍然被挡住，避免用户在引导途中点到别的地方跑丢
 * 点击命中目标后自动进入下一步；不想点也可以「跳过这步」。
 *
 * 高亮本身用「透明矩形 + 超大 box-shadow」压暗四周，不用 SVG 遮罩、不克隆 DOM。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { buildSteps, finishTour } from '../tour.js';
import Icon from './Icon.vue';

const props = defineProps({ isStaff: { type: Boolean, default: false } });
const emit = defineEmits(['open-sidebar']);

const route = useRoute();
const steps = buildSteps({ isStaff: props.isStaff });
const idx = ref(0);
const spot = ref(null);
const card = ref({ top: 0, left: 0, width: 300 });
const cardEl = ref(null);
const currentEl = ref(null);

const step = computed(() => steps[idx.value] || steps[0]);
const isFirst = computed(() => idx.value === 0);
const isLast = computed(() => idx.value === steps.length - 1);
/** 只有当这一步是交互步骤、且目标确实可见时才要求点击 */
const wantClick = computed(() => step.value.action === 'click' && !!currentEl.value);

const TARGET_SCOPE = '.side-link, .side-sublink, .side-group-toggle, .side-section';

function resolveTarget(target) {
  if (!target) return null;
  try {
    if (target.selector) return document.querySelector(target.selector);
    if (target.text) {
      const nodes = document.querySelectorAll(target.scope || TARGET_SCOPE);
      for (const el of nodes) {
        if ((el.innerText || '').trim().startsWith(target.text)) return el;
      }
    }
  } catch { /* 忽略 */ }
  return null;
}

function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  if (!(r.width > 2 && r.height > 2 && r.right > 8 && r.left < window.innerWidth - 8
    && r.bottom > 0 && r.top < window.innerHeight)) return false;
  return !isClippedByAncestor(el, r);
}

/**
 * 元素是否被某个可裁剪的祖先，overflow: hidden/clip/auto/scroll 裁掉了。
 *
 * 典型场景：侧边栏二级菜单用 grid-template-rows 0fr 折叠，子项的**布局矩形依然存在**，
 * 只是视觉上被裁掉 —— 只看元素自身的 rect 会误判为「可见」，于是高亮挖洞挖到
 * 裁剪后的坐标上，正好落在别的菜单项上，用户截图里就是挖到了「连飞活动」，
 * 而点击又只认真正的目标元素，引导就会卡死。
 */
function isClippedByAncestor(el, r) {
  let node = el.parentElement;
  while (node && node !== document.body) {
    const s = window.getComputedStyle(node);
    if (/(hidden|clip|auto|scroll)/.test(s.overflowX + s.overflowY)) {
      const pr = node.getBoundingClientRect();
      const visH = Math.min(r.bottom, pr.bottom) - Math.max(r.top, pr.top);
      const visW = Math.min(r.right, pr.right) - Math.max(r.left, pr.left);
      if (visH <= 2 || visW <= 2) return true;   // 与裁剪容器没有可见交集 = 被收起
    }
    node = node.parentElement;
  }
  return false;
}

/** 目标在收起的二级菜单里时，自动把父级展开，自愈。
 *  用时间戳节流而不是「每步一次」：refresh 会连续定位两次，且展开是异步的，
 *  按步数一次性会把后续重试也挡掉，导致自愈失效。*/
let lastExpandAt = 0;

function layout() {
  const raw = resolveTarget(step.value.target);
  let el = raw;

  if (raw && !visible(raw)) {
    // 目标存在但被收起的二级菜单裁掉：替用户把父级展开，然后等动画结束重新定位。
    // 否则高亮会挖到裁剪坐标上、指到别的菜单项，引导就卡死了。
    const wrap = raw.closest('.sub-wrap');
    const toggle = wrap ? raw.closest('.side-group')?.querySelector('.side-group-toggle') : null;
    if (wrap && toggle && !wrap.classList.contains('open') && Date.now() - lastExpandAt > 1200) {
      lastExpandAt = Date.now();
      toggle.click();
      setTimeout(() => refresh(), 460);
      return;
    }
    el = null;
  }

  currentEl.value = el && visible(el) ? el : null;
  const cw = Math.min(310, window.innerWidth - 28);

  if (!currentEl.value) {
    spot.value = null;
    const ch = cardEl.value?.offsetHeight || 210;
    card.value = {
      left: Math.round((window.innerWidth - cw) / 2),
      top: Math.max(16, Math.round((window.innerHeight - ch) / 2)),
      width: cw,
    };
    return;
  }

  const r = currentEl.value.getBoundingClientRect();
  spot.value = {
    top: Math.round(r.top - 6),
    left: Math.round(r.left - 6),
    width: Math.round(r.width + 12),
    height: Math.round(r.height + 12),
  };

  const gap = 14;
  const ch = cardEl.value?.offsetHeight || 210;
  let left;
  let top;
  if (r.right + gap + cw <= window.innerWidth - 10) {
    left = r.right + gap;                       // 优先放右侧，侧边栏项
    top = r.top - 8;
  } else if (r.left - gap - cw >= 10) {
    left = r.left - gap - cw;
    top = r.top - 8;
  } else {
    left = Math.min(Math.max(10, r.left), window.innerWidth - cw - 10);
    top = r.bottom + gap;
    if (top + ch > window.innerHeight - 10) top = Math.max(10, r.top - gap - ch);
  }
  top = Math.min(Math.max(10, top), Math.max(10, window.innerHeight - ch - 10));
  card.value = { left: Math.round(left), top: Math.round(top), width: cw };
}

/** 围绕高亮区挖洞的 4 块挡板；没有高亮时退化成整屏一块 */
const blockers = computed(() => {
  const W = window.innerWidth;
  const H = window.innerHeight;
  const s = spot.value;
  if (!s) return [{ top: '0px', left: '0px', width: W + 'px', height: H + 'px' }];
  return [
    { top: '0px', left: '0px', width: W + 'px', height: Math.max(0, s.top) + 'px' },
    { top: (s.top + s.height) + 'px', left: '0px', width: W + 'px', height: Math.max(0, H - s.top - s.height) + 'px' },
    { top: s.top + 'px', left: '0px', width: Math.max(0, s.left) + 'px', height: s.height + 'px' },
    { top: s.top + 'px', left: (s.left + s.width) + 'px', width: Math.max(0, W - s.left - s.width) + 'px', height: s.height + 'px' },
  ];
});

const spotStyle = computed(() => (spot.value
  ? { top: spot.value.top + 'px', left: spot.value.left + 'px', width: spot.value.width + 'px', height: spot.value.height + 'px' }
  : {}));

async function refresh() {
  await nextTick();
  layout();
  await nextTick();   // 卡片渲染后高度才准，再校正一次
  layout();
}

watch(idx, () => {
  maybeOpenSidebar();
  refresh();
});
// 点了侧边栏之后会发生路由跳转，等新页面渲染出来再定位下一步的目标
watch(() => route.fullPath, () => { setTimeout(refresh, 220); });

/** 目标在侧边栏里但侧边栏收着，手机端是抽屉时，让外层把抽屉打开*/
function needsSidebar(target) {
  if (!target) return false;
  if (target.selector) return target.selector.startsWith('.sidebar') || target.selector.startsWith('.side-');
  return !!target.text;   // 按文案定位的都是侧边栏项
}

function maybeOpenSidebar() {
  if (!needsSidebar(step.value.target)) return;
  const bar = document.querySelector('.sidebar');
  if (!bar) return;
  const r = bar.getBoundingClientRect();
  const shown = r.width > 2 && r.left > -r.width * 0.5;   // 抽屉收起时会被 transform 推到屏幕外
  if (!shown) {
    emit('open-sidebar');
    setTimeout(refresh, 460);   // 等抽屉动画结束再定位
  }
}

let advancing = false;

function onDocClick(e) {
  if (!wantClick.value || advancing) return;
  const el = currentEl.value;
  if (el && (el === e.target || el.contains(e.target))) {
    // 这次点击照常生效，展开菜单 / 跳转页面，稍等动画与渲染再进下一步
    advancing = true;
    setTimeout(() => { advancing = false; next(); }, 520);
  }
}

function next() {
  if (isLast.value) return done();
  idx.value += 1;
}

function prev() {
  if (idx.value > 0) idx.value -= 1;
}

function done() {
  finishTour();
}

function onKey(e) {
  if (e.key === 'Escape') done();
  else if (e.key === 'ArrowRight' || e.key === 'Enter') next();
  else if (e.key === 'ArrowLeft') prev();
}

let domObserver = null;
let domTimer = null;

/** 侧边栏的展开/收起、抽屉开合都是 class/子树变化，Vue 不会主动通知引导组件。
 *  不观察的话：用户手动收起二级菜单后，高亮会停在旧坐标上 —— 而旧坐标处
 *  现在是别的菜单项，用户截图里高亮指到了「连飞活动」，引导就卡死了。*/
function scheduleRefresh() {
  if (domTimer) return;
  domTimer = setTimeout(() => { domTimer = null; refresh(); }, 150);
}

onMounted(() => {
  refresh();
  maybeOpenSidebar();
  // 用捕获阶段：即使目标元素自己 stopPropagation 也能收到
  document.addEventListener('click', onDocClick, true);
  window.addEventListener('resize', layout, { passive: true });
  window.addEventListener('scroll', layout, { passive: true, capture: true });
  window.addEventListener('keydown', onKey);
  domObserver = new MutationObserver(scheduleRefresh);
  domObserver.observe(document.body, {
    attributes: true, attributeFilter: ['class'], childList: true, subtree: true,
  });
});

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick, true);
  window.removeEventListener('resize', layout);
  window.removeEventListener('scroll', layout, { capture: true });
  window.removeEventListener('keydown', onKey);
  domObserver?.disconnect();
  if (domTimer) { clearTimeout(domTimer); domTimer = null; }
});
</script>

<template>
  <div class="tour-root">
    <!-- 高亮：矩形本身透明，靠超大 box-shadow 把四周压暗 -->
    <div v-if="spot" class="tour-spot" :class="{ 'is-click': wantClick }" :style="spotStyle"></div>

    <!-- 四周挡板：只留高亮区域可以点 -->
    <div v-for="(b, i) in blockers" :key="i" class="tour-block" :style="b"></div>

    <div ref="cardEl" class="tour-card" :style="{ top: card.top + 'px', left: card.left + 'px', width: card.width + 'px' }">
      <div class="tour-head">
        <span class="tour-step">{{ idx + 1 }} / {{ steps.length }}</span>
        <button class="tour-skip" type="button" @click="done">跳过</button>
      </div>

      <h3 class="tour-title">{{ step.title }}</h3>
      <p class="tour-body">{{ step.body }}</p>

      <div v-if="wantClick" class="tour-hint">
        <span class="tour-hint-dot"></span> 请点击高亮的位置
      </div>

      <div class="tour-foot">
        <div class="tour-dots">
          <span
            v-for="(s, i) in steps"
            :key="i"
            class="tour-dot"
            :class="{ on: i === idx }"
          ></span>
        </div>
        <div class="tour-actions">
          <button v-if="!isFirst" class="btn btn-ghost btn-sm" type="button" @click="prev">
            <Icon name="chevron" :size="13" style="transform: rotate(90deg)" /> 上一步
          </button>
          <button class="btn btn-primary btn-sm" type="button" @click="next">
            {{ isLast ? '开始使用' : (wantClick ? '跳过这步' : '下一步') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tour-root {
  position: fixed;
  inset: 0;
  /* 高于小鲸灵 900 与页面 UI，低于诊断面板 99998。根节点不吃事件，交互由挡板和卡片负责*/
  z-index: 960;
  pointer-events: none;
}
.tour-block {
  position: absolute;
  z-index: 1;
  pointer-events: auto;      /* 挡住高亮区以外的点击 */
}
.tour-spot {
  position: absolute;
  z-index: 0;
  border-radius: 10px;
  box-shadow: 0 0 0 9999px rgba(10, 12, 18, 0.58);
  outline: 2px solid rgba(10, 132, 255, 0.9);
  pointer-events: none;
  transition: top 0.18s ease, left 0.18s ease, width 0.18s ease, height 0.18s ease;
}
@keyframes tour-pulse {
  0%, 100% { outline-color: rgba(10, 132, 255, 0.95); }
  50% { outline-color: rgba(10, 132, 255, 0.3); }
}
.tour-spot.is-click { animation: tour-pulse 1.4s ease-in-out infinite; }

.tour-card {
  position: absolute;
  z-index: 2;
  box-sizing: border-box;
  padding: 14px 16px 12px;
  /* 液态玻璃浮层：渐变描边 + 上缘 rim，折射由引擎注入，full 档*/
  border: 1px solid transparent;
  border-radius: 16px;
  background:
    linear-gradient(var(--modal-bg), var(--modal-bg)) padding-box,
    linear-gradient(165deg, var(--lg-rim), var(--lg-rim-2) 40%, var(--lg-rim-2) 62%, var(--lg-rim)) border-box;
  backdrop-filter: blur(18px) saturate(150%);
  -webkit-backdrop-filter: blur(18px) saturate(150%);
  box-shadow: inset 0 1px 0 var(--lg-rim-2), 0 18px 50px rgba(0, 0, 0, 0.34);
  color: var(--text);
  pointer-events: auto;      /* 卡片本身可点 */
}
.tour-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.tour-step {
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.3px;
  color: var(--gray);
}
.tour-skip {
  border: 0;
  background: none;
  padding: 0;
  color: var(--gray);
  font-size: 12.5px;
  cursor: pointer;
}
.tour-skip:hover { color: var(--text); text-decoration: underline; }
.tour-title {
  margin: 6px 0 6px;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.2px;
}
.tour-body {
  margin: 0;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.72;
}
.tour-hint {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 10px;
  padding: 7px 10px;
  border-radius: 9px;
  background: rgba(10, 132, 255, 0.12);
  color: var(--blue);
  font-size: 12.5px;
  font-weight: 600;
}
@keyframes tour-blink {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.35; transform: scale(0.7); }
}
.tour-hint-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--blue);
  animation: tour-blink 1.2s ease-in-out infinite;
}
.tour-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.tour-dots { display: flex; gap: 5px; flex-wrap: wrap; max-width: 120px; }
.tour-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--border);
}
.tour-dot.on { background: var(--blue); }
.tour-actions { display: flex; gap: 8px; margin-left: auto; }

@media (max-width: 720px) {
  .tour-card { padding: 13px 14px 11px; }
  .tour-title { font-size: 15px; }
  .tour-body { font-size: 12.5px; }
}
</style>
