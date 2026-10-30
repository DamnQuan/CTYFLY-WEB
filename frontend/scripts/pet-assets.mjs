/**
 * 桌宠素材清单，给导入/校验脚本用
 *
 * 单一事实来源是 src/deskpet/catalog.js 的 NAMES，slug → 上游中文文件名；
 * 本文件只把它翻译成脚本需要的 { slug, name } 列表，避免两处维护两份中文名。
 *
 * 素材来源：开源项目 dsh-pet，https://github.com/PC2005-cloud/dsh-pet。
 * 代码 MIT；动画 / 提示词 / 源视频「允许开源使用、禁止商用」——本站为公益社区站，
 * 非商业用途，并按许可证要求署名，仓库根目录 NOTICE-dsh-pet.md。
 */
import { NAMES } from '../src/deskpet/catalog.js';

/** 上站的全部动画，slug ↔ dsh-pet assets/webm 里的中文文件名*/
export const CURATED = Object.entries(NAMES).map(([slug, name]) => ({ slug, name }));

/** 上游包内素材目录的默认位置，可用 --from 覆盖*/
export function defaultSourceDir() {
  const home = process.env.DSH_HOME || `${process.env.USERPROFILE || process.env.HOME}/.dsh`;
  return `${home}/profiles/web/node_modules/dsh-pet/assets/webm`;
}
