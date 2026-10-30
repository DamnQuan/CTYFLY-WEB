<script setup>
/**
 * 航司 Logo 上传：从本地选图 → 上传到 /api/uploads/airline-logo → 回填同源地址
 * 客户端只做格式/体积的即时提示，真正把关在服务端，magic bytes + 体积上限
 */
import { computed, ref } from 'vue';
import { getToken } from '../api.js';
import { showToast } from '../utils.js';
import Icon from './Icon.vue';

const props = defineProps({
  modelValue: { type: String, default: '' },
  fallback: { type: String, default: '' },   // 无图时显示的占位文字，如航司代码
  disabled: { type: Boolean, default: false },
});
const emit = defineEmits(['update:modelValue']);

const MAX_BYTES = 2 * 1024 * 1024;
const ALLOWED = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

const inputEl = ref(null);
const uploading = ref(false);

const previewStyle = computed(() =>
  props.modelValue ? { backgroundImage: `url(${props.modelValue})` } : {},
);

function pick() {
  if (props.disabled || uploading.value) return;
  inputEl.value?.click();
}

function clear() {
  emit('update:modelValue', '');
  if (inputEl.value) inputEl.value.value = '';
}

async function onFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (!ALLOWED.includes(file.type)) {
    showToast('仅支持 PNG / JPG / WebP / GIF 图片');
    event.target.value = '';
    return;
  }
  if (file.size > MAX_BYTES) {
    showToast('图片不能超过 2 MB');
    event.target.value = '';
    return;
  }

  uploading.value = true;
  try {
    const fd = new FormData();
    fd.append('file', file);
    const resp = await fetch('/api/uploads/airline-logo', {
      method: 'POST',
      headers: { Authorization: `Bearer ${getToken()}` },
      body: fd,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || '上传失败，请重试');
    emit('update:modelValue', data.url);
    showToast('Logo 上传成功');
  } catch (err) {
    showToast(err.message || '上传失败，请重试');
  } finally {
    uploading.value = false;
    event.target.value = '';
  }
}
</script>

<template>
  <div class="lu">
    <div class="lu-preview" :style="previewStyle">
      <template v-if="!modelValue">
        <Icon name="plane" :size="20" />
        <span v-if="fallback" class="lu-fallback">{{ fallback }}</span>
      </template>
    </div>

    <div class="lu-body">
      <div class="lu-actions">
        <button type="button" class="btn btn-ghost btn-sm" :disabled="disabled || uploading" @click="pick">
          <Icon name="plus" :size="14" />
          {{ uploading ? '上传中…' : (modelValue ? '更换图片' : '从本地上传') }}
        </button>
        <button v-if="modelValue" type="button" class="btn btn-danger btn-sm" :disabled="uploading" @click="clear">
          移除
        </button>
      </div>
      <div class="lu-hint">支持 PNG / JPG / WebP / GIF，不超过 2 MB，建议正方形</div>
    </div>

    <input
      ref="inputEl"
      class="lu-input"
      type="file"
      accept="image/png,image/jpeg,image/webp,image/gif"
      @change="onFile"
    />
  </div>
</template>

<style scoped>
.lu { display: flex; align-items: center; gap: 16px; }
.lu-preview {
  width: 68px;
  height: 68px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border-radius: 16px;
  background-color: var(--glass-strong);
  background-image: none;
  background-size: cover;
  background-position: center;
  border: 1px solid var(--glass-border);
  color: var(--gray);
  font-weight: 700;
  font-size: 12px;
  letter-spacing: 0.5px;
  overflow: hidden;
}
.lu-fallback { color: var(--blue); }
.lu-body { flex: 1; min-width: 0; }
.lu-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.lu-hint { font-size: 12.5px; color: var(--text-2); margin-top: 8px; }
.lu-input { display: none; }
</style>
