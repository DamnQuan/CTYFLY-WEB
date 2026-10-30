<script setup>
/**
 * iOS 风格滑动分段控件：选中块以回弹曲线平滑滑到目标项
 * 支持不等宽按钮，基于 offsetLeft/offsetWidth 实测定位
 *
 * 收纳式胶囊，collapsible：默认只显示当前选中项，悬停时其余选项
 * 以弹性曲线从选中项向两侧展开，移开后收缩回选中项，防误触延迟 140ms。
 * 展开过程中以 rAF 连续校正滑块位置，保证滑块全程贴合选中项。
 */
import { nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';

const props = defineProps({
  options: { type: Array, required: true }, // [{ value, label }]
  modelValue: { default: null },
  collapsible: { type: Boolean, default: false },
});
const emit = defineEmits(['update:modelValue']);

const wrap = ref(null);
const thumb = reactive({ x: 0, w: 0 });
const expanded = ref(false);
let collapseTimer = 0;
let trackRaf = 0;

function update() {
  const el = wrap.value?.querySelector('.seg-btn.on');
  if (!el) return;
  thumb.x = el.offsetLeft;
  thumb.w = el.offsetWidth;
}

/* 展开/收起动画期间滑块要跟着选中项移动：rAF 连续校正 ~460ms */
function trackDuring(ms = 460) {
  if (trackRaf) cancelAnimationFrame(trackRaf);
  const start = performance.now();
  const tick = () => {
    update();
    if (performance.now() - start < ms) trackRaf = requestAnimationFrame(tick);
    else trackRaf = 0;
  };
  requestAnimationFrame(tick);
}

function expand() {
  if (collapseTimer) { clearTimeout(collapseTimer); collapseTimer = 0; }
  expanded.value = true;
  nextTick(() => { update(); trackDuring(); });
}

function collapse() {
  /* 防抖：快速移入移出时延迟收缩，避免闪烁 */
  if (collapseTimer) clearTimeout(collapseTimer);
  collapseTimer = setTimeout(() => {
    collapseTimer = 0;
    expanded.value = false;
    nextTick(() => { update(); trackDuring(); });
  }, 140);
}

watch(
  () => props.modelValue,
  () => nextTick(update),
);

onMounted(() => {
  update();
  window.addEventListener('resize', update);
  document.fonts?.ready?.then(update).catch(() => {});
});
onUnmounted(() => {
  window.removeEventListener('resize', update);
  if (trackRaf) cancelAnimationFrame(trackRaf);
  if (collapseTimer) clearTimeout(collapseTimer);
});
</script>

<template>
  <div
    ref="wrap"
    class="seg"
    :class="{ collapsible, expanded }"
    @mouseenter="collapsible && expand()"
    @mouseleave="collapsible && collapse()"
  >
    <span
      class="seg-thumb"
      :style="{ transform: `translateX(${thumb.x}px)`, width: `${thumb.w}px` }"
    ></span>
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      class="seg-btn"
      :class="{ on: o.value === modelValue }"
      @click="emit('update:modelValue', o.value)"
    >{{ o.label }}</button>
  </div>
</template>
