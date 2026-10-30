<script setup>
/**
 * 桌面小鲸灵，鲸宝—— 开源桌宠 dsh-pet 的网页版
 *
 * 形象与动画来自开源项目 dsh-pet，https://github.com/PC2005-cloud/dsh-pet：
 * 33 段 10 秒长、640×360 的 VP9-alpha 透明动画，待机呼吸、打瞌睡、玩魔方、写代码、
 * 涮火锅、蓝鲸现世……，播放器与物理曲线按上游实现移植，代码 MIT。
 * 素材「允许开源使用、禁止商用」；本站是公益社区站，已按许可署名
 * 仓库根 NOTICE-dsh-pet.md + 右键菜单「关于桌宠」。
 *
 * 行为，与上游一致的骨架，网页场景做了裁剪：
 *   - 动画链：每段播完按权重掷骰选下一段，待机 / 转向 / 走动 / 随机动作分类，永不停止
 *   - 点击：随机回应动画 + Q 弹挤压 + 一句台词
 *   - 拖拽：过阻尼弹簧跟手；松手按轨迹估速，用力甩出沿抛物线飞、撞边反弹、落地 Q 弹
 *   - 走动：移动类动画播放期间按视频时间轴真实位移，首尾原地、身体贴边不越界
 *   - 右键，触屏长按：动作分类点播 / 聊两句 / 回到初始位置 / 收起 / 关于
 *   - 对话：走站内 /api/pet/chat，后端代理豆包，失败时回落到内置台词，绝不哑掉
 *   - Safari / iOS 不支持 VP9 alpha，自动降级成静态立绘，poster.webp，仍透明
 *
 * 性能：位移只写 transform；rAF 只在跟手/甩抛/走动时跑，静止时全停；
 * 标签页隐藏暂停视频与所有定时器；尊重 prefers-reduced-motion，不做 Q 弹与甩抛。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { api } from '../api.js';
import { petHover, setPetEnabled } from '../pet.js';
import { greeting, reply, talk } from '../petTalk.js';
import { useAuthStore } from '../stores/auth.js';
import {
  BODY,
  CATEGORIES,
  CLICKS,
  DRAG,
  EVENTS,
  HIT,
  IDLE,
  PET_REF_WIDTH,
  nameOf,
  pick,
  pickCategory,
  pickNext,
  posterUrl,
} from '../deskpet/catalog.js';
import { createStage } from '../deskpet/stage.js';
import {
  SQ_SQUASH,
  estimateReleaseVelocity,
  landingSquash,
  planMove,
  springStep,
  squashDurationMs,
  squashScale,
  throwBounds,
  throwStep,
  trimTrail,
} from '../deskpet/physics.js';

const STAGE_DESKTOP = 320;
const STAGE_MOBILE = 240;
const EDGE = 24; // 初始位置：身体右缘距视口右边
const GROUND_GAP = 4; // 舞台底边距视口底部
const DRAG_THRESHOLD = 5;
const LONG_PRESS_MS = 500;

const auth = useAuthStore();
const stageW = ref(STAGE_DESKTOP);
const stageH = computed(() => Math.round((stageW.value * 9) / 16));
const sideAllow = computed(() => Math.round(stageW.value * BODY.left));

/** 舞台左上角，视口坐标；位移只写 transform*/
const x = ref(0);
const y = ref(0);
const facing = ref('left'); // 'left' 原生朝向；'right' 水平镜像
const anim = ref(IDLE[0]);
const mode = ref('chain'); // chain | click | drag | move | event
const posterMode = ref(false);
const dragging = ref(false);
const speech = ref('');
const chatOpen = ref(false);
const chatInput = ref('');
const thinking = ref(false);
const menu = ref({ open: false, x: 0, y: 0, view: 'root', cat: '' });

const videoA = ref(null);
const videoB = ref(null);
const artEl = ref(null);
/** 哪块视频在前面，is-front 类交给 Vue 绑定，stage 只回报下标*/
const frontSlot = ref(0);

let reduced = false;
let disposed = false;
let stage = null;
let pendingNext = null;
let posterTimer = 0;
let speechTimer = 0;
let whisperTimer = 0;
let boundsTimer = 0;
let moveRaf = 0;
let movePlan = null;
let throwRaf = 0;
let dragRaf = 0;
let squashRaf = 0;
let squashToken = 0;
let longPressTimer = 0;
let chatSeq = 0;
const drag = { active: false, moved: false, sx: 0, sy: 0, offX: 0, offY: 0, trail: [], target: { x: 0, y: 0 }, vel: { vx: 0, vy: 0 } };

/* ---------------- 几何 ---------------- */
const groundY = () => window.innerHeight - stageH.value - GROUND_GAP;
const clampX = (v) => Math.min(Math.max(v, -sideAllow.value), window.innerWidth - stageW.value + sideAllow.value);
const clampY = (v) => Math.min(Math.max(v, 0), groundY());

function computeSize() {
  stageW.value = window.innerWidth <= 720 ? STAGE_MOBILE : STAGE_DESKTOP;
}

function resetPos() {
  x.value = clampX(window.innerWidth - EDGE - BODY.right * stageW.value);
  y.value = clampY(groundY());
}

/* ---------------- 说话 ---------------- */
function say(text, ms = 6000) {
  if (!text) return;
  speech.value = text;
  if (speechTimer) clearTimeout(speechTimer);
  speechTimer = setTimeout(() => {
    speech.value = '';
  }, ms);
}

function petCtx() {
  return {
    name: auth.user?.username || '',
    cid: auth.user?.cid || '',
    rank: auth.user?.pilot_rank || '',
  };
}

/* ---------------- Q 弹挤压 ---------------- */
function squash(depth = SQ_SQUASH) {
  if (reduced || !artEl.value) return;
  const el = artEl.value;
  const my = ++squashToken;
  if (squashRaf) cancelAnimationFrame(squashRaf);
  const t0 = performance.now();
  const step = () => {
    if (my !== squashToken || disposed) return;
    const u = Math.min((performance.now() - t0) / squashDurationMs, 1);
    el.style.transform = `scaleY(${squashScale(u, depth)})`;
    if (u < 1) squashRaf = requestAnimationFrame(step);
    else {
      squashRaf = 0;
      el.style.transform = '';
    }
  };
  squashRaf = requestAnimationFrame(step);
}

/* ---------------- 动画链 ---------------- */
function armPosterAdvance() {
  if (posterTimer) clearTimeout(posterTimer);
  posterTimer = setTimeout(handleEnded, 8000);
}

/**
 * 切到某段动画。
 * @param {string} slug
 * @param {'chain'|'click'|'drag'|'move'|'event'} m
 * @param {boolean} restart 同一段也要重播，拖拽/飞行时循环播放悬空姿势用
 */
function play(slug, m = 'chain', restart = false) {
  if (!slug || disposed) return null;
  if (!restart && slug === anim.value && m === mode.value) return null;
  mode.value = m;
  anim.value = slug;
  pendingNext = null;
  if (posterMode.value) {
    armPosterAdvance();
    return null;
  }
  if (!stage) return null;
  return stage.play(slug, { facing: facing.value, restart }).then((el) => {
    if (!el || disposed) return el;
    if (mode.value === 'chain' && !drag.active) {
      pendingNext = pickNext(slug);
      stage.preload(pendingNext.slug);
    }
    return el;
  });
}

function stopMove() {
  if (moveRaf) cancelAnimationFrame(moveRaf);
  moveRaf = 0;
  movePlan = null;
}

function toIdle() {
  stopMove();
  play(IDLE[0], 'chain');
}

/** 一段动画播完后的去留，上游 handleEnded 的精简版*/
function handleEnded() {
  if (disposed) return;
  if (drag.active) {
    // 拖拽/飞行中姿势播完了：原地重播，保持悬空姿势
    play(DRAG, 'drag', true);
    return;
  }
  if (mode.value !== 'chain') {
    toIdle();
    return;
  }
  const next = pendingNext || pickNext(anim.value);
  pendingNext = null;
  advance(next);
}

function advance(next) {
  if (next.kind === 'move') {
    if (!reduced && startMove(next.slug, next.params)) return;
    // 走不过去，贴边或省电模式：退回一个原地动作，不丢这一拍
    const cat = pickCategory();
    play(pick(cat.actions, anim.value), 'chain');
    return;
  }
  if (next.kind === 'turn') facing.value = facing.value === 'left' ? 'right' : 'left';
  play(next.slug, 'chain');
}

/* ---------------- 走动，移动类动画期间按视频时间轴位移 ----------------*/
function startMove(slug, params) {
  const W = window.innerWidth;
  const scale = stageW.value / PET_REF_WIDTH;
  const dir = facing.value === 'right' ? 1 : -1;
  const plan = planMove({
    cx: x.value + stageW.value / 2,
    cy: y.value + stageH.value / 2,
    W,
    H: window.innerHeight,
    dir,
    minDist: params.minDist * scale,
    maxDist: params.maxDist * scale,
    margin: params.margin,
    halfW: stageW.value / 2,
    sideAllow: sideAllow.value,
  });
  if (!plan) return false;
  stopMove();
  movePlan = { ...plan, dir, leadSec: params.leadSec, tailSec: params.tailSec };
  const p = play(slug, 'move');
  const drive = () => {
    if (mode.value === 'move') driveMove();
  };
  if (p && p.then) p.then(drive);
  else drive();
  return true;
}

function driveMove() {
  cancelAnimationFrame(moveRaf);
  const step = () => {
    if (!movePlan || disposed) {
      moveRaf = 0;
      return;
    }
    const dur = stage ? stage.duration() : 10;
    const t = stage ? stage.time() : 0;
    const { startRatio, startYRatio, targetRatio, dir, totalRatio, leadSec, tailSec } = movePlan;
    const travel = Math.max(0.1, dur - leadSec - tailSec);
    let rx;
    if (t <= leadSec) rx = startRatio;
    else if (t >= dur - tailSec) rx = targetRatio;
    else rx = startRatio + dir * totalRatio * ((t - leadSec) / travel);
    x.value = clampX(rx * window.innerWidth - stageW.value / 2);
    y.value = clampY(startYRatio * window.innerHeight - stageH.value / 2);
    moveRaf = requestAnimationFrame(step);
  };
  moveRaf = requestAnimationFrame(step);
}

/* ---------------- 拖拽 / 甩抛 ---------------- */
function stopThrow() {
  if (throwRaf) cancelAnimationFrame(throwRaf);
  throwRaf = 0;
}

function startDragFollow() {
  if (dragRaf) return;
  let last = performance.now();
  const step = () => {
    if (!drag.active || disposed) {
      dragRaf = 0;
      return;
    }
    const now = performance.now();
    const dt = Math.min((now - last) / 1000, 1 / 30);
    last = now;
    drag.vel.vx = springStep(drag.vel.vx, x.value, drag.target.x, dt);
    drag.vel.vy = springStep(drag.vel.vy, y.value, drag.target.y, dt);
    x.value = clampX(x.value + drag.vel.vx * dt);
    y.value = clampY(y.value + drag.vel.vy * dt);
    dragRaf = requestAnimationFrame(step);
  };
  dragRaf = requestAnimationFrame(step);
}

function onPointerDown(e) {
  if (e.button !== 0 && e.pointerType === 'mouse') return;
  if (menu.value.open) closeMenu();
  e.preventDefault();
  stopThrow();
  stopMove();
  drag.active = true;
  drag.moved = false;
  drag.sx = e.clientX;
  drag.sy = e.clientY;
  drag.offX = e.clientX - x.value;
  drag.offY = e.clientY - y.value;
  drag.trail = [{ t: performance.now(), x: e.clientX, y: e.clientY }];
  drag.target = { x: x.value, y: y.value };
  drag.vel = { vx: 0, vy: 0 };
  dragging.value = true;
  if (dragRaf) cancelAnimationFrame(dragRaf);
  dragRaf = 0;
  window.addEventListener('pointermove', onDragMove);
  window.addEventListener('pointerup', onDragUp);
  window.addEventListener('pointercancel', onDragUp);
  if (e.pointerType !== 'mouse' && e.pointerType !== 'pen') {
    // 触屏没有右键：长按 500ms 打开菜单，移动超过阈值即取消，与拖拽共存
    clearTimeout(longPressTimer);
    longPressTimer = setTimeout(() => {
      if (!drag.active || drag.moved) return;
      drag.active = false;
      dragging.value = false;
      if (dragRaf) cancelAnimationFrame(dragRaf);
      dragRaf = 0;
      openMenu(e.clientX, e.clientY);
    }, LONG_PRESS_MS);
  }
}

function onDragMove(e) {
  if (!drag.active) return;
  if (Math.abs(e.clientX - drag.sx) > DRAG_THRESHOLD || Math.abs(e.clientY - drag.sy) > DRAG_THRESHOLD) {
    if (!drag.moved) {
      drag.moved = true;
      clearTimeout(longPressTimer);
      play(DRAG, 'drag', true); // 真的拖起来了才切悬空姿势
      say(talk('drag', petCtx()), 3500);
      startDragFollow();
    }
  }
  drag.target = { x: clampX(e.clientX - drag.offX), y: clampY(e.clientY - drag.offY) };
  const now = performance.now();
  drag.trail.push({ t: now, x: e.clientX, y: e.clientY });
  drag.trail = trimTrail(drag.trail, now);
}

function onDragUp() {
  clearTimeout(longPressTimer);
  window.removeEventListener('pointermove', onDragMove);
  window.removeEventListener('pointerup', onDragUp);
  window.removeEventListener('pointercancel', onDragUp);
  if (!drag.active) return;
  drag.active = false;
  dragging.value = false;
  if (dragRaf) cancelAnimationFrame(dragRaf);
  dragRaf = 0;
  x.value = clampX(x.value);
  y.value = clampY(y.value);
  if (!drag.moved) {
    onTap();
    return;
  }
  const vel = reduced ? null : estimateReleaseVelocity(drag.trail, performance.now());
  if (!vel || petHover.value) {
    say(talk(petHover.value ? 'dropHover' : 'drop', petCtx()), 4000);
    toIdle();
    return;
  }
  say(talk('drop', petCtx()), 4000);
  startThrow(x.value, y.value, vel.vx, vel.vy);
}

function startThrow(px, py, vx, vy) {
  stopThrow();
  const bounds = throwBounds({ W: window.innerWidth, H: window.innerHeight, size: stageW.value, sideAllow: sideAllow.value });
  let state = { x: px, y: py, vx, vy };
  let last = performance.now();
  play(DRAG, 'drag', true);
  const step = () => {
    if (disposed) {
      throwRaf = 0;
      return;
    }
    const now = performance.now();
    const dt = (now - last) / 1000;
    last = now;
    const impact = Math.abs(state.vy);
    const res = throwStep(state, dt, bounds);
    state = { x: res.x, y: res.y, vx: res.vx, vy: res.vy };
    x.value = state.x;
    y.value = state.y;
    if (res.bounced) squash(landingSquash(impact));
    if (res.atRest) {
      throwRaf = 0;
      y.value = clampY(y.value);
      toIdle();
      return;
    }
    throwRaf = requestAnimationFrame(step);
  };
  throwRaf = requestAnimationFrame(step);
}

/* ---------------- 点击反应 ---------------- */
function onTap() {
  squash();
  play(pick(CLICKS), 'click');
  say(talk('click', petCtx()), 5000);
}

/* ---------------- 对话 ---------------- */
function toggleChat() {
  chatOpen.value = !chatOpen.value;
  if (chatOpen.value) {
    stopMove();
    if (!speech.value) say(talk('say', petCtx()), 8000);
  }
}

async function sendChat() {
  const text = chatInput.value.trim();
  if (!text || thinking.value) return;
  chatInput.value = '';
  const seq = ++chatSeq;
  thinking.value = true;
  say('……让我想想。', 30000);
  play(EVENTS.thinking, 'event');
  try {
    // 后端代理火山方舟；30 秒超时，模型实测 3-6 秒，留足余量
    const data = await api.post('/api/pet/chat', { message: text }, 30000);
    if (seq !== chatSeq) return;
    say(data.reply, 12000);
    play(EVENTS.success, 'event');
  } catch {
    if (seq !== chatSeq) return;
    // 兜底：AI 不可用/超时/超额时用内置关键词应答，宠物任何时候都不能哑掉
    say(reply(text, petCtx()), 9000);
    play(EVENTS.error, 'event');
  } finally {
    if (seq === chatSeq) thinking.value = false;
  }
}

/* ---------------- 右键菜单 ---------------- */
const catActions = computed(() => {
  const cat = CATEGORIES.find((c) => c.id === menu.value.cat);
  return cat ? cat.actions : [];
});

function openMenu(clientX, clientY) {
  const W = 220;
  const H = 320;
  menu.value = {
    open: true,
    x: Math.min(Math.max(clientX, 8), Math.max(8, window.innerWidth - W - 8)),
    y: Math.min(Math.max(clientY, 8), Math.max(8, window.innerHeight - H - 8)),
    view: 'root',
    cat: '',
  };
}

function closeMenu() {
  menu.value.open = false;
}

function onContextMenu(e) {
  e.preventDefault();
  stopMove();
  stopThrow();
  openMenu(e.clientX, e.clientY);
}

function playFromMenu(slug) {
  closeMenu();
  play(slug, 'event');
}

function openCat(id) {
  menu.value.view = 'list';
  menu.value.cat = id;
}

function onDocPointerDown(e) {
  if (!menu.value.open) return;
  const el = document.querySelector('.pet-menu');
  if (el && el.contains(e.target)) return;
  closeMenu();
}

/* ---------------- 定时碎碎念 / 问好 ---------------- */
function scheduleWhisper() {
  clearTimeout(whisperTimer);
  if (disposed) return;
  const delay = 120000 + Math.random() * 120000;
  whisperTimer = setTimeout(() => {
    if (!document.hidden && !chatOpen.value && !drag.active && mode.value === 'chain') {
      play(pick(EVENTS.whisper), 'event');
      say(talk('idle', petCtx()), 8000);
    }
    scheduleWhisper();
  }, delay);
}

/* ---------------- 可见性 / 尺寸 / 模式切换 ---------------- */
function onVisibility() {
  if (!stage) return;
  if (document.hidden) {
    stage.pause();
    clearTimeout(whisperTimer);
  } else {
    stage.resume();
    scheduleWhisper();
  }
}

function onResize() {
  computeSize();
  x.value = clampX(x.value);
  y.value = clampY(y.value);
}

/** 跑不丢保险：任何原因，异常状态/竞态/未来改动引入的 bug 导致坐标出界时，
 *  空闲状态下把它钳回视口内。正常路径本来就有 clamp，这里只是兜底。*/
function guardBounds() {
  if (disposed || drag.active || movePlan || throwRaf) return;
  const cx = clampX(x.value);
  const cy = clampY(y.value);
  if (cx !== x.value || cy !== y.value) {
    x.value = cx;
    y.value = cy;
  }
}

function onScroll(e) {
  if (!menu.value.open) return;
  // 菜单自己的动作清单是内部滚动的，capture 监听也会收到，不能因为滚清单就把菜单收了
  const t = e && e.target;
  if (t && t !== document && t.closest && t.closest('.pet-menu')) return;
  closeMenu();
}

// 手机端打开对话时先把宠物抬到屏幕中部，否则软键盘一弹把输入框顶出可视区
watch(chatOpen, (open) => {
  if (window.innerWidth > 720) return;
  if (open) {
    const lift = Math.round(window.innerHeight * 0.42);
    if (y.value > lift) y.value = clampY(lift);
  } else if (!petHover.value) {
    y.value = clampY(groundY());
  }
});

// 悬停模式切回落地：自然掉下去，复用抛掷物理
watch(petHover, (on) => {
  if (on) {
    say(talk('hoverOn', petCtx()), 4000);
  } else {
    say(talk('hoverOff', petCtx()), 4000);
    if (y.value < groundY() - 2) startThrow(x.value, y.value, 0, 0);
  }
});

/* ---------------- 挂载 / 卸载 ---------------- */
function isSafariLike() {
  const ua = navigator.userAgent || '';
  const isIOS = /iP(hone|ad|od)/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isSafari = /Safari\//.test(ua) && !/(Chrome|Chromium|CriOS|Edg|OPR|Firefox|FxiOS|Android)/.test(ua);
  // iOS 上所有浏览器的内核都是 WebKit，同样没有 VP9 alpha —— 一律走静态立绘
  return isIOS || isSafari;
}

function onStageError(err) {
  if (posterMode.value) return;
  console.warn('[desk-pet] 视频不可用，退回静态立绘：', err && err.message);
  posterMode.value = true;
  armPosterAdvance();
}

onMounted(() => {
  reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  computeSize();
  posterMode.value = isSafariLike();
  resetPos();
  if (!posterMode.value) {
    stage = createStage({
      slots: [videoA.value, videoB.value],
      onEnded: handleEnded,
      onError: onStageError,
      onFront: (idx) => {
        frontSlot.value = idx;
      },
    });
  }
  play(IDLE[0], 'chain');
  scheduleWhisper();
  boundsTimer = setInterval(guardBounds, 2000);
  window.addEventListener('resize', onResize, { passive: true });
  window.addEventListener('scroll', onScroll, { passive: true, capture: true });
  document.addEventListener('visibilitychange', onVisibility);
  document.addEventListener('pointerdown', onDocPointerDown);
  // 每次进入站点问一次好，不重复打扰
  let greeted = false;
  try {
    greeted = sessionStorage.getItem('ctyfly_pet_hi') === '1';
  } catch {
    /* 忽略：隐私模式下 sessionStorage 可能不可用 */
  }
  if (!greeted) {
    setTimeout(() => {
      if (disposed) return;
      play('click-wave', 'event');
      say(greeting(petCtx()), 8000);
      try {
        sessionStorage.setItem('ctyfly_pet_hi', '1');
      } catch {
        /* 忽略 */
      }
    }, 1300);
  }
});

onBeforeUnmount(() => {
  disposed = true;
  stopMove();
  stopThrow();
  if (dragRaf) cancelAnimationFrame(dragRaf);
  if (squashRaf) cancelAnimationFrame(squashRaf);
  if (posterTimer) clearTimeout(posterTimer);
  if (speechTimer) clearTimeout(speechTimer);
  if (whisperTimer) clearTimeout(whisperTimer);
  if (boundsTimer) clearInterval(boundsTimer);
  clearTimeout(longPressTimer);
  window.removeEventListener('pointermove', onDragMove);
  window.removeEventListener('pointerup', onDragUp);
  window.removeEventListener('pointercancel', onDragUp);
  window.removeEventListener('resize', onResize);
  window.removeEventListener('scroll', onScroll, { capture: true });
  document.removeEventListener('visibilitychange', onVisibility);
  document.removeEventListener('pointerdown', onDocPointerDown);
  if (stage) stage.dispose();
  stage = null;
});

function dismiss() {
  closeMenu();
  setPetEnabled(false);
}

/* ---------------- 视图 ---------------- */
const rootStyle = computed(() => ({
  transform: `translate3d(${x.value}px, ${y.value}px, 0)`,
  width: `${stageW.value}px`,
  height: `${stageH.value}px`,
}));

const rootClass = computed(() => ({
  'deskpet--drag': dragging.value,
  'deskpet--hover-mode': petHover.value,
}));

const hitStyle = computed(() => ({
  left: `${HIT.x0 * 100}%`,
  top: `${HIT.y0 * 100}%`,
  width: `${(HIT.x1 - HIT.x0) * 100}%`,
  height: `${(HIT.y1 - HIT.y0) * 100}%`,
}));

/** 气泡不能飘出视口：按宠物位置左右平移回来 */
const bubbleStyle = computed(() => {
  const BW = Math.min(232, window.innerWidth - 24);
  const pad = 12;
  const cx = x.value + stageW.value / 2;
  let shift = 0;
  if (cx - BW / 2 < pad) shift = pad - (cx - BW / 2);
  else if (cx + BW / 2 > window.innerWidth - pad) shift = window.innerWidth - pad - (cx + BW / 2);
  return { transform: `translateX(calc(-50% + ${shift}px))`, maxWidth: `${BW}px` };
});

const menuStyle = computed(() => ({ left: `${menu.value.x}px`, top: `${menu.value.y}px` }));

// 菜单打开时如果宠物被收起/路由变化，onBeforeUnmount 会清掉；这里只负责 esc 关闭
function onKeydown(e) {
  if (e.key === 'Escape' && menu.value.open) closeMenu();
}

watch(
  () => menu.value.open,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown);
    else window.removeEventListener('keydown', onKeydown);
  },
);
</script>

<template>
  <!-- data-anim：诊断用，线上 devtools 一眼看出当前段，blob 化后 video src 已不含 slug-->
  <div class="deskpet" :class="rootClass" :style="rootStyle" :data-anim="anim">
    <div class="deskpet-art" ref="artEl">
      <video
        v-show="!posterMode"
        ref="videoA"
        class="pet-video"
        :class="{ 'is-front': frontSlot === 0 }"
        muted
        playsinline
        preload="auto"
      ></video>
      <video
        v-show="!posterMode"
        ref="videoB"
        class="pet-video"
        :class="{ 'is-front': frontSlot === 1 }"
        muted
        playsinline
        preload="auto"
      ></video>
      <img
        v-if="posterMode"
        class="pet-video is-front pet-poster"
        :src="posterUrl(anim)"
        alt=""
        draggable="false"
      />
    </div>

    <!-- 命中区：只覆盖身体，素材画布四周是透明的，不能整块都吃点击-->
    <div
      class="deskpet-hit"
      :style="hitStyle"
      @pointerdown="onPointerDown"
      @contextmenu="onContextMenu"
      aria-hidden="true"
    ></div>

    <!-- 对话气泡：说话内容 + 输入框 -->
    <div v-if="speech || chatOpen" class="pet-bubble" :style="bubbleStyle" @pointerdown.stop>
      <div v-if="speech" class="pet-bubble-text" :class="{ 'is-thinking': thinking }">{{ speech }}</div>
      <form v-if="chatOpen" class="pet-chat" @submit.prevent="sendChat">
        <input
          v-model="chatInput"
          class="pet-chat-input"
          maxlength="60"
          placeholder="和鲸宝说点什么…"
          aria-label="和鲸宝对话"
        />
        <button class="pet-chat-send" type="submit" :disabled="thinking">
          {{ thinking ? '…' : '发送' }}
        </button>
      </form>
    </div>

    <!-- 右键 / 长按菜单：Teleport 到 body —— 根节点带 transform，会把 position:fixed
         的子元素变成相对自己定位，containing block 陷阱，与侧边栏 tooltip 同坑，
         菜单必须真正相对视口定位，所以挂出去-->
    <Teleport to="body">
      <div v-if="menu.open" class="pet-menu" :style="menuStyle" @pointerdown.stop @contextmenu.prevent>
      <template v-if="menu.view === 'root'">
        <button class="pet-menu-item" type="button" @click="menu.view = 'cats'">
          <span>动作</span><span class="pet-menu-arrow">›</span>
        </button>
        <button class="pet-menu-item" type="button" @click="toggleChat(); closeMenu()">聊两句</button>
        <button class="pet-menu-item" type="button" @click="resetPos(); closeMenu()">回到初始位置</button>
        <button class="pet-menu-item" type="button" @click="dismiss">收起鲸宝</button>
        <button class="pet-menu-item" type="button" @click="menu.view = 'about'">
          <span>关于桌宠</span><span class="pet-menu-arrow">›</span>
        </button>
        <div class="pet-menu-note">正在播：{{ nameOf(anim) }}</div>
      </template>

      <template v-else-if="menu.view === 'cats'">
        <button class="pet-menu-item pet-menu-back" type="button" @click="menu.view = 'root'">‹ 返回</button>
        <button
          v-for="c in CATEGORIES"
          :key="c.id"
          class="pet-menu-item"
          type="button"
          @click="openCat(c.id)"
        >
          <span>{{ c.id }}</span><span class="pet-menu-arrow">{{ c.actions.length }}</span>
        </button>
      </template>

      <template v-else-if="menu.view === 'list'">
        <button class="pet-menu-item pet-menu-back" type="button" @click="menu.view = 'cats'">‹ 返回</button>
        <div class="pet-menu-scroll">
          <button
            v-for="slug in catActions"
            :key="slug"
            class="pet-menu-item"
            :class="{ 'is-active': slug === anim }"
            type="button"
            @click="playFromMenu(slug)"
          >
            {{ nameOf(slug) }}
          </button>
        </div>
      </template>

      <template v-else>
        <div class="pet-menu-about">
          <strong>鲸宝 · 开源桌宠</strong>
          <p>形象与动画来自开源项目 dsh-pet。</p>
          <p>代码 MIT；动画素材允许开源使用、禁止商用。本站为公益社区站，已按许可证署名。</p>
          <a href="https://github.com/PC2005-cloud/dsh-pet" target="_blank" rel="noopener noreferrer">
            github.com/PC2005-cloud/dsh-pet
          </a>
          <button class="pet-menu-item" type="button" @click="closeMenu">关闭</button>
        </div>
      </template>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.deskpet {
  position: fixed;
  left: 0;
  top: 0;
  /* 层级：要盖在页面 UI 之上，顶栏 90 / 侧边栏 200 / Cookie 弹窗 400 / 模态框 500，
     仍低于提示条 999、气泡菜单 1000、路由进度条 1001 —— 那些是必须能点的临时层。
     根元素 pointer-events:none，只有命中区/气泡/菜单可点，不挡页面操作。*/
  z-index: 900;
  pointer-events: none;
  will-change: transform;
}

/* 舞台：素材原生 640×360，播放时整块撑满；人物只占中间一块，四周是透明边 */
.deskpet-art {
  position: absolute;
  inset: 0;
  /* Q 弹锚定在脚底线，素材 y≈330/360，压扁时脚不挪位*/
  transform-origin: 50% 91.67%;
}
.pet-video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  opacity: 0;
  transition: opacity 0.18s ease;
  pointer-events: none;
  user-select: none;
  -webkit-user-drag: none;
}
.pet-video.is-front {
  opacity: 1;
}

/* 命中区：素材画布里人物的实际范围，左右 31.25%~68.75%，上下 14%~93%*/
.deskpet-hit {
  position: absolute;
  pointer-events: auto;
  cursor: grab;
  /* 拖动时不触发页面滚动 / 长按选中文字 */
  touch-action: none;
  -webkit-touch-callout: none;
  user-select: none;
  border-radius: 24px;
}
.deskpet--drag .deskpet-hit {
  cursor: grabbing;
}
.deskpet--hover-mode .deskpet-hit {
  cursor: move;
}

/* ---------- 对话气泡 ---------- */
.pet-bubble {
  position: absolute;
  bottom: calc(100% - 18px);
  left: 50%;
  width: max-content;
  max-width: 232px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--modal-bg);
  backdrop-filter: blur(14px) saturate(140%);
  -webkit-backdrop-filter: blur(14px) saturate(140%);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
  color: var(--text);
  font-size: 12.5px;
  line-height: 1.6;
  text-align: left;
  white-space: normal;
  pointer-events: auto;
  z-index: 2;
}
.pet-bubble::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -5px;
  width: 9px;
  height: 9px;
  margin-left: -4.5px;
  background: var(--modal-bg);
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  border-radius: 0 0 3px 0;
  transform: rotate(45deg);
}
.pet-bubble-text {
  word-break: break-word;
}
@keyframes pet-think {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}
.pet-bubble-text.is-thinking {
  animation: pet-think 1.1s ease-in-out infinite;
}

.pet-chat {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.pet-chat-input {
  flex: 1;
  min-width: 0;
  width: 130px;
  padding: 5px 8px;
  border: 1px solid var(--input-border, var(--border));
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font-size: 12px;
  outline: none;
}
.pet-chat-input::placeholder {
  color: var(--gray);
}
.pet-chat-send {
  flex: none;
  padding: 5px 10px;
  border: 0;
  border-radius: 8px;
  background: var(--blue);
  color: #fff;
  font-size: 12px;
  cursor: pointer;
}
.pet-chat-send:hover:not(:disabled) {
  background: var(--blue-hover, var(--blue));
}
.pet-chat-send:disabled {
  opacity: 0.6;
  cursor: default;
}

/* ---------- 右键菜单 ---------- */
.pet-menu {
  position: fixed;
  z-index: 1001;
  width: 200px;
  max-height: 340px;
  overflow: hidden;
  padding: 6px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--modal-bg);
  backdrop-filter: blur(14px) saturate(140%);
  -webkit-backdrop-filter: blur(14px) saturate(140%);
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.2);
  font-size: 13px;
  color: var(--text);
  pointer-events: auto;
}
.pet-menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 7px 9px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.pet-menu-item:hover,
.pet-menu-item.is-active {
  background: rgba(88, 118, 232, 0.12);
  background: color-mix(in srgb, var(--blue) 14%, transparent);
  color: var(--blue);
}
.pet-menu-arrow {
  color: var(--gray);
  font-size: 12px;
}
.pet-menu-back {
  color: var(--text-2);
}
.pet-menu-scroll {
  max-height: 268px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.pet-menu-note {
  padding: 7px 9px 3px;
  border-top: 1px solid var(--border);
  margin-top: 4px;
  color: var(--gray);
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pet-menu-about {
  padding: 6px;
  line-height: 1.65;
  font-size: 12px;
  color: var(--text-2);
}
.pet-menu-about strong {
  display: block;
  margin-bottom: 4px;
  color: var(--text);
  font-size: 13px;
}
.pet-menu-about p {
  margin: 0 0 6px;
}
.pet-menu-about a {
  display: block;
  margin-bottom: 8px;
  color: var(--blue);
  word-break: break-all;
}

/* ---------- 无障碍 / 自适应 ---------- */
@media (prefers-reduced-motion: reduce) {
  .pet-video {
    transition: none;
  }
  .pet-bubble-text.is-thinking {
    animation: none;
  }
}

/* 手机端：气泡铺满可用宽度，输入框和按钮都加大到手指能点 */
@media (max-width: 720px) {
  .pet-bubble {
    font-size: 13px;
    padding: 10px 13px;
  }
  .pet-chat-input {
    width: 100%;
    padding: 8px 10px;
    font-size: 13px;
  }
  .pet-chat-send {
    padding: 8px 13px;
    font-size: 13px;
  }
  .pet-menu {
    width: 184px;
    font-size: 13.5px;
  }
  .pet-menu-item {
    padding: 9px 10px;
  }
}
</style>
