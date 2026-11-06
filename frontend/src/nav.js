/**
 * 主导航数据，侧边栏与顶部栏共用，唯一事实来源
 *
 * 之前这套定义写在 Sidebar.vue 里；顶部栏模式，2026-10-06 要在顶部横排同一套菜单，
 * 且二级项要「分列展示带图标和说明」，所以抽成模块，两个组件都从这里取，
 * 避免出现两份定义漂移。
 *
 * 字段约定：
 *   to 路由地址，有 children 的一级项没有 to，只作为分组
 *   label 名称
 *   icon 图标名，见 components/Icon.vue
 *   desc 顶部栏面板里的说明，一级项面板标题 + 二级项卡片说明都用它
 *   children 二级项；子项同样可带 icon/desc
 *   member 仅已加入航司的成员可见，后端 /api/airlines/my/membership
 *   cap 需要对应能力，与后端 permissions.ADMIN_NODES 一一对应
 *   manage 仅 CEO / 部长可见，管理中心直达
 */
import { computed } from 'vue';
import { useAuthStore } from './stores/auth.js';
import { useVaStore } from './stores/va.js';
import acisLogo from './assets/acis-glyph-160.webp';

export { acisLogo };

export function useNavItems() {
  const auth = useAuthStore();
  const va = useVaStore();

  const navItems = computed(() => {
    const items = [
      { to: '/home', label: '仪表盘', icon: 'grid', desc: '我的飞行数据与今日动态' },
      {
        label: '航情查询',
        icon: 'radar',
        desc: 'METAR / TAF 报文、航路规划与机场地面图',
        children: [
          { to: '/weather/metar', label: 'METAR 报文查询', icon: 'radar', desc: '机场实时天气报文' },
          { to: '/weather/taf', label: 'TAF 报文查询', icon: 'calendar', desc: '未来 24–30 小时机场预报' },
          { to: '/weather/routes', label: '航路查询', icon: 'trending', desc: '按 AIRAC 数据自动规划航路' },
          { to: '/nav/airport-map', label: '机场地面图', icon: 'globe', desc: '全球机场地面图与跑道' },
        ],
      },
      {
        label: '连飞活动',
        icon: 'calendar',
        desc: '连飞活动报名与我的历史记录',
        children: [
          { to: '/events', label: '连飞活动', icon: 'calendar', desc: '近期活动、席位与报名' },
          { to: '/events/history', label: '历史报名', icon: 'file', desc: '我参加过的活动记录' },
        ],
      },
      {
        label: '申请中心',
        icon: 'briefcase',
        desc: '管制员申请与职员申请',
        children: [
          { to: '/apply/controller', label: '管制员申请', icon: 'headphones', desc: '申请成为管制员' },
          { to: '/apply/staff', label: '职员申请', icon: 'briefcase', desc: '加入站点运营团队' },
        ],
      },
      {
        label: '虚拟航司',
        icon: 'plane',
        desc: '航司、机队、签派与薪酬',
        children: [
          { to: '/airlines', label: '航司列表', icon: 'plane', desc: '浏览各家虚拟航司' },
          { to: '/va/routes', label: '航线列表', icon: 'trending', desc: '本航司航线网络', member: true },
          { to: '/va/fleet', label: '机队管理', icon: 'wings', desc: '购置与管理飞机', member: true },
          { to: '/va/dispatch', label: '飞行签派', icon: 'bolt', desc: '生成放行单与油量', member: true },
          { to: '/va/pirep', label: '提交飞行报告', icon: 'file', desc: '提交报告并核算工资', member: true },
          { to: '/va/shop', label: '航司商城', icon: 'shop', desc: '航司专属兑换', member: true },
          { to: '/shop', label: '公共商城', icon: 'shop', desc: '全站徽章与称号', member: true },
          { to: '/airlines/leaderboard', label: '排行榜', icon: 'award', desc: '航司与飞行员排行' },
          { to: '/wallet', label: '我的钱包', icon: 'diamond', desc: '余额与收入明细' },
        ],
      },
      {
        label: '飞行生涯',
        icon: 'award',
        desc: '竞标、二手市场、成就与事故记录',
        children: [
          { to: '/bids', label: '航线竞标', icon: 'key', desc: '竞价获取航线，中标入网', member: true },
          { to: '/market', label: '二手飞机市场', icon: 'shop', desc: '航司之间整机转让', member: true },
          { to: '/achievements', label: '成就徽章', icon: 'award', desc: '里程碑徽章与奖励' },
          { to: '/incidents', label: '事故记录', icon: 'shield', desc: '事故上报与调查跟踪' },
        ],
      },
      {
        label: '工单中心',
        icon: 'ticket',
        desc: '问题反馈与处理进度',
        children: [
          { to: '/tickets/new', label: '提交工单', icon: 'plus', desc: '遇到问题在这里找我们' },
          { to: '/tickets', label: '工单历史', icon: 'ticket', desc: '查看处理进度与回复' },
        ],
      },
      { to: '/partners', label: '合作伙伴', icon: 'link', desc: '合作单位与友人站点' },
      { to: '/acis', label: 'ACIS 事件检索', icon: 'book', image: acisLogo, desc: '飞圈事件智能检索与论坛' },
      {
        label: '管理后台',
        icon: 'shield',
        desc: '站点运营与审核，按能力显示',
        admin: true,
        // 每个节点声明所需能力，与后端 permissions.ADMIN_NODES 一一对应。
        // 能力来自 role 分支 ∪ rating 分支，普通用户两者皆空 → 整个管理后台不显示。
        children: [
          { to: '/admin/stats', label: '数据概览', icon: 'grid', desc: '站点核心指标', cap: 'view_stats' },
          { to: '/admin/users', label: '用户管理', icon: 'users', desc: '账号与管制等级', cap: 'view_users' },
          { to: '/admin/permissions', label: '权限管理', icon: 'key', desc: '角色能力矩阵', cap: 'manage_permissions' },
          { to: '/admin/approvals', label: '审批中心', icon: 'check', desc: '敏感操作双人复核', cap: 'approve_sensitive' },
          { to: '/admin/applications/controller', label: '管制申请', icon: 'headphones', desc: '审核管制员申请', cap: 'review_applications' },
          { to: '/admin/applications/staff', label: '职员申请', icon: 'briefcase', desc: '审核职员申请，含面试', cap: 'review_applications' },
          { to: '/admin/airlines', label: '航司审核', icon: 'plane', desc: '虚拟航司建司审核', cap: 'review_airlines' },
          { to: '/admin/events', label: '活动管理', icon: 'calendar', desc: '连飞活动与管制席位', cap: 'manage_events' },
          { to: '/admin/archive', label: 'ACIS 管理', icon: 'book', desc: '投稿审核、纠错与事件发布', cap: 'manage_archive' },
          { to: '/admin/tickets', label: '工单管理', icon: 'ticket', desc: '处理用户工单', cap: 'manage_tickets' },
          { to: '/admin/notices', label: '公告管理', icon: 'megaphone', desc: '发布站内公告', cap: 'manage_notices' },
          { to: '/admin/partners', label: '合作伙伴', icon: 'link', desc: '首页合作展示位', cap: 'manage_notices' },
          { to: '/admin/shop', label: '商城管理', icon: 'shop', desc: '公共商城商品', cap: 'manage_shop' },
          { to: '/admin/logs-login', label: '登录日志', icon: 'file', desc: '登录记录与异常', cap: 'view_logs' },
          { to: '/admin/logs-register', label: '注册日志', icon: 'file', desc: '注册来源与脚本识别', cap: 'view_logs' },
          { to: '/admin/logs-network', label: '网络日志', icon: 'globe', desc: 'API 访问溯源', cap: 'view_logs' },
          { to: '/admin/logs-audit', label: '审计日志', icon: 'shield', desc: '管理操作留痕', cap: 'view_logs' },
          { to: '/admin/banned-ips', label: 'IP 黑名单', icon: 'radar', desc: '脚本封禁与白名单', cap: 'view_logs' },
          { to: '/admin/airline-funds', label: '航司货币', icon: 'trending', desc: '余额发放与扣除', cap: 'manage_airline_funds' },
          { to: '/admin/surveys', label: '问卷反馈', icon: 'message', desc: '平台发展问卷与建议', cap: 'view_surveys' },
        ],
      },
    ];
    // 管理中心直达：CEO / 部长可见，跳到自己航司的管理中心
    if (va.joined && (va.isCEO || va.membership?.minister)) {
      const g = items.find((i) => i.label === '虚拟航司');
      if (g) {
        g.children.push({
          to: `/airlines/${va.membership.airlineId}`, label: '管理中心', icon: 'key',
          desc: 'CEO / 部长管理入口', manage: true,
        });
      }
    }
    return items;
  });

  /** 当前用户实际能看到的下级节点 */
  function visibleChildren(item) {
    return (item.children || []).filter((c) => {
      if (c.cap && !auth.can(c.cap)) return false;
      if (c.member && !va.joined) return false;
      if (c.manage && !(va.isCEO || va.membership?.minister)) return false;
      return true;
    });
  }

  /** 顶层项是否可见，管理后台要求有任一子项能力*/
  function visibleTop(item) {
    if (!item.admin) return true;
    return auth.isStaff && visibleChildren(item).length > 0;
  }

  const mainItems = computed(() => navItems.value.filter(visibleTop));

  return { navItems, mainItems, visibleChildren };
}
