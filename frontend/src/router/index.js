import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '../stores/auth.js';
import { isChunkLoadError, markAppHealthy, recoverFromStaleChunk } from '../recover.js';
import { recordDiagEvent, showDiagPanel } from '../diag.js';
import { showToast } from '../utils.js';

const routes = [
  { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
  { path: '/partners', name: 'partners', component: () => import('../views/PartnersView.vue') },
  { path: '/acis', name: 'acis', component: () => import('../views/AcisView.vue') },
  { path: '/acis/submit', name: 'acis-submit', component: () => import('../views/AcisSubmitView.vue') },
  { path: '/acis/:id(\\d+)', name: 'acis-detail', component: () => import('../views/ArchiveDetailView.vue'), meta: { acis: true } },
  { path: '/archive', name: 'archive', component: () => import('../views/ArchiveView.vue') },
  { path: '/archive/submit', name: 'archive-submit', component: () => import('../views/ArchiveSubmitView.vue'), meta: { auth: true } },
  { path: '/archive/mine', name: 'archive-mine', component: () => import('../views/ArchiveMineView.vue'), meta: { auth: true } },
  { path: '/archive/:id(\\d+)', name: 'archive-detail', component: () => import('../views/ArchiveDetailView.vue') },
  { path: '/cookies', name: 'cookies', component: () => import('../views/CookiePolicyView.vue') },
  { path: '/privacy', name: 'privacy', component: () => import('../views/PrivacyPolicyView.vue') },
  { path: '/terms', name: 'terms', component: () => import('../views/TermsView.vue') },
  { path: '/about', name: 'about', component: () => import('../views/AboutView.vue') },
  { path: '/docs', name: 'survey', component: () => import('../views/SurveyView.vue') },
  { path: '/status', name: 'status', component: () => import('../views/StatusView.vue') },
  { path: '/changelog', name: 'changelog', component: () => import('../views/ChangelogView.vue') },
  { path: '/va/:icao', name: 'public-airline', component: () => import('../views/PublicAirlineView.vue') },
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { guest: true } },
  { path: '/register', name: 'register', component: () => import('../views/RegisterView.vue'), meta: { guest: true } },
  { path: '/forgot', name: 'forgot', component: () => import('../views/ForgotView.vue'), meta: { guest: true } },
  { path: '/home', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { auth: true } },
  { path: '/dashboard', redirect: '/home' },
  { path: '/weather', redirect: '/weather/metar' },
  { path: '/weather/metar', name: 'weather-metar', component: () => import('../views/WeatherMetarView.vue'), meta: { auth: true } },
  { path: '/weather/taf', name: 'weather-taf', component: () => import('../views/WeatherTafView.vue'), meta: { auth: true } },
  { path: '/weather/routes', name: 'weather-routes', component: () => import('../views/WeatherRoutesView.vue'), meta: { auth: true } },
  { path: '/nav/airport-map', name: 'nav-airport-map', component: () => import('../views/AirportMapView.vue'), meta: { auth: true } },
  { path: '/events', name: 'events', component: () => import('../views/EventsView.vue'), meta: { auth: true } },
  { path: '/events/history', name: 'events-history', component: () => import('../views/EventsHistoryView.vue'), meta: { auth: true } },
  { path: '/events/:id/briefing', name: 'event-briefing', component: () => import('../views/EventBriefingView.vue'), meta: { auth: true } },
  { path: '/airlines', name: 'airlines', component: () => import('../views/AirlinesView.vue'), meta: { auth: true } },
  { path: '/airlines/leaderboard', name: 'airline-leaderboard', component: () => import('../views/AirlineLeaderboardView.vue'), meta: { auth: true } },
  { path: '/airlines/:id', name: 'airline-detail', component: () => import('../views/AirlineDetailView.vue'), meta: { auth: true } },
  { path: '/va/routes', name: 'va-routes', component: () => import('../views/VaRoutesView.vue'), meta: { auth: true } },
  { path: '/va/fleet', name: 'va-fleet', component: () => import('../views/VaFleetView.vue'), meta: { auth: true } },
  { path: '/va/shop', name: 'va-shop', component: () => import('../views/VaShopView.vue'), meta: { auth: true } },
  { path: '/va/dispatch', name: 'va-dispatch', component: () => import('../views/VaDispatchView.vue'), meta: { auth: true } },
  { path: '/va/pirep', name: 'va-pirep', component: () => import('../views/VaPirepView.vue'), meta: { auth: true } },
  { path: '/wallet', name: 'wallet', component: () => import('../views/WalletView.vue'), meta: { auth: true } },
  { path: '/shop', name: 'shop', component: () => import('../views/ShopView.vue'), meta: { auth: true } },
  { path: '/bids', name: 'bids', component: () => import('../views/BiddingView.vue'), meta: { auth: true } },
  { path: '/market', name: 'market', component: () => import('../views/MarketView.vue'), meta: { auth: true } },
  { path: '/achievements', name: 'achievements', component: () => import('../views/AchievementsView.vue'), meta: { auth: true } },
  { path: '/incidents', name: 'incidents', component: () => import('../views/IncidentsView.vue'), meta: { auth: true } },
  { path: '/apply', redirect: '/apply/controller' },
  { path: '/apply/controller', name: 'apply-controller', component: () => import('../views/ApplyView.vue'), meta: { auth: true, tab: 'controller' } },
  { path: '/apply/staff', name: 'apply-staff', component: () => import('../views/ApplyView.vue'), meta: { auth: true, tab: 'staff' } },
  { path: '/tickets', name: 'tickets', component: () => import('../views/TicketsView.vue'), meta: { auth: true } },
  { path: '/tickets/new', name: 'tickets-new', component: () => import('../views/TicketsView.vue'), meta: { auth: true } },
  { path: '/profile', name: 'profile', component: () => import('../views/ProfileView.vue'), meta: { auth: true } },
  { path: '/admin', redirect: '/admin/stats' },
  { path: '/admin/stats', name: 'admin-stats', component: () => import('../views/admin/AdminStatsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/users', name: 'admin-users', component: () => import('../views/admin/AdminUsersView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/permissions', name: 'admin-permissions', component: () => import('../views/admin/AdminPermissionsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/approvals', name: 'admin-approvals', component: () => import('../views/admin/AdminApprovalsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/applications/:type(controller|staff)', name: 'admin-applications', component: () => import('../views/admin/AdminApplicationsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/airlines', name: 'admin-airlines', component: () => import('../views/admin/AdminAirlinesView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/events', name: 'admin-events', component: () => import('../views/admin/AdminEventsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/archive', name: 'admin-archive', component: () => import('../views/admin/AdminArchiveView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/archive/review/:type(submission|correction|event)/:id(\\d+)', name: 'admin-archive-review', component: () => import('../views/admin/AdminArchiveReviewView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/tickets', name: 'admin-tickets', component: () => import('../views/admin/AdminTicketsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/notices', name: 'admin-notices', component: () => import('../views/admin/AdminNoticesView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/partners', name: 'admin-partners', component: () => import('../views/admin/AdminPartnersView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/shop', name: 'admin-shop', component: () => import('../views/admin/AdminShopView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/logs-login', name: 'admin-logs-login', component: () => import('../views/admin/AdminLogsView.vue'), meta: { auth: true, admin: true, logKind: 'login' } },
  { path: '/admin/logs-register', name: 'admin-logs-register', component: () => import('../views/admin/AdminLogsView.vue'), meta: { auth: true, admin: true, logKind: 'register' } },
  { path: '/admin/logs-network', name: 'admin-logs-network', component: () => import('../views/admin/AdminLogsView.vue'), meta: { auth: true, admin: true, logKind: 'network' } },
  { path: '/admin/logs-audit', name: 'admin-logs-audit', component: () => import('../views/admin/AdminLogsView.vue'), meta: { auth: true, admin: true, logKind: 'audit' } },
  { path: '/admin/banned-ips', name: 'admin-banned-ips', component: () => import('../views/admin/AdminBannedIpsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/airline-funds', name: 'admin-airline-funds', component: () => import('../views/admin/AdminAirlineFundsView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/surveys', name: 'admin-surveys', component: () => import('../views/admin/AdminSurveysView.vue'), meta: { auth: true, admin: true } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
];

/* 页面懒加载限时。
 * 挂起的 import，服务端重启留下的半开连接、代理卡住等不会报错、只会一直等，
 * 导航就永远停在半路——表现为「顶栏时钟还在走，但整个页面点不动」。
 * 超时后按 chunk 失效处理，由 onError 自动整页恢复。*/
const PAGE_TIMEOUT = 10000;
const page = (loader) => () => Promise.race([
  loader(),
  new Promise((_, reject) =>
    setTimeout(() => reject(new Error('Failed to fetch dynamically imported module: timeout')), PAGE_TIMEOUT)),
]);

// 给所有懒加载页面套上超时保护
for (const r of routes) {
  if (typeof r.component === 'function') r.component = page(r.component);
}

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

/* 导航看门狗：一次导航若超过时限仍未完成，无论卡在哪个环节，强制整页恢复*/
let navWatchdog = null;
let navTarget = '';

function armWatchdog(to) {
  navTarget = to?.fullPath || window.location.pathname + window.location.search;
  clearTimeout(navWatchdog);
  navWatchdog = setTimeout(() => recoverFromStaleChunk(navTarget), PAGE_TIMEOUT + 2000);
}

function disarmWatchdog() {
  clearTimeout(navWatchdog);
}

/** 限时等待登录态：即使验证请求异常，导航也必须在限定时间内放行，绝不永久挂住界面 */
function waitForAuth(auth) {
  return Promise.race([
    auth.fetchMe(),
    new Promise((resolve) => setTimeout(resolve, 8000)),
  ]);
}

// 管理后台子节点的能力表，与 Sidebar.vue 各节点声明的 cap 一一对应：
// URL 直入无对应能力的后台页 → 提示并退回上一页，直接刷新进入则回仪表盘
const ADMIN_CAPS = {
  '/admin/stats': 'view_stats',
  '/admin/users': 'view_users',
  '/admin/permissions': 'manage_permissions',
  '/admin/approvals': 'approve_sensitive',
  '/admin/applications/controller': 'review_applications',
  '/admin/applications/staff': 'review_applications',
  '/admin/airlines': 'review_airlines',
  '/admin/events': 'manage_events',
  '/admin/archive': 'manage_archive',
  '/admin/tickets': 'manage_tickets',
  '/admin/notices': 'manage_notices',
  '/admin/partners': 'manage_notices',
  '/admin/shop': 'manage_shop',
  '/admin/logs-login': 'view_logs',
  '/admin/logs-register': 'view_logs',
  '/admin/logs-network': 'view_logs',
  '/admin/logs-audit': 'view_logs',
  '/admin/banned-ips': 'view_logs',
  '/admin/airline-funds': 'manage_airline_funds',
  '/admin/surveys': 'view_surveys',
};

router.beforeEach(async (to, from) => {
  armWatchdog(to);
  const auth = useAuthStore();
  if (!auth.loaded) await waitForAuth(auth);

  if (to.meta.auth && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } };
  }
  // 管理后台的准入改为「能力」判断，role 分支 ∪ rating 分支，与后端同一套：
  // 普通用户两条分支都是空的，任何 /admin/* 都会被挡回仪表盘。
  if (to.meta.admin && !auth.canAdmin) {
    return { name: 'dashboard' };
  }
  // 细粒度能力校验：无对应能力的后台页 → 提示 + 退回上一页；
  // 直接刷新/直链进入，无上一页则回仪表盘
  const needCap = ADMIN_CAPS[to.path]
    || (to.path.startsWith('/admin/archive') ? 'manage_archive' : '');
  if (needCap && !auth.can(needCap)) {
    showToast('无权限访问该页面');
    if (from.matched.length && from.fullPath !== to.fullPath) return false;
    return { name: 'dashboard' };
  }
  if (to.meta.guest && auth.isLoggedIn) {
    return { name: 'dashboard' };
  }
  return true;
});

/* 懒加载 chunk 失效，部署后旧页面引用了已删除的旧 chunk：自动整页恢复到目标路由*/
router.onError((error, to) => {
  disarmWatchdog();
  if (isChunkLoadError(error)) {
    recoverFromStaleChunk(to?.fullPath);
    return;
  }
  /* 其余导航错误此前被完全静默——界面点不动却查无原因。
     现在记录并立刻可见，让「导航为什么失败」自己开口。 */
  const message = error?.message || String(error);
  const target = to?.fullPath || '?';
  recordDiagEvent('导航失败', `${message}，目标：${target}`);
  showDiagPanel('导航失败', [
    `原因：${message}`,
    `目标页面：${target}`,
    '',
    '请把这段信息发给开发者。',
  ]);
  showToast(`页面跳转失败：${message}`);
});

/* 导航成功即认为当前页面与新构建一致，解除自恢复节流与看门狗 */
router.afterEach(() => {
  disarmWatchdog();
  markAppHealthy();
});
