/**
 * 桌宠物理，纯计算，无 DOM
 *
 * 移植自开源项目 dsh-pet 的 src/shared/physics.ts + motion.ts，Copyright c 2026
 * PC2005-cloud，MIT 许可，见 NOTICE-dsh-pet.md。移植时只保留浏览器里需要的那部分：
 * 弹簧跟手、松手甩抛初速估算、抛物线积分 + 边界反弹、落地/点击 Q 弹挤压、移动几何规划。
 * 多屏/桌宠互撞等桌面端逻辑没有搬过来，网页里只有一块视口。
 *
 * 为什么要照抄曲线常量：手感就是这几个数，过阻尼弹簧 / 软钳速 / 落地 Q 弹幅度，
 * 自己重新调参不会更好，只是会跟上游的观感不一致。
 */

/* ---------------- 拖拽跟手，过阻尼弹簧 ----------------*/
const SPRING_K = 200;
const SPRING_C = 30;
/** 抛掷初速估算：采样窗口 / 过期判定 / 最小跨度 */
const TRAIL_KEEP_MS = 200;
const RELEASE_WINDOW_MS = 150;
const RELEASE_STALE_MS = 150;
const MIN_SPAN_MS = 20;
const SEG_MIN_DT_MS = 8;
/** 松手速度低于它 = 温柔放下，不抛*/
const DEAD_ZONE_SPEED = 500;
const MAX_THROW_SPEED = 3600;
const PEAK_WEIGHT = 0.5;
const ACCEL_REF = 8000;
const ACCEL_GAIN_MAX = 0.6;

/* ---------------- 抛体 ---------------- */
const GRAVITY = 1400;
const RESTITUTION = 0.78;
const GROUND_FRICTION = 2.5;
const CEILING_BOUNCE = true;
const REST_VY = 40;
const REST_VX = 15;
const MAX_STEP_DT = 0.05;

/* ---------------- Q 弹挤压 ---------------- */
export const SQ_SQUASH = 0.55;
const SQ_DURATION_MS = 220;
const SQ_MAX_SQUASH = 0.55;
const SQ_SOFT_SPEED = 300;
const SQ_HARD_SPEED = 1500;

export const squashDurationMs = SQ_DURATION_MS;

/** 弹簧速度步进，调用方随后 x += v*dt*/
export const springStep = (v, x, target, dt) => v + ((target - x) * SPRING_K - v * SPRING_C) * dt;

/** 剔除超窗口的旧轨迹采样 */
export function trimTrail(trail, now) {
  const cutoff = now - TRAIL_KEEP_MS;
  let i = 0;
  while (i < trail.length && trail[i].t < cutoff) i++;
  return i === 0 ? trail : trail.slice(i);
}

const softClampSpeed = (speed) => (speed <= 0 ? 0 : MAX_THROW_SPEED * (1 - Math.exp(-speed / MAX_THROW_SPEED)));

/**
 * 由拖拽轨迹估松手初速，px/s：端点平均速度与峰值按 PEAK_WEIGHT 加权，
 * 末段仍在加速时按比例增益；软钳速封顶。返回 null = 温柔放下。
 */
export function estimateReleaseVelocity(trail, now) {
  if (!trail.length) return null;
  const last = trail[trail.length - 1];
  if (now - last.t > RELEASE_STALE_MS) return null;
  const win = trail.filter((s) => now - s.t <= RELEASE_WINDOW_MS);
  if (win.length < 2) return null;
  const t0 = win[0].t;
  const x0 = win[0].x;
  const y0 = win[0].y;
  const t1 = win[win.length - 1].t;
  const x1 = win[win.length - 1].x;
  const y1 = win[win.length - 1].y;
  const spanMs = t1 - t0;
  if (spanMs < MIN_SPAN_MS) return null;
  const baseVx = ((x1 - x0) / spanMs) * 1000;
  const baseVy = ((y1 - y0) / spanMs) * 1000;
  const baseSpeed = Math.hypot(baseVx, baseVy);
  if (baseSpeed < 1e-6) return null;

  const segSpeeds = [];
  let px = x0;
  let py = y0;
  let pt = t0;
  for (const s of win.slice(1)) {
    const dt = s.t - pt;
    if (dt >= SEG_MIN_DT_MS) {
      segSpeeds.push({ speed: (Math.hypot(s.x - px, s.y - py) / dt) * 1000, tEnd: s.t });
      px = s.x;
      py = s.y;
      pt = s.t;
    }
  }
  const peakSpeed = segSpeeds.length ? Math.max(...segSpeeds.map((v) => v.speed)) : baseSpeed;
  let accel = 0;
  if (segSpeeds.length >= 2) {
    const lastSeg = segSpeeds[segSpeeds.length - 1];
    const firstSeg = segSpeeds[0];
    accel = (lastSeg.speed - firstSeg.speed) / Math.max((lastSeg.tEnd - firstSeg.tEnd) / 1000, MIN_SPAN_MS / 1000);
  }
  const speedBeforeClamp =
    ((1 - PEAK_WEIGHT) * baseSpeed + PEAK_WEIGHT * peakSpeed) *
    (1 + Math.min(Math.max(accel, 0) / ACCEL_REF, 1) * ACCEL_GAIN_MAX);
  const speed = softClampSpeed(speedBeforeClamp);
  if (speed < DEAD_ZONE_SPEED) return null;
  return { vx: (baseVx / baseSpeed) * speed, vy: (baseVy / baseSpeed) * speed };
}

/** 抛掷边界，舞台左上角的允许范围：身体贴到屏幕边缘才反弹*/
export function throwBounds({ W, H, size, sideAllow }) {
  const h = (size * 9) / 16;
  return { minX: -sideAllow, minY: 0, maxX: W - size + sideAllow, maxY: H - h };
}

/**
 * 抛体单步积分 + 边界反弹。
 * 返回 { x, y, vx, vy, bounced, atRest }；atRest = 贴地且低速，调用方应停止循环。
 */
export function throwStep(s, dtRaw, bounds) {
  const dt = Math.min(Math.max(dtRaw, 0), MAX_STEP_DT);
  let { x, y, vx, vy } = s;
  vy += GRAVITY * dt;
  x += vx * dt;
  y += vy * dt;
  let bounced = false;
  if (x < bounds.minX) {
    x = bounds.minX;
    vx = Math.abs(vx) * RESTITUTION;
    bounced = true;
  } else if (x > bounds.maxX) {
    x = bounds.maxX;
    vx = -Math.abs(vx) * RESTITUTION;
    bounced = true;
  }
  if (y < bounds.minY) {
    if (CEILING_BOUNCE) {
      y = bounds.minY;
      vy = Math.abs(vy) * RESTITUTION;
      bounced = true;
    }
  } else if (y >= bounds.maxY) {
    y = bounds.maxY;
    vx *= Math.max(0, 1 - GROUND_FRICTION * dt);
    vy = Math.abs(vy) < REST_VY ? 0 : -Math.abs(vy) * RESTITUTION;
    bounced = true;
  }
  const speed = Math.hypot(vx, vy);
  const atRest =
    (y >= bounds.maxY - 1 && Math.abs(vy) < 1 && Math.abs(vx) < REST_VX) || (bounced && speed < REST_VY && Math.abs(vy) < 1);
  return { x, y, vx, vy, bounced, atRest };
}

/** Q 弹挤压曲线：u∈[0,1] → scaleY，下压 ease-in，回弹 easeOutBack 带约 4% 过冲*/
export function squashScale(u, squash = SQ_SQUASH) {
  if (u < 0.45) {
    const p = u / 0.45;
    return 1 - (1 - squash) * p * p;
  }
  const p = (u - 0.45) / 0.55;
  const c1 = 1.70158;
  const c3 = c1 + 1;
  const f = 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2);
  return Math.min(1.12, squash + (1 - squash) * Math.max(f, 0));
}

/** 落地冲击速度 → 下压幅度，轻落 0.8，重砸吃满 0.55*/
export function landingSquash(impactSpeed) {
  const t = Math.min(Math.max((Math.abs(impactSpeed) - SQ_SOFT_SPEED) / (SQ_HARD_SPEED - SQ_SOFT_SPEED), 0), 1);
  return Math.min(0.8, 1 - t * (1 - SQ_MAX_SQUASH));
}

/** 区间随机整数 */
const randomBetween = (min, max) => Math.floor(min + Math.random() * (max - min));

/**
 * 规划一次移动：返回起点/终点的视口比例与总距离；目标越界返回 null，调用方退回原地动作。
 * sideAllow = 画布两侧透明边，按「身体贴边」而不是「整个视频盒贴边」判定边界。
 */
export function planMove({ cx, cy, W, H, dir, minDist, maxDist, margin, halfW, sideAllow }) {
  const side = sideAllow || 0;
  const distance = randomBetween(minDist, maxDist);
  const target = cx + dir * distance;
  const leftBound = margin + halfW - side;
  const rightBound = W - margin - halfW + side;
  if (target < leftBound || target > rightBound) return null;
  return {
    startRatio: cx / W,
    startYRatio: cy / H,
    targetRatio: target / W,
    totalRatio: Math.abs(target - cx) / W,
  };
}
