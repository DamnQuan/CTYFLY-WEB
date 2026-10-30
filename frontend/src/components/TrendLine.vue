<script setup>
/**
 * 趋势折线图，轻量 SVG，无依赖：折线 + 面积渐变 + 数据点/数值 + 日期轴。
 * points: [{ day: '2026-09-20', count: 3 }, ...]，1 个点也画
 */
import { computed } from 'vue';

const props = defineProps({
  points: { type: Array, default: () => [] },
  height: { type: Number, default: 200 },
});

const W = 700;
const PAD_L = 34, PAD_R = 34, PAD_T = 30, PAD_B = 34;
const H = computed(() => props.height);

const pts = computed(() => {
  const n = props.points.length;
  if (!n) return [];
  const max = Math.max(1, ...props.points.map((p) => p.count));
  const innerW = W - PAD_L - PAD_R;
  const innerH = H.value - PAD_T - PAD_B;
  return props.points.map((p, i) => ({
    ...p,
    x: n === 1 ? W / 2 : PAD_L + (i * innerW) / (n - 1),
    y: Math.round(PAD_T + innerH * (1 - p.count / max)),
  }));
});

const linePath = computed(() =>
  pts.value.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y}`).join(' '));

const areaPath = computed(() => {
  const a = pts.value;
  if (a.length < 2) return '';
  const base = H.value - PAD_B;
  return `${linePath.value} L ${a[a.length - 1].x} ${base} L ${a[0].x} ${base} Z`;
});

// 同页多实例时渐变 id 不能撞
const uid = `trend-fill-${Math.random().toString(36).slice(2, 8)}`;
</script>

<template>
  <svg
    :viewBox="`0 0 ${W} ${H}`"
    style="width: 100%; height: auto; display: block"
    role="img"
    aria-label="趋势折线图"
  >
    <defs>
      <linearGradient :id="uid" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#0a84ff" stop-opacity="0.26" />
        <stop offset="100%" stop-color="#0a84ff" stop-opacity="0.02" />
      </linearGradient>
    </defs>

    <!-- 基线 -->
    <line
      :x1="PAD_L" :y1="H - PAD_B" :x2="W - PAD_R" :y2="H - PAD_B"
      stroke="rgba(128,128,140,0.25)" stroke-width="1"
    />

    <path v-if="pts.length > 1" :d="areaPath" :fill="`url(#${uid})`" />
    <path
      v-if="pts.length > 1" :d="linePath" fill="none"
      stroke="#0a84ff" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"
    />

    <g v-for="p in pts" :key="p.day">
      <circle :cx="p.x" :cy="p.y" r="3.5" fill="#fff" stroke="#0a84ff" stroke-width="2" />
      <text :x="p.x" :y="p.y - 10" text-anchor="middle" style="font-size: 12px; fill: var(--text-2)">{{ p.count }}</text>
      <text :x="p.x" :y="H - 10" text-anchor="middle" style="font-size: 11px; fill: var(--gray)">{{ String(p.day).slice(5) }}</text>
    </g>
  </svg>
</template>
