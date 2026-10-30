<script setup>
/**
 * 形变提交按钮：矩形文字按钮 → 圆形状态球
 *
 * 状态机，由父组件持有，组件只负责表现：
 *   idle 矩形 + 文字
 *   loading 宽度/圆角平滑收拢成圆形，~320ms，文字淡出，圆内转圈；期间禁止重复点击
 *   success 圆球变绿 + 绿色对勾，描边绘制 + 缩放弹出
 *   error 圆球变红 + 左右摇晃，2 × 0.6s ≈ 1.2s，结束后 emit 'settle' 交还父组件置回 idle
 *
 * 无障碍：状态变化用 aria-live 播报；窄态下文字视觉隐藏但仍给屏幕阅读器；
 * 尊重 prefers-reduced-motion，关掉位移/摇晃类动画，仅保留必要的状态切换。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue';

const props = defineProps({
  status: { type: String, default: 'idle' }, // idle | loading | success | error
  label: { type: String, default: '登 录' },
  disabled: { type: Boolean, default: false },
});
const emit = defineEmits(['settle']);

const ERR_SHAKE_MS = 1200; // 与 CSS 里 2 × 0.6s 的摇晃时长对应

let settleTimer = null;
watch(
  () => props.status,
  (s) => {
    clearTimeout(settleTimer);
    if (s === 'error') {
      // 摇晃结束后由父组件把状态置回 idle，状态机不放在组件里，便于外部复用
      settleTimer = setTimeout(() => emit('settle'), ERR_SHAKE_MS);
    }
  },
);
onBeforeUnmount(() => clearTimeout(settleTimer));

const blocked = computed(
  () => props.disabled || props.status === 'loading' || props.status === 'success',
);
const srStatus = computed(
  () => ({ loading: '登录中', success: '登录成功', error: '登录失败，请重试' }[props.status] || ''),
);
// 窄态下按钮内已无可见文字，给读屏一个明确的名称
const ariaLabel = computed(() => srStatus.value || props.label);
const pressed = ref(false);
</script>

<template>
  <button
    class="morph-btn"
    :class="[`is-${status}`, { 'is-pressed': pressed }]"
    :disabled="blocked"
    :aria-busy="status === 'loading' ? 'true' : 'false'"
    :aria-label="ariaLabel"
    type="submit"
    @pointerdown="pressed = true"
    @pointerup="pressed = false"
    @pointerleave="pressed = false"
  >
    <span class="morph-btn__label">{{ label }}</span>

    <span class="morph-btn__mark" aria-hidden="true">
      <span v-if="status === 'loading'" class="morph-btn__spinner" />
      <svg v-else-if="status === 'success'" class="morph-btn__tick" viewBox="0 0 24 24">
        <path d="M5 12.6 10 17.5 19 7.6" />
      </svg>
      <!-- 失败：红球内画一个叉，两笔错开画出来-->
      <svg v-else-if="status === 'error'" class="morph-btn__cross" viewBox="0 0 24 24">
        <path d="M7.6 7.6 16.4 16.4" />
        <path d="M16.4 7.6 7.6 16.4" />
      </svg>
    </span>

    <span class="sr-only" role="status" aria-live="polite">{{ srStatus }}</span>
  </button>
</template>

<style scoped>
.morph-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 46px; /* 收拢后的圆直径就等于这个高度 */
  margin: 0;
  padding: 0 18px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--blue);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  overflow: hidden;
  /* 关键：宽度与圆角一起过渡，约 300ms，对齐本站其它 0.3s 动效节奏。
     缓动特意用 ease-in-out 系而不是带过冲的曲线 —— 后者前段太快，150ms 就走完大半，
     看起来像「瞬间变圆」而不是平滑形变。*/
  transition:
    width 0.32s cubic-bezier(0.4, 0, 0.2, 1),
    border-radius 0.32s cubic-bezier(0.4, 0, 0.2, 1),
    margin 0.32s cubic-bezier(0.4, 0, 0.2, 1),
    background 0.25s ease,
    box-shadow 0.3s ease,
    transform 0.12s ease;
}
.morph-btn:hover:not(:disabled) {
  background: var(--blue-hover);
}
.morph-btn:focus-visible {
  outline: 2px solid var(--blue);
  outline-offset: 3px;
}
.morph-btn.is-pressed {
  transform: scale(0.985);
}

/* 点击后：宽度收成圆、圆角到 50%，并水平居中 */
.morph-btn.is-loading,
.morph-btn.is-success,
.morph-btn.is-error {
  width: 46px;
  margin-left: auto;
  margin-right: auto;
  padding: 0;
  border-radius: 50%;
}
.morph-btn.is-loading {
  cursor: progress;
}
.morph-btn.is-success {
  background: var(--green);
  box-shadow: 0 8px 22px rgba(48, 209, 88, 0.35);
}
.morph-btn.is-error {
  background: var(--red);
  box-shadow: 0 8px 22px rgba(255, 59, 48, 0.35);
  animation: morph-shake 0.6s cubic-bezier(0.36, 0.07, 0.19, 0.97) 2;
}

/* 文字：淡出 + 轻微缩小 */
.morph-btn__label {
  transition:
    opacity 0.16s ease,
    transform 0.24s ease;
}
.morph-btn.is-loading .morph-btn__label,
.morph-btn.is-success .morph-btn__label,
.morph-btn.is-error .morph-btn__label {
  opacity: 0;
  transform: scale(0.86);
  /* 窄态下文字必须脱离文档流：只把 opacity 归零的话它仍占宽度，
     会把圆内的转圈/对勾挤到偏右，截图验收时发现的。*/
  position: absolute;
  pointer-events: none;
}

.morph-btn__mark {
  display: flex;
  align-items: center;
  justify-content: center;
}
.morph-btn__mark:empty {
  display: none; /* idle 时不占位，避免多出 6px 间隙 */
}

.morph-btn__spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: morph-spin 0.7s linear infinite;
}

.morph-btn__tick {
  width: 22px;
  height: 22px;
}
.morph-btn__tick path {
  fill: none;
  stroke: #fff;
  stroke-width: 2.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 26;
  stroke-dashoffset: 26;
  animation: morph-draw 0.3s ease-out 0.05s forwards;
}
.morph-btn.is-success .morph-btn__mark {
  animation: morph-pop 0.34s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

/* 失败态的叉：与对勾同一套画法，两笔错开画，第二笔晚 0.14s
   线段长 = √ 8.8² + 8.8² ≈ 12.4，dasharray 取 13 保证画满*/
.morph-btn__cross {
  width: 22px;
  height: 22px;
}
.morph-btn__cross path {
  fill: none;
  stroke: #fff;
  stroke-width: 2.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 13;
  stroke-dashoffset: 13;
  animation: morph-draw 0.22s ease-out 0.04s forwards;
}
.morph-btn__cross path:nth-child(2) {
  animation-delay: 0.16s;
}
.morph-btn.is-error .morph-btn__mark {
  animation: morph-pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes morph-spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes morph-draw {
  to {
    stroke-dashoffset: 0;
  }
}
@keyframes morph-pop {
  0% {
    transform: scale(0.4);
    opacity: 0.4;
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}
@keyframes morph-shake {
  10%,
  90% {
    transform: translateX(-2px);
  }
  20%,
  80% {
    transform: translateX(4px);
  }
  30%,
  50%,
  70% {
    transform: translateX(-6px);
  }
  40%,
  60% {
    transform: translateX(6px);
  }
}

/* 读屏专用：视觉隐藏但可被朗读 */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (prefers-reduced-motion: reduce) {
  .morph-btn,
  .morph-btn__label {
    transition: none;
  }
  .morph-btn.is-error {
    animation: none;
  }
  .morph-btn__tick path,
  .morph-btn__cross path {
    animation: none;
    stroke-dashoffset: 0;
  }
  .morph-btn.is-success .morph-btn__mark,
  .morph-btn.is-error .morph-btn__mark {
    animation: none;
  }
  .morph-btn__spinner {
    animation-duration: 1.4s;
  }
}
</style>
