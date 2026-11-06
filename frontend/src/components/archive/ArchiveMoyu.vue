<script setup>
/**
 * 飞圈事件检索的摸鱼彩蛋：只有在检索无结果时出现。
 * 纯前端小游戏，分数只存本机 localStorage，不写服务端、不影响业务数据。
 */
import { onBeforeUnmount, ref, watch } from 'vue';

const props = defineProps({
  prompt: { type: Boolean, default: false },
});

const visible = ref(false);
const open = ref(false);
const running = ref(false);
const score = ref(0);
const timeLeft = ref(15);
const fishPos = ref({ x: 48, y: 44 });
const best = ref(0);
let tickTimer = null;
let countdownTimer = null;

try {
  best.value = Number(localStorage.getItem('ctyfly_moyu_best') || 0) || 0;
} catch { /* 存储不可用时按 0 处理 */ }

watch(() => props.prompt, (value) => {
  visible.value = value;
  if (!value) {
    open.value = false;
    stop();
  }
});

function randomPosition() {
  return {
    x: 8 + Math.random() * 80,
    y: 10 + Math.random() * 70,
  };
}

function moveFish() {
  fishPos.value = randomPosition();
}

function stop() {
  running.value = false;
  if (tickTimer) clearInterval(tickTimer);
  if (countdownTimer) clearInterval(countdownTimer);
  tickTimer = null;
  countdownTimer = null;
}

function finish() {
  stop();
  if (score.value > best.value) {
    best.value = score.value;
    try {
      localStorage.setItem('ctyfly_moyu_best', String(best.value));
    } catch { /* 忽略存储异常 */ }
  }
}

function start() {
  stop();
  score.value = 0;
  timeLeft.value = 15;
  running.value = true;
  fishPos.value = randomPosition();
  tickTimer = setInterval(moveFish, 750);
  countdownTimer = setInterval(() => {
    timeLeft.value -= 1;
    if (timeLeft.value <= 0) finish();
  }, 1000);
}

function openGame() {
  open.value = true;
  start();
}

function closeGame() {
  open.value = false;
  stop();
}

function catchFish() {
  if (!running.value) return;
  score.value += 1;
  moveFish();
}

onBeforeUnmount(stop);
</script>

<template>
  <button v-if="visible && !open" class="moyu-pet" type="button" title="摸鱼彩蛋" @click="openGame">
    <span class="moyu-pet-fish">🐟</span>
    <span class="moyu-pet-text">没搜到，摸会儿鱼</span>
  </button>

  <div v-if="open" class="moyu-panel glass card">
    <div class="moyu-head">
      <div>
        <div class="moyu-title">摸鱼时间</div>
        <div class="moyu-sub">点中游动的小鱼，15 秒内看看能摸几条</div>
      </div>
      <button class="moyu-close" type="button" aria-label="关闭摸鱼彩蛋" @click="closeGame">×</button>
    </div>
    <div class="moyu-pond">
      <button
        v-if="running"
        class="moyu-fish"
        type="button"
        :style="{ left: `${fishPos.x}%`, top: `${fishPos.y}%` }"
        aria-label="抓住小鱼"
        @click="catchFish"
      >🐟</button>
      <div v-if="running" class="moyu-status">
        <span>已摸 {{ score }} 条</span>
        <span>还剩 {{ timeLeft }} 秒</span>
      </div>
      <div v-else class="moyu-result">
        <div class="moyu-result-score">{{ score }} 条</div>
        <div class="moyu-result-text">本次摸鱼成绩，历史最高 {{ best }} 条</div>
        <button class="btn btn-primary btn-sm" type="button" @click="start">再摸一次</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.moyu-pet {
  position: fixed;
  right: 26px;
  bottom: 92px;
  z-index: 60;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px 9px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-solid);
  color: var(--text-2);
  font-size: 12.5px;
  cursor: pointer;
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.12);
  transition: transform 0.18s ease, border-color 0.18s ease;
}
.moyu-pet:hover { transform: translateY(-3px); border-color: rgba(10, 132, 255, 0.4); }
.moyu-pet-fish { font-size: 20px; line-height: 1; animation: moyu-bob 2.2s ease-in-out infinite; }
.moyu-pet-text { white-space: nowrap; }
@keyframes moyu-bob {
  0%, 100% { transform: translateY(0) rotate(-4deg); }
  50% { transform: translateY(-4px) rotate(6deg); }
}
.moyu-panel {
  position: fixed;
  right: 26px;
  bottom: 92px;
  z-index: 61;
  width: min(360px, calc(100vw - 32px));
  padding: 14px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.18);
}
.moyu-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.moyu-title { font-size: 15px; font-weight: 600; }
.moyu-sub { margin-top: 3px; color: var(--gray); font-size: 12px; line-height: 1.5; }
.moyu-close {
  border: none;
  background: transparent;
  color: var(--gray);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}
.moyu-pond {
  position: relative;
  height: 190px;
  margin-top: 12px;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(10, 132, 255, 0.18);
  background:
    radial-gradient(circle at 20% 20%, rgba(10, 132, 255, 0.16), transparent 42%),
    radial-gradient(circle at 80% 78%, rgba(52, 199, 89, 0.12), transparent 46%),
    var(--surface);
  overflow: hidden;
}
.moyu-fish {
  position: absolute;
  width: 42px;
  height: 42px;
  margin-left: -21px;
  margin-top: -21px;
  border: none;
  background: transparent;
  font-size: 30px;
  line-height: 42px;
  cursor: pointer;
  transition: left 0.5s ease, top 0.5s ease;
}
.moyu-fish:active { transform: scale(0.86); }
.moyu-status {
  position: absolute;
  inset: auto 10px 8px 10px;
  display: flex;
  justify-content: space-between;
  color: var(--text-2);
  font-size: 12px;
  pointer-events: none;
}
.moyu-result {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  text-align: center;
}
.moyu-result-score { font-size: 30px; font-weight: 700; color: var(--blue); }
.moyu-result-text { color: var(--gray); font-size: 12px; margin-bottom: 6px; }
@media (max-width: 620px) {
  .moyu-pet, .moyu-panel { right: 14px; bottom: 78px; }
  .moyu-pet-text { display: none; }
}
</style>
