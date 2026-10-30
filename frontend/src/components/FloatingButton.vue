<script setup>
/**
 * 通用悬浮按钮，零依赖，见交接文档 §26
 *
 * 用 position: fixed 悬浮在页面角落，z-index 高于内容；
 * 圆角 / 背景 / 阴影 / 图标 / 文案 / 尺寸 / 位置 / 颜色全部由 props 配置，
 * 点击通过 emit 'click' 抛给使用方，也支持原生事件透传。
 *
 * 用法：
 *   <FloatingButton icon="chevron" text="回到顶部" :bottom="150" :right="24" @click="toTop" />
 *   <FloatingButton size="lg" bg="#0a84ff" color="#fff" round @click="..."><Icon name="plus" /></FloatingButton>
 */
import { computed } from 'vue';
import Icon from './Icon.vue';

const props = defineProps({
  // 位置，px，可传数字或 CSS 长度字符串；四个方向都支持，默认右下角
  bottom: { type: [Number, String], default: 24 },
  right: { type: [Number, String], default: 24 },
  top: { type: [Number, String], default: null },
  left: { type: [Number, String], default: null },
  // 尺寸：预设 sm/md/lg 或直接给像素
  size: { type: [String, Number], default: 'md' },
  // 形状与外观
  radius: { type: [Number, String], default: null },
  round: { type: Boolean, default: false },      // 正圆，图标按钮
  bg: { type: String, default: null },           // 背景色，默认跟随品牌蓝
  color: { type: String, default: null },        // 文字/图标色
  shadow: { type: String, default: null },       // 阴影，默认柔和投影
  zIndex: { type: [Number, String], default: 880 },
  icon: { type: String, default: '' },           // Icon.vue 里的图标名
  iconSize: { type: [Number, String], default: null },
  text: { type: String, default: '' },           // 可选文案，不传就是纯图标
  title: { type: String, default: '' },          // 悬浮提示 + aria-label
  disabled: { type: Boolean, default: false },
  // 常显 / 由使用方控制显隐，如滚动到一定位置才出现
  visible: { type: Boolean, default: true },
});

const emit = defineEmits(['click']);

const SIZES = { sm: 36, md: 46, lg: 56 };
const px = (v) => (typeof v === 'number' ? `${v}px` : v);

const boxSize = computed(() => {
  const s = props.size;
  return typeof s === 'number' ? s : (SIZES[s] ?? SIZES.md);
});

const style = computed(() => {
  const st = {
    bottom: props.bottom === null ? 'auto' : px(props.bottom),
    right: props.right === null ? 'auto' : px(props.right),
    top: props.top === null ? 'auto' : px(props.top),
    left: props.left === null ? 'auto' : px(props.left),
    zIndex: String(props.zIndex),
    minWidth: `${boxSize.value}px`,
    height: `${boxSize.value}px`,
    borderRadius: props.round ? '50%' : px(props.radius ?? (props.text ? 999 : 16)),
  };
  if (props.bg) st.background = props.bg;
  if (props.color) st.color = props.color;
  if (props.shadow) st.boxShadow = props.shadow;
  return st;
});
</script>

<template>
  <button
    v-show="visible"
    type="button"
    class="fab"
    :class="{ 'is-round': round, 'has-text': !!text }"
    :style="style"
    :title="title || text || undefined"
    :aria-label="title || text || undefined"
    :disabled="disabled"
    @click="emit('click', $event)"
  >
    <slot>
      <Icon v-if="icon" :name="icon" :size="iconSize || (text ? 15 : 19)" />
      <span v-if="text" class="fab-text">{{ text }}</span>
    </slot>
  </button>
</template>

<style scoped>
/* 只放与内容有关的样式；位置/尺寸/颜色/圆角/阴影全部走内联 props 计算 */
.fab {
  position: fixed;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 14px;
  border: none;
  background: var(--blue);
  color: #fff;
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.18);
  transition: transform 0.16s ease, box-shadow 0.16s ease, opacity 0.2s ease, background 0.16s ease;
}
.fab.is-round { padding: 0; }
.fab:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 12px 26px rgba(15, 23, 42, 0.24); }
.fab:active:not(:disabled) { transform: translateY(0) scale(0.97); }
.fab:focus-visible { outline: none; box-shadow: 0 0 0 3.5px rgba(10, 132, 255, 0.28); }
.fab:disabled { opacity: 0.5; cursor: not-allowed; }
.fab-text { white-space: nowrap; }
</style>
