/**
 * 桌宠动画目录，唯一事实来源
 *
 * 形象与动画来自开源项目 dsh-pet：https://github.com/PC2005-cloud/dsh-pet
 *   · 代码 MIT；动画 / 提示词 / 源视频「允许开源使用，禁止商用」
 *   · 本站是公益社区站，站内货币只是游戏数值，没有任何真实付费，属于开源使用
 *   · 按许可证要求署名：仓库根目录 NOTICE-dsh-pet.md + 宠物右键菜单「关于桌宠」
 *
 * 数据来源：上游 assets/config.jsonc 的 animations 段，idle / turn / drag / clicks /
 * moves / categories / events。素材是 640×360 画布上的 Q 版蓝发小女仆，全部 VP9-alpha
 * 透明视频，每段 10 秒；这里只挑了覆盖全部交互的 33 段，见 scripts/pet-assets.mjs。
 *
 * 改权重/加动画后不需要动别的：随机链、右键菜单、播放器全部读这份目录。
 */

/** 画布，素材原生尺寸，几何都以它为准*/
export const CANVAS = { w: 640, h: 360 };

/**
 * 人物在画布里的位置，比例——由素材实测得到，.audit-tmp/pet-assets-report.json：
 *   常见可见范围 x∈[196,440]、y∈[60,331]，脚底线 y≈330，画布底部留 30px 透明边。
 * 与上游 constants.ts 的 HIT_BOX，200,50 - 440,335 基本一致，这里换算成比例。
 */
export const BODY = {
  left: 0.3125, // 身体左缘，命中区左边界
  right: 0.6875, // 身体右缘
  top: 0.14, // 头顶，含头顶道具的常见上限
  feet: 0.9167, // 脚底线：站在这条线上
};

/** 命中区，点击 / 拖拽 / 右键只认这块*/
export const HIT = { x0: BODY.left, y0: BODY.top, x1: BODY.right, y1: 0.93 };

/** 上游 moves.minDist/maxDist 是「基准宠物宽 462px」下的像素，运行时按 实际宽/462 等比缩放 */
export const PET_REF_WIDTH = 462;

/* ---------------- 基础动画 ---------------- */
export const IDLE = ['idle-breathe'];
export const TURN = ['turn-look'];
export const DRAG = 'drag-hang';

/* ---------------- 点击回应，点一下随机抽一段 ----------------*/
export const CLICKS = ['click-happy', 'click-shy', 'click-tsun', 'click-tickle', 'click-wave'];

/* ---------------- 移动，会真的走一段 ----------------*/
export const MOVES = {
  default: { minDist: 60, maxDist: 240, margin: 20, leadSec: 2, tailSec: 2 },
  actions: [
    { slug: 'move-crab' },
    { slug: 'move-float', params: { minDist: 40, maxDist: 120 } },
  ],
};

/* ---------------- 随机动作分类 ---------------- */
export const CATEGORIES = [
  {
    id: '小动作',
    weight: 24,
    actions: ['act-hum', 'act-stretch', 'act-tap', 'act-squat', 'act-yawn', 'act-nap', 'act-curtsy', 'act-startle', 'act-code', 'act-mirror'],
  },
  { id: '玩耍', weight: 18, actions: ['fun-rubik', 'fun-bubbles', 'fun-violin', 'fun-whale', 'fun-cat'] },
  { id: '吃什么', weight: 8, actions: ['food-rice', 'food-hotpot', 'food-token'] },
  { id: '碎碎念', weight: 5, actions: ['whisper-wipe', 'whisper-daze', 'whisper-screen'] },
];

/** 顶层权重：idle + turn + move + 各分类 weight 必须等于 100，校验脚本会查*/
export const WEIGHTS = { idle: 25, turn: 8, move: 12 };

/* ---------------- 事件动画，不进随机链，由代码显式触发 ----------------*/
export const EVENTS = {
  whisper: ['whisper-wipe', 'whisper-daze', 'whisper-screen'],
  thinking: 'think-bubble',
  success: 'cheer',
  error: 'click-tsun',
};

/** slug → 中文名，右键菜单显示；也是上游素材的文件名，导入脚本据此对应*/
export const NAMES = {
  'idle-breathe': '待机呼吸',
  'turn-look': '东张西望',
  'drag-hang': '被拖拽悬空',
  'click-happy': '点击回应-开心跃动',
  'click-shy': '点击回应-害羞惊讶',
  'click-tsun': '点击回应-傲娇生气',
  'click-tickle': '点击回应-挠痒咯咯笑',
  'click-wave': '点击回应-元气挥手',
  'move-crab': '螃蟹走路',
  'move-float': '漂浮踏步',
  'act-hum': '悠闲哼歌',
  'act-stretch': '伸懒腰',
  'act-tap': '敲桌面',
  'act-squat': '下蹲',
  'act-yawn': '哈欠连天',
  'act-nap': '小憩',
  'act-curtsy': '屈膝礼',
  'act-startle': '被吓一跳',
  'act-code': '写代码',
  'act-mirror': '照镜子',
  'fun-rubik': '玩魔方',
  'fun-bubbles': '鲸鱼吐泡泡',
  'fun-violin': '小提琴演奏',
  'fun-whale': '蓝鲸出现',
  'fun-cat': '撸猫',
  'food-rice': '吃白饭',
  'food-hotpot': '涮火锅',
  'food-token': '吃 Token',
  'whisper-wipe': '碎碎念-擦桌子',
  'whisper-daze': '碎碎念-发呆',
  'whisper-screen': '碎碎念-对屏幕',
  'think-bubble': '工作状态-思考',
  cheer: '工作状态-庆祝',
};

/** 菜单/说明里显示的名字 */
export const nameOf = (slug) => NAMES[slug] || slug;

/** 素材地址，走 public/pet，不进 bundle；BASE_URL 保证部署在子路径也能用*/
const assetBase = () => {
  const base = (import.meta.env && import.meta.env.BASE_URL) || '/';
  return base.endsWith('/') ? base : `${base}/`;
};
export const webmUrl = (slug) => `${assetBase()}pet/webm/${slug}.webm`;
export const posterUrl = (slug) => `${assetBase()}pet/poster/${slug}.webp`;

/* ---------------- 随机选择 ---------------- */

/** 等概率抽一个，尽量避开 exclude；池子只有它自己时宁可重复也不返回空 */
export function pick(pool, exclude) {
  const src = exclude ? pool.filter((n) => n !== exclude) : pool;
  const use = src.length ? src : pool;
  return use[Math.floor(Math.random() * use.length)];
}

/** 按权重选一个分类，镜像过滤在 dsh-pet 用于文字类动画，这里没有文字素材，故不区分朝向*/
export function pickCategory() {
  const cats = CATEGORIES.filter((c) => c.actions.length > 0);
  const total = cats.reduce((s, c) => s + c.weight, 0) || 1;
  let t = Math.random() * total;
  for (const c of cats) {
    t -= c.weight;
    if (t <= 0) return c;
  }
  return cats[cats.length - 1];
}

/**
 * 掷一次骰子决定下一段动画属于哪一档。
 * roll ∈ [0,1：idle / turn / move 按权重切分，剩余概率给随机动作分类。
 */
export function rollKind(roll = Math.random()) {
  const { idle, turn, move } = WEIGHTS;
  if (roll < idle / 100) return 'idle';
  if (roll < (idle + turn) / 100) return 'turn';
  if (roll < (idle + turn + move) / 100) return 'move';
  return 'action';
}

/**
 * 随机链的下一段动画，纯函数，方便单测/排查。
 * 返回 { kind, slug }；kind==='move' 时调用方负责算移动几何，planMove，失败要退回 'action'。
 */
export function pickNext(current) {
  const kind = rollKind();
  if (kind === 'idle') return { kind, slug: pick(IDLE, current) };
  if (kind === 'turn') return { kind, slug: pick(TURN, current) };
  if (kind === 'move') {
    const act = MOVES.actions[Math.floor(Math.random() * MOVES.actions.length)];
    return { kind, slug: act.slug, params: { ...MOVES.default, ...(act.params || {}) } };
  }
  const cat = pickCategory();
  return { kind, slug: pick(cat.actions, current), category: cat.id };
}
