<script setup>
/**
 * 统一风格勾选控件，替代原生 checkbox
 * variant: check，方形勾选| switch，iOS 开关
 */
import Icon from './Icon.vue';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  label: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  variant: { type: String, default: 'check' },
});
const emit = defineEmits(['update:modelValue']);

function onToggle() {
  if (props.disabled) return;
  emit('update:modelValue', !props.modelValue);
}
</script>

<template>
  <label
    class="cb"
    :class="[`cb-${variant}`, { checked: modelValue, disabled }]"
  >
    <input
      type="checkbox"
      class="cb-native"
      :checked="modelValue"
      :disabled="disabled"
      @change="onToggle"
    />
    <!-- 方形勾选 -->
    <span v-if="variant === 'check'" class="cb-box">
      <Icon v-if="modelValue" name="check" :size="12" />
    </span>
    <!-- iOS 开关 -->
    <span v-else class="cb-track"><span class="cb-knob"></span></span>
    <span v-if="label" class="cb-label">{{ label }}</span>
  </label>
</template>

<style scoped>
.cb {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  cursor: pointer;
  user-select: none;
}
.cb.disabled { cursor: not-allowed; opacity: 0.45; }
.cb-native {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

/* 方形勾选 */
.cb-box {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  border: 1.5px solid var(--input-border);
  background: var(--glass-strong);
  color: #fff;
  transition: background 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
}
.cb:hover .cb-box { border-color: var(--blue); }
.cb.checked .cb-box {
  background: var(--blue);
  border-color: var(--blue);
  transform: scale(1.04);
}
.cb:focus-within .cb-box { box-shadow: 0 0 0 3.5px rgba(0, 113, 227, 0.18); }

/* iOS 开关 */
.cb-track {
  position: relative;
  width: 46px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 980px;
  background: var(--surface-strong);
  transition: background 0.24s ease;
}
.cb.checked .cb-track { background: var(--green); }
.cb-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  transition: transform 0.24s cubic-bezier(0.3, 1.2, 0.5, 1);
}
.cb.checked .cb-knob { transform: translateX(18px); }

.cb-label { font-size: 13.5px; color: var(--text); }
</style>
