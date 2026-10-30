/**
 * 鲸宝的对话内容
 *
 * 设计取舍：不接大模型 —— 预设台词 + 关键词应答，零成本、零延迟、
 * 不依赖任何外部服务，也不会被拿来生成违规内容。
 *
 * 台词分两类：
 *   1. 情境台词，talk：按触发时机取，比如被点、被拖、睡醒、页面不同；
 *   2. 关键词应答，reply：用户在输入框里打字，按关键词命中回复。
 *
 * 注意：项目规则是「不使用 emoji」，所以台词里不放任何表情符号。
 */

/** 简单变量替换：{name} 用户名、{cid} CID、{rank} 飞行员等级 */
function fill(text, ctx) {
  return text
    .replace(/\{name\}/g, ctx.name || '飞行员')
    .replace(/\{cid\}/g, ctx.cid || '----')
    .replace(/\{rank\}/g, ctx.rank || '学员');
}

/** 按当前小时给出问候语 */
export function greeting(ctx) {
  const h = new Date().getHours();
  let text;
  if (h >= 5 && h < 10) text = '{name} 早啊，今天的天气适合飞一圈。';
  else if (h >= 10 && h < 12) text = '{name}，上午巡场辛苦了。';
  else if (h >= 12 && h < 14) text = '中午了 {name}，别忘了吃饭。';
  else if (h >= 14 && h < 18) text = '{name}，下午的航路查过了吗？';
  else if (h >= 18 && h < 23) text = '晚上好 {name}，今晚有连飞活动吗？';
  else text = '这么晚还在飞？{name} 注意休息。';
  return fill(text, ctx);
}

const POOLS = {
  click: [
    '别戳我，痒。',
    '我在呢。',
    '{name}，需要我帮你看 METAR 吗？',
    '今天已经飞了几班了？',
    '呼号 {cid}，随时待命。',
    '我在这儿看着你的航路呢。',
    '戳我是没用的，除非你想聊天。',
    '嗯？有事找我？',
  ],
  drag: ['起飞了？', '唔……别晃我。', '我要晕机了。', '轻点儿，我不是行李。'],
  drop: ['落地，三点姿态。', '安全着陆。', '这一下有点重。'],
  dropHover: ['就停这儿吧。', '这里视野不错。', '悬着也挺舒服的。'],
  sleep: ['我先眯一会儿……', '没人理我，那我睡了啊。'],
  wake: ['嗯？我没睡，我在想航路。', '醒了醒了。'],
  idle: [
    '有点无聊，给我找个活动报名吧。',
    '你的钱包里还有多少飞行工资？',
    '听说航司排行榜又变了。',
    '{rank} 大大，带带我。',
    '今天的风挺顺的。',
    '航路查询能自动规划，比手抄快多了。',
  ],
  hoverOn: ['好嘞，我就悬在这儿不动了。'],
  hoverOff: ['那我乖乖落地。'],
  say: ['嗯，你说。', '我听着呢。'],
};

/** 取一条情境台词。避免与上一条重复。 */
let lastText = '';
export function talk(key, ctx = {}) {
  const pool = POOLS[key];
  if (!pool || !pool.length) return '';
  if (pool.length === 1) {
    lastText = pool[0];
    return fill(pool[0], ctx);
  }
  let text = pool[Math.floor(Math.random() * pool.length)];
  let guard = 0;
  while (text === lastText && guard++ < 8) {
    text = pool[Math.floor(Math.random() * pool.length)];
  }
  lastText = text;
  return fill(text, ctx);
}

/** 关键词应答：命中即回复，未命中走兜底 */
const RULES = [
  { re: /(你好|您好|hi|hello|在吗|在不在)/i, a: ['在的，{name}。有什么想问的？', '你好呀，我一直在。'] },
  { re: /(你是谁|叫什么|名字|自我介绍)/, a: ['我是鲸宝，CTYFLY 的桌面小鲸灵。', '我叫鲸宝，平时就在这儿游着。'] },
  { re: /(metar|taf|天气|报文|航情)/i, a: ['航情查询里有 METAR 和 TAF，要不要一起去看看？', '查报文记得看时间，别拿旧报做计划。'] },
  { re: /(航路|航线|规划|route)/i, a: ['航路查询能自动规划，比手抄快多了。', '填出发和到达机场，剩下的交给航路查询。'] },
  { re: /(活动|连飞|报名)/, a: ['连飞活动页有新活动的话记得报名。', '报名之后在仪表盘能看到自己报的活动。'] },
  { re: /(工资|钱包|钱|余额)/, a: ['飞行工资在钱包里，可以拿去商城换称号。', '多飞几班工资就上去了。'] },
  { re: /(商城|称号|徽章|购买)/, a: ['商城里的称号和徽章能挂在名字旁边，挺好看的。', '看中哪个了？攒够工资就能换。'] },
  { re: /(工单|客服|投诉|反馈|问题)/, a: ['有问题去工单中心提，管理员会看的。', '提交工单后在这里能看到进度。'] },
  { re: /(航司|ceo|跳槽)/i, a: ['航司列表里可以申请加入，也能自己开一家。', '跳槽要走审批，想清楚再提。'] },
  { re: /(管制|管管|放行|塔台)/, a: ['想当管制员的话，去申请中心提交管制申请。', '管制等级要一级一级考上去。'] },
  { re: /(隐私|数据|信息|cookie)/i, a: ['页脚有隐私政策和 Cookie 政策，写得很细。', '你的数据怎么用，隐私政策里都写了。'] },
  { re: /(谢谢|感谢|多谢|thanks|thank)/i, a: ['不客气，随时叫我。', '应该的。'] },
  { re: /(再见|拜拜|走了|bye)/i, a: ['下次再聊，我先飘一会儿。', '去吧，我在这儿等你。'] },
  { re: /(累|困|睡|休息)/, a: ['那我也陪你眯一会儿。', '累了就歇会儿，飞机也要检修的。'] },
  { re: /(管理员|admin|管理团队)/i, a: ['管理后台的事情我可管不了，得找管理团队。', '有事找管理员的话，走工单最快。'] },
  { re: /(可爱|好看|喜欢|真棒)/, a: ['嘿嘿，被夸到了。', '你也很棒，{name}。'] },
  { re: /(笨|丑|讨厌|滚)/, a: ['……我当没听见。', '好吧，那我安静一会儿。'] },
];

const FALLBACK = [
  '嗯……这个我还没学会，要不换个说法？',
  '我只是一条小鲸鱼，懂得不多，但我会听。',
  '记下了。还有什么想说的？',
  '这个我答不上来，不过航情和航路的问题可以问我。',
];

export function reply(input, ctx = {}) {
  const text = String(input || '').trim();
  if (!text) return talk('say', ctx);
  for (const rule of RULES) {
    if (rule.re.test(text)) {
      return fill(rule.a[Math.floor(Math.random() * rule.a.length)], ctx);
    }
  }
  return fill(FALLBACK[Math.floor(Math.random() * FALLBACK.length)], ctx);
}
