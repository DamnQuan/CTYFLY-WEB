<script setup>
/**
 * 统一风格下拉选择，替代原生 <select>
 * options: [{ value, label, hint? }]
 * 面板 Teleport 到 body，避免被相邻卡片的层叠上下文遮挡，按触发框定位
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import Icon from './Icon.vue';

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '请选择' },
  disabled: { type: Boolean, default: false },
});
const emit = defineEmits(['update:modelValue']);

const rootEl = ref(null);
const triggerEl = ref(null);
const panelEl = ref(null);
const open = ref(false);
const panelStyle = ref({});

const current = computed(() => props.options.find((o) => o.value === props.modelValue));
const displayText = computed(() => current.value?.label ?? (props.modelValue === '' ? '' : String(props.modelValue)));

function updatePosition() {
  const rect = triggerEl.value?.getBoundingClientRect();
  if (!rect) return;
  const panelH = Math.min(props.options.length * 40 + 12, 260);
  let left = Math.min(Math.max(8, rect.left), window.innerWidth - rect.width - 8);
  let top;
  if (window.innerHeight - rect.bottom < panelH && rect.top > panelH) {
    top = Math.max(8, rect.top - panelH - 6);
  } else {
    top = rect.bottom + 6;
  }
  panelStyle.value = { left: `${left}px`, top: `${top}px`, width: `${rect.width}px` };
}

function toggle() {
  if (props.disabled) return;
  open.value = !open.value;
  if (open.value) nextTick(() => { updatePosition(); centerSelected(); });
}

/** 展开时把列表滚动到「当前选中项垂直居中」的位置，选项少、无需滚动时自然不动*/
function centerSelected() {
  const panel = panelEl.value;
  if (!panel) return;
  const active = panel.querySelector('.sm-option.active');
  if (!active) return;
  const p = panel.getBoundingClientRect();
  const a = active.getBoundingClientRect();
  // 用两者当前位置求差，避免依赖 offsetParent，面板被 Teleport 到 body 且是 fixed
  panel.scrollTop += (a.top - p.top) - (p.height - a.height) / 2;
}
function onWindowChange() {
  if (open.value) updatePosition();
}
onMounted(() => {
  window.addEventListener('scroll', onWindowChange, true);
  window.addEventListener('resize', onWindowChange);
});
onUnmounted(() => {
  window.removeEventListener('scroll', onWindowChange, true);
  window.removeEventListener('resize', onWindowChange);
});

function pick(option) {
  emit('update:modelValue', option.value);
  open.value = false;
}

function onDocClick(e) {
  if (!open.value) return;
  const t = e.target;
  if (rootEl.value?.contains(t) || panelEl.value?.contains(t)) return;
  open.value = false;
}
function onKey(e) {
  if (e.key === 'Escape') open.value = false;
}
onMounted(() => {
  document.addEventListener('mousedown', onDocClick);
  document.addEventListener('keydown', onKey);
});
onUnmounted(() => {
  document.removeEventListener('mousedown', onDocClick);
  document.removeEventListener('keydown', onKey);
});
</script>

<template>
  <div ref="rootEl" class="sm" :class="{ disabled }">
    <button ref="triggerEl" type="button" class="sm-trigger" :disabled="disabled" @click="toggle">
      <span class="sm-value" :class="{ empty: !displayText }">{{ displayText || placeholder }}</span>
      <Icon name="chevron" :size="14" class="sm-chevron" :class="{ open }" />
    </button>

    <Teleport to="body">
      <transition name="sm-pop">
        <div v-if="open" ref="panelEl" class="sm-panel" :style="panelStyle">
          <div v-if="!options.length" class="sm-empty">暂无可选项</div>
          <button
            v-for="o in options"
            :key="String(o.value)"
            type="button"
            class="sm-option"
            :class="{ active: o.value === modelValue }"
            @click="pick(o)"
          >
            <span class="sm-option-label">
              {{ o.label }}
              <span v-if="o.hint" class="sm-hint">{{ o.hint }}</span>
            </span>
            <Icon v-if="o.value === modelValue" name="check" :size="14" />
          </button>
        </div>
      </transition>
    </Teleport>
  </div>
</template>

<style scoped>
.sm { position: relative; width: 100%; }
.sm.disabled { opacity: 0.5; }

.sm-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 11px 14px;
  font-size: 15px;
  font-family: inherit;
  text-align: left;
  color: var(--text);
  background: var(--glass-strong);
  border: 1px solid var(--input-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.sm-trigger:hover:not(:disabled) { border-color: var(--blue); }
.sm-trigger:focus { outline: none; border-color: var(--blue); box-shadow: 0 0 0 3.5px rgba(0, 113, 227, 0.18); }
.sm-trigger:disabled { cursor: not-allowed; }
.sm-value { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sm-value.empty { color: var(--gray); }
.sm-chevron { color: var(--gray); flex-shrink: 0; transition: transform 0.24s cubic-bezier(0.4, 0, 0.2, 1); }
.sm-chevron.open { transform: rotate(180deg); }

.sm-pop-enter-active { transition: opacity 0.18s ease, transform 0.24s cubic-bezier(0.34, 1.4, 0.64, 1); }
.sm-pop-leave-active { transition: opacity 0.14s ease, transform 0.14s ease; }
.sm-pop-enter-from { opacity: 0; transform: translateY(-6px) scale(0.98); }
.sm-pop-leave-to { opacity: 0; transform: translateY(-4px); }
</style>

<style>
/* 面板 Teleport 到 body，使用全局样式 */
.sm-panel {
  position: fixed;
  z-index: 1000;
  max-height: 260px;
  overflow-y: auto;
  padding: 6px;
  /* 液态玻璃菜单：渐变描边 + 上缘 rim，折射由引擎注入*/
  border: 1px solid transparent;
  background:
    linear-gradient(var(--modal-bg), var(--modal-bg)) padding-box,
    linear-gradient(165deg, var(--lg-rim), var(--lg-rim-2) 40%, var(--lg-rim-2) 62%, var(--lg-rim)) border-box;
  backdrop-filter: blur(28px) saturate(180%);
  -webkit-backdrop-filter: blur(28px) saturate(180%);
  border-radius: 14px;
  box-shadow: inset 0 1px 0 var(--lg-rim-2), 0 18px 50px rgba(0, 0, 0, 0.2);
}
.sm-option {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-family: inherit;
  font-size: 13.5px;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: background 0.12s ease;
}
.sm-option:hover { background: var(--surface); }
.sm-option.active { background: rgba(0, 113, 227, 0.12); color: var(--blue); font-weight: 500; }
.sm-option-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sm-hint { font-size: 11.5px; color: var(--gray); margin-left: 6px; }
.sm-empty { padding: 12px; text-align: center; font-size: 12.5px; color: var(--gray); }

.sm-pop-enter-active { transition: opacity 0.18s ease, transform 0.24s cubic-bezier(0.34, 1.4, 0.64, 1); }
.sm-pop-leave-active { transition: opacity 0.14s ease, transform 0.14s ease; }
.sm-pop-enter-from { opacity: 0; transform: translateY(-6px) scale(0.98); }
.sm-pop-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
