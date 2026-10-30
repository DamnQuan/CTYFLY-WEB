/**
 * 桌宠素材一致性校验，纯 Node，CI 与 check-all.ps1 都会跑
 *
 * 查四件事，任何一件不对都算失败：
 *   1. 权重封闭：WEIGHTS idle+turn+move + 各分类 weight 之和必须正好 100
 *      随机链按 /100 切概率，和不等于 100 时「action」档的概率就错了
 *   2. 引用封闭：目录里引用到的每个 slug，idle/turn/drag/clicks/moves/分类/事件
 *      必须都在 NAMES 里有中文名 —— 没有=菜单显示不出来、导入脚本也找不到素材
 *   3. 文件齐全：public/pet/webm/<slug>.webm 与 public/pet/poster/<slug>.webp 都存在
 *   4. 没有孤儿：public/pet/webm 里不存在 NAMES 之外的文件，忘了从 NAMES 删
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  CATEGORIES,
  CLICKS,
  DRAG,
  EVENTS,
  IDLE,
  MOVES,
  NAMES,
  TURN,
  WEIGHTS,
  nameOf,
} from '../src/deskpet/catalog.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const WEBM = path.join(ROOT, 'public', 'pet', 'webm');
const POSTER = path.join(ROOT, 'public', 'pet', 'poster');

const errors = [];
const bad = (msg) => errors.push(msg);

/* 1. 权重封闭 */
const top = WEIGHTS.idle + WEIGHTS.turn + WEIGHTS.move;
const catSum = CATEGORIES.reduce((s, c) => s + c.weight, 0);
if (top + catSum !== 100) {
  bad(`权重和不等于 100：idle+turn+move=${top}，分类合计=${catSum}，总=${top + catSum}`);
}
for (const c of CATEGORIES) {
  if (c.weight <= 0) bad(`分类「${c.id}」weight 必须为正，现在是 ${c.weight}`);
  if (!c.actions.length) bad(`分类「${c.id}」没有任何动画`);
}

/* 2. 引用封闭 */
const used = [
  ...IDLE,
  ...TURN,
  DRAG,
  ...CLICKS,
  ...MOVES.actions.map((a) => a.slug),
  ...CATEGORIES.flatMap((c) => c.actions),
  ...EVENTS.whisper,
  EVENTS.thinking,
  EVENTS.success,
  EVENTS.error,
];
for (const slug of used) {
  if (!NAMES[slug]) bad(`动画「${slug}」被引用但没有中文名（NAMES）`);
}
const referenced = new Set(used);
for (const slug of Object.keys(NAMES)) {
  if (!referenced.has(slug)) bad(`NAMES 里的「${slug}（${nameOf(slug)}）」没有被任何池引用（要么删掉，要么挂进某个池）`);
}

/* 3. 文件齐全 */
let webmBytes = 0;
for (const slug of Object.keys(NAMES)) {
  const w = path.join(WEBM, `${slug}.webm`);
  if (!fs.existsSync(w)) bad(`缺动画文件 public/pet/webm/${slug}.webm`);
  else webmBytes += fs.statSync(w).size;
  const p = path.join(POSTER, `${slug}.webp`);
  if (!fs.existsSync(p)) bad(`缺静态立绘 public/pet/poster/${slug}.webp`);
}

/* 4. 没有孤儿 */
if (fs.existsSync(WEBM)) {
  const known = new Set(Object.keys(NAMES).map((s) => `${s}.webm`));
  for (const f of fs.readdirSync(WEBM)) {
    if (!known.has(f)) bad(`public/pet/webm/${f} 不在 NAMES 里（孤儿文件，用 --prune 导入脚本清掉或补进 NAMES）`);
  }
}
if (fs.existsSync(POSTER)) {
  const known = new Set(Object.keys(NAMES).map((s) => `${s}.webp`));
  for (const f of fs.readdirSync(POSTER)) {
    if (!known.has(f)) bad(`public/pet/poster/${f} 不在 NAMES 里（孤儿文件）`);
  }
}

/* 汇总 */
const count = Object.keys(NAMES).length;
if (errors.length) {
  console.error(`✗ 桌宠素材校验未通过（${errors.length} 处）：`);
  for (const e of errors) console.error(`   - ${e}`);
  process.exit(1);
}
console.log(`✓ 桌宠素材校验通过：${count} 段动画，${(webmBytes / 1024 / 1024).toFixed(1)} MB，权重和=100，无孤儿文件`);
