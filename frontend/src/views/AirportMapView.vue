<script setup>
/**
 * 机场地面图查询：Airport GIS 矢量数据交互查看器。
 * 数据源：/api/nav/ground-map/*，X-Plane 机场场景 GeoJSON，2090 机场全球覆盖。
 * Canvas 自绘，零依赖：拖拽平移 / 滚轮缩放 / 图层开关 / 跑道与机位标注。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { api } from '../api.js';
import { showToast } from '../utils.js';
import CheckBox from '../components/CheckBox.vue';

const airports = ref([]);
const q = ref('');
const selected = ref('');
const loading = ref(false);
const mapData = ref(null);
const layerNames = ref([]);
const err = ref('');

const filtered = computed(() => {
  const k = q.value.trim().toUpperCase();
  if (!k) return airports.value;
  return airports.value.filter((a) => a.includes(k));
});

/* 图层分组，渲染顺序 = 数组顺序*/
const GROUPS = [
  { label: '跑道', layers: ['runwayelement', 'runwaymarking', 'runwaycenterlinepoint', 'runwaythreshold', 'runwaydisplacedarea', 'runwayshoulder', 'runwayexitline', 'blastpad', 'stopway', 'touchdownliftoffarea', 'finalapproachandtakeoffarea', 'runwayintersection'] },
  { label: '滑行道', layers: ['taxiwayelement', 'taxiwayshoulder', 'asrnedge', 'asrnnode'] },
  { label: '机坪与停机位', layers: ['apronelement', 'parkingstandarea', 'parkingstandlocation'] },
  { label: '引导与标志', layers: ['taxiwayguidanceline', 'taxiwayholdingposition', 'aerodromesign', 'positionmarking', 'hotspot'] },
  { label: '灯光', layers: ['aerodromesurfacelighting'] },
  { label: '服务与其它', layers: ['serviceroad', 'constructionarea', 'deicingarea', 'deicinggroup', 'frequencyarea', 'atcblindspot', 'arrestinggearlocation', 'arrestingsystemlocation', 'bridgeside', 'verticallinestructure', 'verticalpointstructure', 'verticalpolygonalstructure', 'water', 'surveycontrolpoint', 'landandholdshortoperationlocation', 'helipadthreshold', 'aerodromereferencepoint'] },
];
const groupOn = ref(Object.fromEntries(GROUPS.map((g) => [g.label, true])));
const layersOn = computed(() => {
  const set = new Set();
  for (const g of GROUPS) if (groupOn.value[g.label]) g.layers.forEach((l) => set.add(l));
  return set;
});

/* 图层样式 */
const STYLE = {
  runwayelement: { fill: '#3f4a5c', stroke: '#dbe4ee', width: 1.2 },
  runwaymarking: { stroke: 'rgba(255,255,255,0.75)', width: 1 },
  runwaycenterlinepoint: { stroke: 'rgba(255,255,255,0.5)', width: 1 },
  runwaythreshold: { stroke: 'rgba(255,255,255,0.6)', width: 1 },
  runwayexitline: { stroke: 'rgba(255,255,255,0.4)', width: 1 },
  taxiwayelement: { fill: 'rgba(71, 85, 105, 0.9)', stroke: 'rgba(148,163,184,0.35)', width: 0.8 },
  apronelement: { fill: 'rgba(96, 116, 146, 0.5)', stroke: 'rgba(148,163,184,0.3)', width: 0.8 },
  parkingstandarea: { stroke: 'rgba(96,165,250,0.55)', width: 1 },
  parkingstandlocation: { fill: '#93c5fd' },
  taxiwayguidanceline: { stroke: '#facc15', width: 1.2 },
  taxiwayholdingposition: { stroke: 'rgba(239,68,68,0.8)', width: 1.2 },
  aerodromesign: { fill: '#f59e0b' },
  aerodromesurfacelighting: { fill: '#bfdbfe' },
  serviceroad: { stroke: 'rgba(120,130,140,0.7)', width: 1 },
};

let canvas = null;
let ctx = null;
let view = { x: 0, y: 0, scale: 1 };
let dragFrom = null;

function select(icao) {
  selected.value = icao;
  load(icao);
}

async function load(icao) {
  loading.value = true;
  err.value = '';
  mapData.value = null;
  try {
    const data = await api.get(`/api/nav/ground-map/${icao}`);
    mapData.value = data;
    layerNames.value = Object.keys(data.layers || {});
    for (const g of GROUPS) if (groupOn.value[g.label] === undefined) groupOn.value[g.label] = true;
    /* canvas 在 v-if 块内，等 DOM 渲染出来再初始化，首次选择机场时元素才存在*/
    await nextTick();
    setupCanvas();
    fit();
    draw();
  } catch (e) {
    err.value = e.message;
    showToast(e.message);
  }
  loading.value = false;
}

/* ---------- 投影与渲染 ---------- */
function collectCoords(geom, cb) {
  const t = geom.type;
  if (t === 'Point') cb(geom.coordinates);
  else if (t === 'MultiPoint' || t === 'LineString') geom.coordinates.forEach(cb);
  else if (t === 'MultiLineString' || t === 'Polygon') geom.coordinates.forEach((part) => part.forEach(cb));
  else if (t === 'MultiPolygon') geom.coordinates.forEach((poly) => poly.forEach((part) => part.forEach(cb)));
}

function bounds() {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, any = false;
  const scan = (fc) => {
    for (const f of fc.features || []) {
      if (!(f.geometry && f.geometry.coordinates)) continue;
      collectCoords(f.geometry, ([lon, lat]) => {
        any = true;
        if (lon < minX) minX = lon;
        if (lon > maxX) maxX = lon;
        if (lat < minY) minY = lat;
        if (lat > maxY) maxY = lat;
      });
    }
  };
  for (const name of layerNames.value) if (layersOn.value.has(name)) scan(mapData.value.layers[name]);
  if (!any) return null;
  return { minX, minY, maxX, maxY };
}

function fit() {
  const b = bounds();
  if (!b || !canvas) return;
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  const spanX = Math.max(1e-5, b.maxX - b.minX);
  const spanY = Math.max(1e-5, b.maxY - b.minY);
  const pad = 40;
  view.scale = Math.min((cw - pad * 2) / spanX, (ch - pad * 2) / spanY);
  /* 纬度轴翻转：view.y 定位在 maxY，图顶，py 随纬度增大而向上移动*/
  view.x = pad - b.minX * view.scale + (cw - pad * 2 - spanX * view.scale) / 2;
  view.y = pad + b.maxY * view.scale + (ch - pad * 2 - spanY * view.scale) / 2;
}

function draw() {
  if (!canvas || !ctx || !mapData.value) return;
  const dpr = window.devicePixelRatio || 1;
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cw, ch);
  ctx.fillStyle = 'rgba(15, 23, 42, 0.35)';
  ctx.fillRect(0, 0, cw, ch);

  const px = (lon) => view.x + lon * view.scale;
  const py = (lat) => view.y - lat * view.scale;

  for (const g of GROUPS) {
    if (!groupOn.value[g.label]) continue;
    for (const name of g.layers) {
      const fc = mapData.value.layers[name];
      if (!fc || !fc.features) continue;
      const st = STYLE[name] || { stroke: 'rgba(148,163,184,0.5)', width: 1 };
      for (const f of fc.features || []) {
        if (!f.geometry || !f.geometry.coordinates) continue;
        const t = f.geometry.type;
        ctx.beginPath();
        const trace = (pts, close) => {
          if (!pts.length) return;
          ctx.moveTo(px(pts[0][0]), py(pts[0][1]));
          for (let i = 1; i < pts.length; i += 1) ctx.lineTo(px(pts[i][0]), py(pts[i][1]));
          if (close) ctx.closePath();
        };
        if (t === 'Polygon') f.geometry.coordinates.forEach((ring) => trace(ring, true));
        else if (t === 'MultiPolygon') f.geometry.coordinates.forEach((poly) => poly.forEach((ring) => trace(ring, true)));
        else if (t === 'LineString') trace(f.geometry.coordinates, false);
        else if (t === 'MultiLineString') f.geometry.coordinates.forEach((line) => trace(line, false));
        if (st.fill && (t.includes('Polygon'))) { ctx.fillStyle = st.fill; ctx.fill(); }
        if (st.stroke) { ctx.strokeStyle = st.stroke; ctx.lineWidth = st.width; ctx.stroke(); }
        if (t === 'Point' && st.fill) {
          ctx.fillStyle = st.fill;
          ctx.beginPath();
          ctx.arc(px(f.geometry.coordinates[0]), py(f.geometry.coordinates[1]), 1.6, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }
  drawLabels();
}

function drawLabels() {
  if (view.scale < 1.2) return;
  const px = (lon) => view.x + lon * view.scale;
  const py = (lat) => view.y - lat * view.scale;
  ctx.font = '10px system-ui, sans-serif';
  ctx.textAlign = 'center';
  const label = (lon, lat, text, color) => {
    ctx.fillStyle = color;
    ctx.fillText(text, px(lon), py(lat));
  };
  const rw = mapData.value.layers.runwayelement;
  if (rw && groupOn.value['跑道']) {
    for (const f of rw.features || []) {
      const c = f.geometry?.coordinates?.[0]?.[0];
      if (c && f.properties?.idrwy) label(c[0], c[1], f.properties.idrwy, 'rgba(255,255,255,0.85)');
    }
  }
  const ps = mapData.value.layers.parkingstandlocation;
  if (ps && groupOn.value['机坪与停机位'] && view.scale > 2.2) {
    for (const f of ps.features || []) {
      const c = f.geometry?.coordinates;
      if (c && f.properties?.idstd) label(c[0], c[1], f.properties.idstd, 'rgba(147,197,253,0.9)');
    }
  }
}

/* ---------- 交互 ---------- */
function setupCanvas() {
  canvas = document.getElementById('gmap-canvas');
  if (!canvas) return;
  ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;

  canvas.addEventListener('mousedown', (e) => { dragFrom = { x: e.offsetX, y: e.offsetY }; });
  window.addEventListener('mouseup', () => { dragFrom = null; });
  canvas.addEventListener('mousemove', (e) => {
    if (!dragFrom) return;
    view.x += e.offsetX - dragFrom.x;
    view.y += e.offsetY - dragFrom.y;
    dragFrom = { x: e.offsetX, y: e.offsetY };
    draw();
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const mx = e.offsetX, my = e.offsetY;
    view.x = mx - (mx - view.x) * factor;
    view.y = my - (my - view.y) * factor;
    view.scale *= factor;
    draw();
  }, { passive: false });
}

function reloadDraw() { requestAnimationFrame(() => draw()); }

watch(() => selected.value, () => {});
watch(groupOn, () => reloadDraw(), { deep: true });

onMounted(async () => {
  try {
    const data = await api.get('/api/nav/ground-map/airports');
    airports.value = data.airports || [];
  } catch (e) {
    showToast(e.message);
  }
  setupCanvas();
  window.addEventListener('resize', () => { if (mapData.value) { fit(); draw(); } });
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-title">机场地面图</div>
      <div class="page-desc">机场地面设施矢量图，跑道/滑行道/机坪/停机位/标志/灯光 · 覆盖全球 {{ airports.length }} 个机场 · 数据源 X-Plane 场景 GIS</div>
    </div>

    <div class="glass card" style="margin-bottom: 16px">
      <div class="input-row" style="max-width: 560px">
        <input v-model="q" class="input" placeholder="输入 ICAO 搜索机场，如 ZBAA / ZSPD / KJFK" />
      </div>
      <div v-if="q" class="list-sub" style="margin-top: 8px">匹配 {{ filtered.length }} 个机场</div>
      <div v-if="q" style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; max-height: 130px; overflow-y: auto">
        <button
          v-for="a in filtered.slice(0, 60)" :key="a"
          class="btn btn-sm" :class="selected === a ? 'btn-primary' : 'btn-ghost'"
          @click="select(a)"
        >{{ a }}</button>
      </div>
    </div>

    <div v-if="err" class="glass card"><div class="empty">{{ err }}</div></div>

    <div v-if="selected && mapData" class="glass card" style="padding: 12px">
      <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 10px">
        <div class="card-title" style="margin: 0">{{ selected }} 机场地面图</div>
        <div v-for="g in GROUPS" :key="g.label" style="display: flex; align-items: center">
          <CheckBox v-model="groupOn[g.label]" :label="g.label" @update:model-value="reloadDraw" />
        </div>
        <button class="btn btn-ghost btn-sm" style="margin-left: auto" @click="() => { fit(); draw(); }">复位视图</button>
      </div>
      <canvas
        id="gmap-canvas"
        style="width: 100%; height: 560px; border-radius: 10px; cursor: grab; touch-action: none"
      ></canvas>
      <div class="list-sub" style="margin-top: 8px">拖拽平移 · 滚轮缩放 · 数据源 X-Plane 机场场景 GIS，AIRAC 2609 · 仅限模拟飞行娱乐使用</div>
    </div>
  </div>
</template>
