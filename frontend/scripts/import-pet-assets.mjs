/**
 * 把 dsh-pet 的动画素材导入本站，public/pet/webm/<slug>.webm
 *
 * 用法，在本目录 `frontend/` 下执行：
 *   node scripts/import-pet-assets.mjs # 用默认上游位置，$DSH_HOME/profiles/web/node_modules/dsh-pet
 *   node scripts/import-pet-assets.mjs --from <目录> # 指定上游 assets/webm 目录，或 dsh-pet 包根目录
 *   node scripts/import-pet-assets.mjs --prune # 同时删掉清单里已移除的旧文件
 *
 * 说明：
 *   - 素材是二进制、体积大，提交进仓库是为了「部署可复现」——服务器上不需要装 dsh-pet。
 *   - 上游更新素材后可重跑本脚本覆盖，内容变了 git 会显示改动，便于复核。
 *   - 只拷清单里的条目；上游新增动画想上站，先往 scripts/pet-assets.mjs 的 CURATED 里加。
 *   - 校验见 scripts/check-pet-assets.mjs，CI 与 check-all.ps1 都会跑。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CURATED, defaultSourceDir } from './pet-assets.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const DEST = path.join(ROOT, 'public', 'pet', 'webm');

function parseArgs(argv) {
  const out = { from: '', prune: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--from') out.from = argv[++i] || '';
    else if (a === '--prune') out.prune = true;
    else if (a === '--help' || a === '-h') out.help = true;
  }
  return out;
}

function resolveSource(input) {
  let dir = input || defaultSourceDir();
  // 允许传 dsh-pet 包根目录，自动补 assets/webm
  if (fs.existsSync(path.join(dir, 'assets', 'webm'))) dir = path.join(dir, 'assets', 'webm');
  return dir;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log('用法: node scripts/import-pet-assets.mjs [--from <上游 assets/webm 目录>] [--prune]');
    return;
  }
  const src = resolveSource(args.from);
  if (!fs.existsSync(src)) {
    console.error(`✗ 上游素材目录不存在：${src}`);
    console.error('  请确认已安装 dsh-pet，或用 --from 指定 assets/webm 的绝对路径。');
    process.exit(1);
  }
  fs.mkdirSync(DEST, { recursive: true });

  const missing = [];
  let copied = 0;
  let bytes = 0;
  for (const { slug, name } of CURATED) {
    const from = path.join(src, `${name}.webm`);
    if (!fs.existsSync(from)) {
      missing.push(`${name}.webm（slug=${slug}）`);
      continue;
    }
    const to = path.join(DEST, `${slug}.webm`);
    fs.copyFileSync(from, to);
    copied++;
    bytes += fs.statSync(to).size;
  }

  if (args.prune) {
    const keep = new Set(CURATED.map((a) => `${a.slug}.webm`));
    for (const f of fs.readdirSync(DEST)) {
      if (!keep.has(f)) {
        fs.rmSync(path.join(DEST, f));
        console.log(`- 删除清单外旧素材 ${f}`);
      }
    }
  }

  console.log(`✓ 导入 ${copied}/${CURATED.length} 段动画 → public/pet/webm（合计 ${(bytes / 1024 / 1024).toFixed(1)} MB）`);
  if (missing.length) {
    console.error(`✗ ${missing.length} 段在上游找不到：`);
    for (const m of missing) console.error(`   - ${m}`);
    process.exit(1);
  }
  console.log('下一步：node scripts/gen-pet-posters.mjs（重新生成 Safari 兜底静态图）');
}

main();
