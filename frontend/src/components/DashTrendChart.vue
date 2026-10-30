<script setup>
/**
 * 仪表盘主模块的「核心图表」：零依赖手写 SVG 柱图，与 AirportMapView 的 Canvas 自绘一致，不引第三方库。
 *
 * 两个刻意的实现选择：
 *  1. 只有图形是 SVG 且 preserveAspectRatio="none"，随容器宽高自由伸缩、填满主模块，
 *     坐标文字全部用 HTML 覆盖层渲染 —— 避免文字跟着被横向拉伸变形。
 *  2. 单序列 + 悬浮 title，不引入 tooltip 组件：信息用「柱 + 轴 + 合计」表达，符合站内扁平风格。
 */
import { computed } from 'vue';

const props = defineProps({
  series: { type: Array, default: () => [] },     // [{ day, requests, users, reports, hours }]
  metric: { type: String, default: 'requests' },
});

const METRICS = {
  requests: { label: '请求量', unit: '', pick: (d) => d.requests },
  reports: { label: '飞行报告', unit: ' 份', pick: (d) => d.reports },
  users: { label: '新增用户', unit: ' 人', pick: (d) => d.users },
};
const current = computed(() => METRICS[props.metric] || METRICS.requests);

const VB_W = 700;
const VB_H = 200;
const PAD_B = 6;

const values = computed(() => props.series.map((d) => current.value.pick(d) || 0));
const max = computed(() => Math.max(1, ...values.value));
const total = computed(() => values.value.reduce((a, b) => a + b, 0));

const bars = computed(() => {
  const n = values.value.length || 1;
  const step = VB_W / n;
  const bw = Math.max(6, step * 0.58);
  return values.value.map((v, i) => {
    const h = v > 0 ? Math.max(2, (v / max.value) * (VB_H - PAD_B)) : 0;
    return { key: i, x: i * step + (step - bw) / 2, w: bw, y: VB_H - PAD_B - h, h };
  });
});

/* y 轴刻度用 HTML 覆盖层定位，百分比，避开 SVG 拉伸导致文字变形*/
const yTicks = computed(() => {
  const m = max.value;
  return [1, 0.5, 0].map((f) => ({
    bottomPct: ((f * (VB_H - PAD_B)) / VB_H) * 100,
    label: m * f >= 1000 ? `${Math.round((m * f) / 1000)}k` : String(Math.round(m * f)),
  }));
});

const xLabels = computed(() =>
  props.series.map((d, i) => ({ key: i, text: (d.day || '').slice(5), show: props.series.length <= 8 || i % 2 === 0 }))
);
</script>

<template>
  <div class="chart">
    <div class="chart-kpis">
      <div class="chart-kpi">
        <div class="chart-kpi-num">{{ total.toLocaleString() }}<span class="chart-kpi-unit">{{ current.unit }}</span></div>
        <div class="chart-kpi-label">近 14 天{{ current.label }}</div>
      </div>
    </div>

    <div class="chart-plot">
      <div class="chart-yaxis">
        <span v-for="t in yTicks" :key="t.label" :style="{ bottom: `calc(${t.bottomPct}% - 7px)` }">{{ t.label }}</span>
      </div>
      <div class="chart-canvas">
        <svg :viewBox="`0 0 ${VB_W} ${VB_H}`" preserveAspectRatio="none" role="img"
             :aria-label="`近 14 天每日${current.label}柱状图`">
          <line v-for="t in yTicks" :key="`g${t.label}`" class="chart-grid"
                x1="0" :x2="VB_W" :y1="VB_H - PAD_B - (t.bottomPct / 100) * VB_H"
                :y2="VB_H - PAD_B - (t.bottomPct / 100) * VB_H" />
          <rect v-for="(b, i) in bars" :key="b.key" class="chart-bar" :x="b.x" :y="b.y" :width="b.w" :height="b.h">
            <title>{{ series[i]?.day }}：{{ values[i] }}{{ current.unit }}{{ current.label }}</title>
          </rect>
          <line class="chart-base" x1="0" :x2="VB_W" :y1="VB_H - PAD_B" :y2="VB_H - PAD_B" />
        </svg>
        <div v-if="!total" class="chart-empty">近 14 天暂无数据</div>
      </div>
    </div>

    <div class="chart-xaxis">
      <span v-for="l in xLabels" :key="l.key" :class="{ 'is-hidden': !l.show }">{{ l.text }}</span>
    </div>
  </div>
</template>

<style scoped>
.chart { display: flex; flex-direction: column; height: 100%; min-height: 0; }

.chart-kpis { display: flex; gap: 26px; flex-wrap: wrap; margin-bottom: 6px; }
.chart-kpi-num { font-size: 30px; font-weight: 700; letter-spacing: -0.6px; font-variant-numeric: tabular-nums; }
.chart-kpi-unit { font-size: 14px; font-weight: 600; color: var(--text-2); margin-left: 2px; }
.chart-kpi-label { font-size: 12.5px; color: var(--text-2); margin-top: 2px; }

.chart-plot { display: flex; gap: 8px; flex: 1; min-height: 150px; }
.chart-yaxis {
  position: relative;
  width: 34px;
  flex-shrink: 0;
  font-size: 11px;
  color: var(--gray);
  font-variant-numeric: tabular-nums;
}
.chart-yaxis span { position: absolute; right: 0; line-height: 1; }
.chart-canvas { position: relative; flex: 1; min-width: 0; }
.chart-canvas svg { width: 100%; height: 100%; display: block; }

.chart-grid { stroke: var(--border); stroke-width: 1; vector-effect: non-scaling-stroke; }
.chart-base { stroke: var(--border); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.chart-bar { fill: var(--blue); opacity: 0.85; }
.chart-bar:hover { opacity: 1; }

.chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--gray);
}

.chart-xaxis {
  display: flex;
  margin-left: 42px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--gray);
  font-variant-numeric: tabular-nums;
}
.chart-xaxis span { flex: 1; text-align: center; }
.chart-xaxis span.is-hidden { visibility: hidden; }
</style>
