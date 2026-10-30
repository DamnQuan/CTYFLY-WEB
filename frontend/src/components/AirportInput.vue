<script setup>
/**
 * 机场 ICAO 联想输入框，替代普通 ICAO 文本输入
 * - 输入 1 个字符即触发联想，查询 AIRAC 导航数据库
 * - multiple：支持逗号分隔多个机场，如 METAR 查询 ZSPD,ZBAA，联想最后一个词
 * - 单值模式选中后输出 4 位 ICAO；多值模式选中后自动补 ", " 继续输入
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { api } from '../api.js';

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '机场 ICAO，如 ZBAA' },
  multiple: { type: Boolean, default: false },
});
const emit = defineEmits(['update:modelValue', 'select']);

const rootEl = ref(null);
const inputEl = ref(null);
const panelEl = ref(null);
const open = ref(false);
const panelStyle = ref({});
const suggestions = ref([]);
const loading = ref(false);

let timer = null;

const text = ref(props.modelValue || '');

/* 同步外部值，父组件重置表单等场景*/
watch(() => props.modelValue, (v) => {
  if (v !== text.value) text.value = v || '';
});

const token = computed(() => {
  if (!props.multiple) return text.value.trim();
  const parts = text.value.split(',');
  return (parts[parts.length - 1] || '').trim();
});

function scheduleSearch() {
  clearTimeout(timer);
  const t = token.value;
  if (t.length < 1) {
    suggestions.value = [];
    open.value = false;
    return;
  }
  timer = setTimeout(async () => {
    if (token.value !== t) return; // 已过期
    loading.value = true;
    try {
      const data = await api.get(`/api/nav/airports?q=${encodeURIComponent(t)}`);
      if (token.value !== t) return;
      suggestions.value = (data.airports || []).slice(0, 8);
      if (suggestions.value.length) {
        open.value = true;
        nextTick(updatePosition);
      } else {
        open.value = false;
      }
    } catch {
      suggestions.value = [];
    } finally {
      loading.value = false;
    }
  }, 180);
}

function onInput(e) {
  let v = e.target.value;
  if (props.multiple) {
    const parts = v.split(',');
    const last = (parts.pop() ?? '').toUpperCase();
    parts.push(last);
    v = parts.join(',');
  } else {
    v = v.toUpperCase();
  }
  text.value = v;
  emit('update:modelValue', v);
  scheduleSearch();
}

function pick(ap) {
  if (props.multiple) {
    const parts = text.value.split(',');
    parts.pop();
    parts.push(ap.icao);
    const next = parts.join(',') + ', ';
    text.value = next;
    emit('update:modelValue', next);
    suggestions.value = [];
    nextTick(() => inputEl.value?.focus());
  } else {
    text.value = ap.icao;
    emit('update:modelValue', ap.icao);
    emit('select', ap);
    open.value = false;
  }
}

/* ---------- 定位，Teleport 到 body，避让层叠上下文 ----------*/
function updatePosition() {
  const rect = inputEl.value?.getBoundingClientRect();
  if (!rect) return;
  const panelH = Math.min(suggestions.value.length * 44 + 12, 320);
  let left = Math.min(Math.max(8, rect.left), window.innerWidth - rect.width - 8);
  let top;
  if (window.innerHeight - rect.bottom < panelH && rect.top > panelH) {
    top = Math.max(8, rect.top - panelH - 6);
  } else {
    top = rect.bottom + 6;
  }
  panelStyle.value = { left: `${left}px`, top: `${top}px`, width: `${Math.max(rect.width, 300)}px` };
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
  clearTimeout(timer);
});

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
  <div ref="rootEl" class="ai">
    <input
      ref="inputEl"
      class="input ai-input"
      :value="text"
      :placeholder="placeholder"
      :maxlength="multiple ? undefined : 4"
      autocomplete="off"
      spellcheck="false"
      @input="onInput"
      @focus="() => { if (suggestions.length) { open = true; updatePosition(); } }"
    />

    <Teleport to="body">
      <transition name="sm-pop">
        <div v-if="open && suggestions.length" ref="panelEl" class="ai-panel" :style="panelStyle">
          <button
            v-for="ap in suggestions" :key="ap.icao" type="button"
            class="ai-item" @mousedown.prevent="pick(ap)"
          >
            <span class="ai-icao">{{ ap.icao }}</span>
            <span class="ai-name">{{ ap.name }}</span>
          </button>
          <div v-if="loading" class="ai-loading">搜索中…</div>
        </div>
      </transition>
    </Teleport>
  </div>
</template>

<style scoped>
.ai { position: relative; width: 100%; }
.ai-input { text-transform: uppercase; }
</style>

<style>
.ai-panel {
  position: fixed;
  z-index: 1000;
  padding: 6px;
  background: var(--modal-bg);
  backdrop-filter: blur(28px) saturate(180%);
  -webkit-backdrop-filter: blur(28px) saturate(180%);
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.2);
  max-height: 320px;
  overflow-y: auto;
}
.ai-item {
  width: 100%;
  display: flex;
  align-items: baseline;
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
.ai-item:hover { background: var(--surface); }
.ai-icao { font-weight: 700; font-variant-numeric: tabular-nums; flex-shrink: 0; }
.ai-name { color: var(--text-2); font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ai-loading { padding: 8px 12px; font-size: 12px; color: var(--gray); text-align: center; }

.sm-pop-enter-active { transition: opacity 0.18s ease, transform 0.24s cubic-bezier(0.34, 1.4, 0.64, 1); }
.sm-pop-leave-active { transition: opacity 0.14s ease, transform 0.14s ease; }
.sm-pop-enter-from { opacity: 0; transform: translateY(-6px) scale(0.98); }
.sm-pop-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
