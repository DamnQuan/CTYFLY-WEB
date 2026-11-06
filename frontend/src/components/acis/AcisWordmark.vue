<script setup>
/**
 * ACIS 高定动态文字 Logo：打字入场、液态波浪、光标呼吸。
 * 每个字母独立 <span>，动画全部由 CSS 的 transform / opacity 驱动。
 */
const letters = ['A', 'C', 'I', 'S'];
</script>

<template>
  <div class="acis-wordmark" aria-label="ACIS">
    <span
      v-for="(letter, index) in letters"
      :key="letter"
      class="acis-letter"
      :style="{ '--i': index }"
    >{{ letter }}</span>
    <span class="acis-cursor" aria-hidden="true"></span>
  </div>
</template>

<style scoped>
.acis-wordmark {
  display: inline-flex;
  align-items: baseline;
  font-weight: 800;
  font-size: clamp(52px, 9vw, 96px);
  letter-spacing: 2px;
  line-height: 1;
  user-select: none;
}
.acis-letter {
  display: inline-block;
  opacity: 0;
  transform: translateY(20px);
  background: linear-gradient(135deg, #ffffff 0%, #d5f1ff 8%, #8fd6ff 20%, #43adf7 42%, #117fd8 68%, #074f9f 100%);
  background-size: 160% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  text-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
  filter: drop-shadow(0 4px 12px rgba(59, 130, 246, 0.38)) drop-shadow(0 1px 1px rgba(255, 255, 255, 0.28));
  animation:
    acis-in 0.62s cubic-bezier(0.2, 0.9, 0.3, 1.2) both,
    acis-wave 2.6s ease-in-out infinite,
    acis-shimmer 5s ease-in-out infinite;
  animation-delay:
    calc(var(--i) * 120ms),
    calc(900ms + var(--i) * 100ms),
    calc(1200ms + var(--i) * 100ms);
}
.acis-cursor {
  display: inline-block;
  width: 3px;
  height: 0.82em;
  margin-left: 8px;
  border-radius: 2px;
  background: #0a84ff;
  box-shadow: 0 0 10px rgba(10, 132, 255, 0.55);
  animation: acis-cursor 1.1s steps(1, end) infinite;
  animation-delay: 900ms;
}
@keyframes acis-in {
  from { opacity: 0; transform: translateY(20px) scale(0.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes acis-wave {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}
@keyframes acis-shimmer {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}
@keyframes acis-cursor {
  0%, 48% { opacity: 1; }
  49%, 100% { opacity: 0.15; }
}
@media (prefers-reduced-motion: reduce) {
  .acis-letter, .acis-cursor { animation: none; opacity: 1; transform: none; }
}
</style>
