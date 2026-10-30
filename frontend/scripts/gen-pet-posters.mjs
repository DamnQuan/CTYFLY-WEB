/**
 * 生成 Safari 兜底静态图 + 探测素材几何，开发工具，不在 CI 里跑
 *
 * 为什么需要 poster：dsh-pet 的动画是 VP9-alpha WebM，透明底。Chrome / Edge / Firefox
 * 能透明播放，但 Safari，含 iOS Safari 不支持 VP9 的 alpha 通道 —— 直接播会得到一块
 * 黑色矩形。降级策略是：Safari 只显示静态立绘，poster 图，仍透明，动画链照常切换。
 * poster 必须带 alpha；用 canvas 从视频帧导出即可，canvas 默认就是 RGBA。
 *
 * 顺带产出：每段动画的时长、可见内容包围盒，用来定命中区和地面线。
 *
 * 用法，frontend/ 下：
 *   node scripts/gen-pet-posters.mjs # 生成 poster + 报告
 *   node scripts/gen-pet-posters.mjs --check # 只出报告，不写 poster
 *
 * 依赖：playwright-core + 本机 Edge，与仓库其它验收脚本一致，故不入 package.json；
 * 找不到 playwright-core 时会提示把 D:\audit-tools 加进 NODE_PATH。
 */
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { CURATED } from './pet-assets.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const PUBLIC = path.join(ROOT, 'public');
const POSTER = path.join(PUBLIC, 'pet', 'poster');
const REPORT = path.resolve(ROOT, '..', '.audit-tmp', 'pet-assets-report.json');
const EDGE_CANDIDATES = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
];

function requirePlaywright() {
  const tries = [HERE, 'D:\\audit-tools', process.cwd()];
  for (const base of tries) {
    try {
      return createRequire(path.join(base, 'noop.cjs'))('playwright-core');
    } catch { /* 继续找 */ }
  }
  console.error('✗ 找不到 playwright-core：请 `npm i` 到 D:\\audit-tools，或设置 NODE_PATH');
  process.exit(2);
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.webm': 'video/webm',
  '.png': 'image/png',
  '.json': 'application/json',
};

/** 极简静态服务器：必须支持 Range，否则 Chromium 的媒体加载会拿不到可用数据 */
function startServer() {
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent((req.url || '/').split('?')[0]);
    if (url === '/') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end('<!doctype html><html><body></body></html>');
      return;
    }
    const file = path.join(PUBLIC, url);
    if (!file.startsWith(PUBLIC) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404).end('not found');
      return;
    }
    const size = fs.statSync(file).size;
    const type = MIME[path.extname(file)] || 'application/octet-stream';
    const range = req.headers.range;
    if (range) {
      const m = /bytes=(\d*)-(\d*)/.exec(range);
      const start = m && m[1] ? parseInt(m[1], 10) : 0;
      const end = m && m[2] ? parseInt(m[2], 10) : size - 1;
      res.writeHead(206, {
        'Content-Type': type,
        'Content-Range': `bytes ${start}-${end}/${size}`,
        'Accept-Ranges': 'bytes',
        'Content-Length': end - start + 1,
      });
      fs.createReadStream(file, { start, end }).pipe(res);
      return;
    }
    res.writeHead(200, { 'Content-Type': type, 'Accept-Ranges': 'bytes', 'Content-Length': size });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

/** 在页面里对一段视频采样：时长 + 若干时间点的 alpha 包围盒 */
async function probe(page, slug, sampleCount) {
  return page.evaluate(
    async ({ url, sampleCount }) => {
      const W = 640;
      const H = 360;
      const video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      video.preload = 'auto';
      video.src = url;
      document.body.appendChild(video);
      await new Promise((resolve, reject) => {
        video.addEventListener('loadeddata', resolve, { once: true });
        video.addEventListener(
          'error',
          () => reject(new Error(`video error ${video.error ? video.error.code : '?'} ${video.error ? video.error.message : ''}`)),
          { once: true },
        );
        setTimeout(() => reject(new Error('timeout loadeddata')), 8000);
      });
      const canvas = document.createElement('canvas');
      canvas.width = W;
      canvas.height = H;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      const bboxOf = (data) => {
        let x0 = W;
        let y0 = H;
        let x1 = -1;
        let y1 = -1;
        let opaqueCorner = 0;
        for (let y = 0; y < H; y++) {
          for (let x = 0; x < W; x++) {
            const a = data[(y * W + x) * 4 + 3];
            if (a > 8) {
              if (x < x0) x0 = x;
              if (y < y0) y0 = y;
              if (x > x1) x1 = x;
              if (y > y1) y1 = y;
            }
          }
        }
        for (const [cx, cy] of [[2, 2], [W - 3, 2], [2, H - 3], [W - 3, H - 3]]) {
          if (data[(cy * W + cx) * 4 + 3] > 8) opaqueCorner++;
        }
        return { x0, y0, x1, y1, opaqueCorner };
      };
      const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : null;
      const times = [];
      for (let i = 0; i < sampleCount; i++) times.push(duration ? ((i + 0.5) / sampleCount) * duration : 0);
      const boxes = [];
      let poster = null;
      for (const t of times) {
        if (duration) {
          await new Promise((resolve) => {
            video.addEventListener('seeked', resolve, { once: true });
            video.currentTime = Math.min(t, Math.max(0, duration - 0.05));
          });
        }
        ctx.clearRect(0, 0, W, H);
        ctx.drawImage(video, 0, 0, W, H);
        const data = ctx.getImageData(0, 0, W, H).data;
        boxes.push(bboxOf(data));
        if (poster === null) poster = canvas.toDataURL('image/webp', 0.92);
      }
      const union = boxes.reduce(
        (a, b) => ({
          x0: Math.min(a.x0, b.x0),
          y0: Math.min(a.y0, b.y0),
          x1: Math.max(a.x1, b.x1),
          y1: Math.max(a.y1, b.y1),
          opaqueCorner: Math.max(a.opaqueCorner, b.opaqueCorner),
        }),
        { x0: W, y0: H, x1: -1, y1: -1, opaqueCorner: 0 },
      );
      video.remove();
      return { duration, canvas: { W, H }, union, boxes, poster };
    },
    { url: `/pet/webm/${slug}.webm`, sampleCount },
  );
}

async function main() {
  const checkOnly = process.argv.includes('--check');
  const { chromium } = requirePlaywright();
  const edge = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
  if (!edge) {
    console.error('✗ 找不到 Edge');
    process.exit(2);
  }
  fs.mkdirSync(path.dirname(REPORT), { recursive: true });
  if (!checkOnly) fs.mkdirSync(POSTER, { recursive: true });

  const server = await startServer();
  const port = server.address().port;
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  const page = await browser.newPage({ viewport: { width: 800, height: 600 } });
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: 'domcontentloaded' });

  const out = [];
  let alphaOk = 0;
  let posterBytes = 0;
  for (const { slug, name } of CURATED) {
    const info = await probe(page, slug, 5);
    if (info.union.opaqueCorner === 0 && info.union.x1 > info.union.x0) alphaOk++;
    const posterPath = path.join(POSTER, `${slug}.webp`);
    if (!checkOnly && info.poster) {
      fs.writeFileSync(posterPath, Buffer.from(info.poster.split(',')[1], 'base64'));
      posterBytes += fs.statSync(posterPath).size;
    }
    out.push({
      slug,
      name,
      duration: info.duration,
      bbox: info.union,
      boxRatios: {
        x0: +(info.union.x0 / 640).toFixed(4),
        x1: +(info.union.x1 / 640).toFixed(4),
        y0: +(info.union.y0 / 360).toFixed(4),
        y1: +(info.union.y1 / 360).toFixed(4),
      },
    });
    console.log(
      `  ${info.union.opaqueCorner === 0 ? '✓' : '✗'} ${slug.padEnd(16)} ${(info.duration || 0).toFixed(2)}s  ` +
        `bbox=[${info.union.x0},${info.union.y0}]-[${info.union.x1},${info.union.y1}]`,
    );
  }
  fs.writeFileSync(REPORT, JSON.stringify(out, null, 2));
  await browser.close();
  server.close();
  console.log(`\n素材 ${out.length} 段；透明通道正常 ${alphaOk}/${out.length}`);
  if (!checkOnly) console.log(`poster ${out.length} 张，合计 ${(posterBytes / 1024).toFixed(0)} KB → public/pet/poster/`);
  console.log(`报告：${REPORT}`);
  if (alphaOk !== out.length) process.exit(1);
}

main().catch((e) => {
  console.error('脚本异常:', e);
  process.exit(2);
});
