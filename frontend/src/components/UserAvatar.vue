<script setup>
/**
 * 用户头像：QQ 头像等外链加载失败时自动回退到本地占位图，
 * 并启用懒加载 / 异步解码，避免外链挂起拖慢页面。
 */
import { ref, watch } from 'vue';
import { avatarUrl } from '../utils.js';

const props = defineProps({
  user: { type: Object, default: null },
  size: { type: Number, default: 34 },
  square: { type: Boolean, default: false },
  ring: { type: Boolean, default: false },
});

const src = ref(avatarUrl(props.user));

watch(
  () => props.user,
  () => { src.value = avatarUrl(props.user); },
  { deep: true },
);

function onError() {
  src.value = avatarUrl({ username: props.user?.username });
}
</script>

<template>
  <img
    :src="src"
    class="ua"
    :class="{ ring }"
    alt=""
    :style="{ width: `${size}px`, height: `${size}px`, borderRadius: square ? '14px' : '50%' }"
    loading="lazy"
    decoding="async"
    referrerpolicy="no-referrer"
    @error="onError"
  />
</template>

<style scoped>
.ua {
  object-fit: cover;
  flex-shrink: 0;
  background: var(--surface-strong);
}
.ua.ring {
  border: 2px solid rgba(255, 255, 255, 0.8);
  box-shadow: var(--shadow);
}
</style>
