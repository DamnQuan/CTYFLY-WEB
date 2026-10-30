<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { modalState, cancelModal, confirmModalValue, copyAlertValue } from '../modal.js';
import { showToast } from '../utils.js';

const inputRef = ref(null);

watch(
  () => modalState.visible,
  async (v) => {
    if (v && modalState.inputMode) {
      await nextTick();
      inputRef.value?.focus();
    }
  },
);

function onKeydown(e) {
  if (!modalState.visible) return;
  if (e.key === 'Escape') {
    e.preventDefault();
    cancelModal();
  } else if (e.key === 'Enter' && !e.shiftKey) {
    // prompt 模式下仅文本框内 Enter 提交，避免误触
    if (!modalState.inputMode || e.target.tagName === 'TEXTAREA') {
      e.preventDefault();
      confirmModalValue();
    }
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown));
onUnmounted(() => window.removeEventListener('keydown', onKeydown));
</script>

<template>
  <Teleport to="body">
    <!-- 不用 <transition>：入场动画由 CSS 关键帧完成，关闭时元素立即移除，
         避免离场动画在后台标签页卡住、透明蒙层滞留吞掉整页点击 -->
    <div v-if="modalState.visible" class="modal-mask" @mousedown.self="cancelModal">
        <div class="modal-panel" role="dialog" aria-modal="true">
          <div class="modal-title">{{ modalState.title }}</div>
          <div v-if="modalState.message" class="modal-message">{{ modalState.message }}</div>

          <textarea
            v-if="modalState.inputMode"
            ref="inputRef"
            v-model="modalState.inputValue"
            class="textarea modal-input"
            rows="3"
            :placeholder="modalState.inputPlaceholder"
          ></textarea>

          <div v-if="modalState.copyable" class="modal-alert-row">
            <div class="code-block modal-alert-value">{{ modalState.alertValue }}</div>
            <button
              class="btn btn-ghost btn-sm"
              @click="copyAlertValue().then((ok) => showToast(ok ? '已复制到剪贴板' : '复制失败，请手动选择复制'))"
            >复制</button>
          </div>

          <div class="modal-actions">
            <button v-if="!modalState.hideCancel" class="btn btn-ghost" @click="cancelModal">
              {{ modalState.cancelText }}
            </button>
            <button
              class="btn"
              :class="modalState.danger ? 'btn-danger' : 'btn-primary'"
              @click="confirmModalValue"
            >{{ modalState.confirmText }}</button>
          </div>
        </div>
      </div>
  </Teleport>
</template>
