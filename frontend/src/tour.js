/**
 * 新手引导的步骤定义与完成状态。
 *
 * 两种步骤：
 *   action: 'click' —— 交互式：高亮处挖开一个可点击的洞，用户真的点下去才进下一步。
 *                      点击会真的展开菜单、跳转页面，边做边学。
 *   action: 'read'，默认—— 只需要看，点「下一步」继续。
 *
 * 定位用「可见文案 + scope」而不是写死选择器：
 *   侧边栏一级菜单是会展开的按钮，.side-group-toggle，二级是链接，.side-sublink，
 *   两者文案可能重名，比如「连飞活动」，所以必须用 scope 区分。
 *   找不到或不可见时组件会自动降级成居中卡片，流程不会中断。
 */
import { ref } from 'vue';

const KEY = 'ctyfly_tour_v1';

function read() {
  try {
    return localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
}

export const tourDone = ref(read());

export function finishTour() {
  tourDone.value = true;
  try { localStorage.setItem(KEY, '1'); } catch { /* 忽略 */ }
}

export function restartTour() {
  tourDone.value = false;
  try { localStorage.removeItem(KEY); } catch { /* 忽略 */ }
}

const GROUP = { scope: '.side-group-toggle' };   // 一级菜单，点开展开
const SUB = { scope: '.side-sublink' };          // 二级菜单，点了跳转
const LINK = { scope: '.side-link' };            // 一级直达链接

/**
 * @param {{isStaff: boolean}} ctx 按身份裁剪步骤，普通用户看不到管理后台那一步
 */
export function buildSteps(ctx = {}) {
  const steps = [
    {
      title: '欢迎来到 CTYFLY',
      body: '跟着点几下就认全了。每一步高亮的地方都可以直接点，点了才会往下走；不想看随时点「跳过」。',
      target: null,
    },
    {
      title: '所有功能都在左侧边栏',
      body: '左边是一级菜单，带箭头的点一下会展开二级菜单。手机端在左上角按钮里打开这个抽屉。',
      target: { selector: '.sidebar-logo' },
    },
    {
      title: '动手试试：展开「航情查询」',
      body: '点一下高亮的这一项，二级菜单会展开。',
      target: { text: '航情查询', ...GROUP },
      action: 'click',
    },
    {
      title: '现在点进「METAR 报文查询」',
      body: '点它会进入航情查询页面 —— 这是查机场实时天气最快的地方。',
      target: { text: 'METAR 报文查询', ...SUB },
      action: 'click',
    },
    {
      title: '航情查询一共三页',
      body: 'METAR 报文查询，实时天气、TAF 报文查询，未来预报、航路查询，自动规划航路，基于 AIRAC 导航数据，不用手抄。',
      target: { text: '航情查询', ...GROUP },
    },
    {
      title: '动手试试：看看「连飞活动」',
      body: '点一下展开，里面有当前活动和你的历史报名。',
      target: { text: '连飞活动', ...GROUP },
      action: 'click',
    },
    {
      title: '点进「连飞活动」报名',
      body: '进入活动页后可以看详情并报名，报名记录会出现在仪表盘。',
      target: { text: '连飞活动', ...SUB },
      action: 'click',
    },
    {
      title: '申请中心',
      body: '想当管制员或加入运营团队，在这里提交申请；提交后本页能看到审核进度和审核意见。点一下展开看看。',
      target: { text: '申请中心', ...GROUP },
      action: 'click',
    },
    {
      title: '虚拟航司',
      body: '浏览各家航司、看排行榜，也能申请加入或自己开一家，航司 CEO 还能定制对外主页。',
      target: { text: '虚拟航司', ...GROUP },
    },
    {
      title: '钱包与虚拟商城',
      body: '飞行工资会进「我的钱包」，拿去「虚拟商城」换称号和徽章，会显示在你的用户名旁边。',
      target: { text: '虚拟商城', ...LINK },
    },
    {
      title: '工单中心',
      body: '遇到任何问题——账号、权限、报错——都在这里提工单。点一下展开。',
      target: { text: '工单中心', ...GROUP },
      action: 'click',
    },
    {
      title: '顶栏：时区与主题',
      body: '右上角切换时钟时区，UTC / 北京时间和页面主题，AUTO 跟随系统 / 浅色 / 深色。',
      target: { selector: '.topbar' },
    },
    {
      title: '动手试试：戳一下鲸宝',
      body: '右下角这只鲸宝会跟着你的鼠标看、能拖着玩、闲着会打瞌睡。点它一下试试，气泡里还能打字跟它聊天。不想要就在个人中心收起。',
      target: { selector: '.deskpet' },
      action: 'click',
    },
    {
      title: '个人中心',
      body: '最后一步：点进个人中心，可以改用户名、QQ、头像和密码，也能开关鲸宝、切换它的落地/悬停模式，以及重播这份引导。',
      target: { text: '个人中心', ...LINK },
      action: 'click',
    },
    {
      title: '准备好了',
      body: '就这些。祝飞行愉快 —— 之后有不懂的，随时点右下角的鲸宝问它。',
      target: null,
    },
  ];

  if (ctx.isStaff) {
    steps.splice(11, 0, {
      title: '管理后台',
      body: '职员专属：数据概览、用户与权限管理、审批中心、申请审核、活动与公告管理、商城管理，以及登录/注册/网络/审计四类日志。',
      target: { text: '管理后台', ...GROUP },
      action: 'click',
    });
  }

  return steps;
}
