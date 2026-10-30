<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth.js';
import { useVaStore } from '../stores/va.js';
import { confirmModal } from '../modal.js';
import { useNavItems } from '../nav.js';
import { prefetchRoute, prefetchRoutesOnIdle } from '../prefetch.js';
import { isCollapsed, toggleNavCollapsed } from '../navlayout.js';
import Icon from './Icon.vue';
import UserAvatar from './UserAvatar.vue';
import UserTag from './UserTag.vue';
// 站点标志：走构建产物，文件名带 hash，可长期缓存
import logoMark from '../assets/logo-mark.png';

const props = defineProps({ open: Boolean });
const emit = defineEmits(['close']);

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const va = useVaStore();

// 登录后拉取航司成员身份：决定「航线列表/签派/报告」是否出现在侧边栏
watch(() => auth.isLoggedIn, (ok) => {
  if (ok) va.fetch();
  else va.clear();
}, { immediate: true });

// 空闲时预热常用页面，进入即秒开。
// 必须等确认已登录再预热：首次加载时路由/登录态还没就绪，侧边栏可能短暂挂载，
// 那时若直接预热，未登录用户在登录页就会白白下载 9 个业务页面的 chunk。
watch(() => auth.isLoggedIn, (ok) => {
  if (!ok) return;
  prefetchRoutesOnIdle([
    '/home', '/airlines', '/weather/metar', '/events',
    '/tickets', '/apply/controller', '/wallet', '/airlines/leaderboard', '/shop',
  ]);
}, { immediate: true });

/* 主导航数据来自共享模块 nav.js，侧边栏与顶部栏共用同一套定义*/
const { navItems, visibleChildren } = useNavItems();

const guestLinks = [
  { to: '/login', label: '登录', icon: 'logout' },
  { to: '/register', label: '注册', icon: 'user-plus' },
];

/* 二级菜单展开状态：路由所在组自动展开，也可手动开合 */
const openGroups = reactive(new Set());

function isOpen(item) {
  return openGroups.has(item.label);
}
/** 手风琴：同一时间只展开一组；再点已展开的那组则收起 */
function toggleGroup(label) {
  const wasOpen = openGroups.has(label);
  openGroups.clear();
  if (!wasOpen) openGroups.add(label);
}

/** 收拢态下点分组：先展开侧边栏，再打开该组，否则图标栏里点分组看不到任何东西*/
function onGroupToggle(item) {
  if (isCollapsed.value) {
    toggleNavCollapsed();
    openGroups.clear();
    openGroups.add(item.label);
    return;
  }
  toggleGroup(item.label);
}

/* ---------- 收拢态的悬浮提示，tooltip----------
 * 为什么不用 CSS :hover + 绝对定位：`.side-nav` 是 overflow-y:auto 的滚动容器，
 * 横向会被一并裁成 auto，tooltip 出了 68px 就被切掉，尝试过，确实被裁。
 * 因此用**独立元素 + fixed 定位**：按悬停项的位置算出坐标，渲染在 .sidebar 之外。
 * 只挂鼠标事件不够 —— 键盘 Tab 聚焦时也要出提示，@focus/@blur。
 */
const tip = reactive({ show: false, text: '', x: 0, y: 0 });

function showTip(e, text) {
  if (!isCollapsed.value || !text) return;
  const r = e.currentTarget.getBoundingClientRect();
  tip.text = text;
  tip.x = Math.round(r.right + 10);            // 图标右缘 10px
  tip.y = Math.round(r.top + r.height / 2);    // 与图标垂直居中
  tip.show = true;
}

function hideTip() {
  tip.show = false;
}
function isGroupActive(item) {
  return item.children?.some((c) => route.path === c.to || route.path.startsWith(c.to + '/'));
}
function syncOpenGroups() {
  // 注意必须是 navItems.value：navItems 是 computed，直接 for...of 遍历 ref 会抛
  // TypeError，is not iterable。这个错在基线版本就存在，0df990a 起，而它被 Vue 的
  // 错误处理吞掉，只表现为「当前路由所在的分组不会自动展开」——排查时极易漏。
  const active = navItems.value.find((item) => item.children && isGroupActive(item));
  // 当前路由不在任何分组内，如 /home、/partners：保留用户手动展开的那一组
  if (!active) return;
  // 手风琴：进入某分组下的页面时，把其它组收起来，只留当前这一组
  openGroups.clear();
  openGroups.add(active.label);
}

/* ---------- 滑动高亮块 ----------
 * 当前项只保留这一个圆角高亮底：切换时滑到新位置，宽高跟随目标项，一级项与二级项
 * 高度不同也能贴合，回弹曲线见 main.css 的 .nav-highlight.ready。
 *
 * 两条踩过的经验，都很隐蔽，务必照做：
 * 1 「当前项」必须由 Vue 计算属性 + :class 绑定决定，**不能**在测量函数里手改 classList：
 *    路由一变，Vue 会重写这些元素的 class 属性，手加的类会被整块覆盖 → 高亮停摆。
 * 2 这些状态与函数必须声明在 watch route.path **之前**：观察器 immediate 回调里访问
 *    尚未初始化的 const/let 会抛 TDZ 引用错误，而它会被 Vue 的错误处理吞掉，
 *    表面症状只是「高亮不再移动」。
 */
const sideNavEl = ref(null);
const hlEl = ref(null);
const hl = reactive({ x: 0, y: 0, w: 0, h: 0, show: false, ready: false });
let rafId = 0;

/** 全部可见导航项，带分组归属*/
const navCandidates = computed(() => {
  const list = [];
  for (const item of navItems.value) {
    if (item.children) {
      if (item.admin && !visibleChildren(item).length) continue;
      for (const c of visibleChildren(item)) list.push({ to: c.to, group: item.label });
    } else if (!item.admin || auth.isStaff) {
      list.push({ to: item.to });
    }
  }
  if (auth.isLoggedIn) list.push({ to: '/profile' });
  else for (const l of guestLinks) list.push({ to: l.to });
  return list;
});

/** 唯一的当前项：前缀匹配里路径最长的那个
 *  否则 /tickets/new 会让 /tickets 也命中，同时亮两项*/
const current = computed(() => {
  const path = route.path;
  let best = null;
  for (const c of navCandidates.value) {
    if (path !== c.to && !path.startsWith(`${c.to}/`)) continue;
    if (!best || c.to.length > best.to.length) best = c;
  }
  return best;
});

const isLinkCurrent = (item) => !current.value?.group && current.value?.to === item.to;
const isSubCurrent = (item, c) => isOpen(item) && current.value?.to === c.to;
/** 当前项落在被折叠的二级里时，高亮它所属的一级按钮 */
const isGroupCurrent = (item) => current.value?.group === item.label && !isOpen(item);

function measure() {
  const nav = sideNavEl.value;
  const box = hlEl.value;
  if (!nav || !box) return;
  const target = nav.querySelector('.nav-current');
  if (!target) {
    hl.show = false;
    return;
  }
  // 用 getBoundingClientRect 而不是 offsetTop：二级项在 .sub-inner position:relative 内，
  // offsetParent 不是 .side-nav，offsetTop 会算错
  const tr = target.getBoundingClientRect();
  const nr = nav.getBoundingClientRect();
  hl.x = Math.round(tr.left - nr.left + nav.scrollLeft);
  hl.y = Math.round(tr.top - nr.top + nav.scrollTop);
  hl.w = Math.round(tr.width);
  hl.h = Math.round(tr.height);
  hl.show = true;
}

/** 一段时间内逐帧跟随：二级菜单展开时目标项在持续位移，单次 measure 会跟不上 */
function startFollow(ms = 480) {
  cancelAnimationFrame(rafId);
  const end = performance.now() + ms;
  const tick = () => {
    measure();
    if (performance.now() < end) rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);
}

function onResize() {
  measure();
}

onMounted(() => {
  syncOpenGroups();
  nextTick(() => {
    measure();
    // 首帧先摆好位置再开启过渡，避免从 0,0 滑进来
    requestAnimationFrame(() => { hl.ready = true; });
  });
  window.addEventListener('resize', onResize);
});

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  cancelAnimationFrame(rafId);
});

// flush: 'post' —— 必须等 Vue 把 .nav-current 写进 DOM 之后再量
watch(() => route.path, () => { syncOpenGroups(); startFollow(); }, { flush: 'post' });
// 移动端抽屉开合、登录态/成员身份变化导致菜单项增减时，重新贴合
watch(() => props.open, () => startFollow(320), { flush: 'post' });
watch(() => navItems.value, () => startFollow(320), { deep: true, flush: 'post' });
// 手风琴展开/收起：分组集合一变，可见项的位置就变了。
// 注意不能用 openGroups.size 判断——单开模式下「关 A 开 B」集合大小不变但内容变了
watch(() => [...openGroups].join(','), () => startFollow(480), { flush: 'post' });
// 收拢/展开：菜单项宽度在过渡中持续变化，高亮块必须逐帧跟随，否则会错位
watch(isCollapsed, () => { hideTip(); startFollow(360); }, { flush: 'post' });

async function logout() {
  // 二次确认：误触侧边栏底部的退出按钮不应直接登出
  const ok = await confirmModal({
    title: '退出登录',
    message: '确定要退出当前账号吗？退出后需要重新登录才能继续使用。',
    confirmText: '退出登录',
  });
  if (!ok) return;
  await auth.logout();
  emit('close');
  router.push('/login');
}
</script>

<template>
  <!-- 移动端遮罩：抽屉唯一的「空白处」，点它才收起，点菜单项导航不收起，站长 2026-10-06 要求-->
  <div class="side-overlay" :class="{ show: open }" @click="emit('close')"></div>

  <aside class="sidebar" :class="{ open, 'is-collapsed': isCollapsed }">
    <!-- 抽屉内的关闭按钮：仅移动端抽屉形态显示，桌面侧边栏常驻，不该有叉-->
    <button class="side-close" type="button" title="收起菜单" @click="emit('close')">
      <Icon name="x" :size="15" />
    </button>
    <div class="sidebar-top">
      <router-link class="sidebar-logo" to="/">
        <img class="brand-mark" :src="logoMark" alt="" width="20" height="20" /><span class="brand-text">CTYFLY</span>
      </router-link>
      <!-- 收拢/展开：桌面端把侧边栏收成图标栏，状态持久化；移动端抽屉形态下隐藏-->
      <button
        class="nav-collapse-btn"
        type="button"
        :title="isCollapsed ? '展开侧边栏' : '收拢侧边栏'"
        :aria-label="isCollapsed ? '展开侧边栏' : '收拢侧边栏'"
        :aria-expanded="isCollapsed ? 'false' : 'true'"
        @click="toggleNavCollapsed()"
      >
        <Icon name="chevron" :size="14" />
      </button>
    </div>

    <nav class="side-nav" ref="sideNavEl" @scroll="hideTip">
      <!-- 滑动高亮块：唯一的高亮底，在菜单项之间滑动，宽高跟随目标项 -->
      <span
        ref="hlEl"
        class="nav-highlight"
        :class="{ ready: hl.ready }"
        :style="{
          transform: `translate3d(${hl.x}px, ${hl.y}px, 0)`,
          width: `${hl.w}px`,
          height: `${hl.h}px`,
          opacity: hl.show ? 1 : 0,
        }"
        aria-hidden="true"
      ></span>

      <template v-if="auth.isLoggedIn">
        <template v-for="item in navItems" :key="item.label">
          <!-- 一级链接：收拢时鼠标悬停/键盘聚焦都会在右侧弹出提示，见 showTip-->
          <router-link
            v-if="!item.children && (!item.admin || auth.isStaff)"
            class="side-link"
            :class="{ 'nav-current': isLinkCurrent(item) }"
            :to="item.to"
            :aria-label="isCollapsed ? item.label : null"
            @mouseenter="prefetchRoute(item.to); showTip($event, item.label)"
            @mouseleave="hideTip"
            @focus="prefetchRoute(item.to); showTip($event, item.label)"
            @blur="hideTip"
          >
            <Icon :name="item.icon" :size="16" /><span class="side-label">{{ item.label }}</span>
          </router-link>

          <!-- 二级菜单组：收拢态下点击会先展开侧边栏再打开该组，见 onGroupToggle-->
          <div v-else-if="item.children && (!item.admin || visibleChildren(item).length)" class="side-group">
            <button
              class="side-link side-group-toggle"
              :class="{ 'group-active': isGroupActive(item), 'nav-current': isGroupCurrent(item) }"
              :aria-label="isCollapsed ? item.label : null"
              @click="onGroupToggle(item)"
              @mouseenter="showTip($event, item.label)"
              @mouseleave="hideTip"
              @focus="showTip($event, item.label)"
              @blur="hideTip"
            >
              <Icon :name="item.icon" :size="16" /><span class="side-label">{{ item.label }}</span>
              <Icon name="chevron" :size="14" class="chevron" :class="{ open: isOpen(item) }" />
            </button>
            <div class="sub-wrap" :class="{ open: isOpen(item) }">
              <div class="sub-inner">
                <router-link
                  v-for="(c, i) in visibleChildren(item)"
                  :key="c.to"
                  class="side-sublink"
                  :class="{ 'nav-current': isSubCurrent(item, c) }"
                  :style="{ '--i': i }"
                  :to="c.to"
                  @mouseenter="prefetchRoute(c.to)"
                  @focus="prefetchRoute(c.to)"
                >{{ c.label }}</router-link>
              </div>
            </div>
          </div>
        </template>
      </template>

      <template v-if="auth.isLoggedIn">
        <div class="side-section"><span class="side-label">账号</span></div>
        <router-link
          class="side-link" :class="{ 'nav-current': isLinkCurrent({ to: '/profile' }) }"
          to="/profile"
          :aria-label="isCollapsed ? '个人中心' : null"
          @mouseenter="showTip($event, '个人中心')"
          @mouseleave="hideTip"
          @focus="showTip($event, '个人中心')"
          @blur="hideTip"
        >
          <Icon name="user" :size="16" /><span class="side-label">个人中心</span>
        </router-link>
      </template>

      <template v-else>
        <div class="side-section"><span class="side-label">开始使用</span></div>
        <router-link
          v-for="l in guestLinks"
          :key="l.to"
          class="side-link"
          :class="{ 'nav-current': isLinkCurrent(l) }"
          :to="l.to"
          :aria-label="isCollapsed ? l.label : null"
          @mouseenter="showTip($event, l.label)"
          @mouseleave="hideTip"
          @focus="showTip($event, l.label)"
          @blur="hideTip"
        >
          <Icon :name="l.icon" :size="16" /><span class="side-label">{{ l.label }}</span>
        </router-link>
      </template>
    </nav>

    <div class="side-foot">
      <template v-if="auth.isLoggedIn">
        <router-link to="/profile" class="side-user">
          <UserAvatar class="side-avatar" :user="auth.user" :size="34" />
          <div class="side-user-info">
            <div class="side-user-name">
              <UserTag
                :badge="auth.user.equipped_badge"
                :title="auth.user.equipped_title"
                size="sm"
              >{{ auth.user.username }}</UserTag>
            </div>
            <div class="side-user-cid">CID {{ auth.user.cid }}</div>
          </div>
        </router-link>
        <button class="side-logout" title="退出登录" @click="logout">
          <Icon name="logout" :size="15" />
        </button>
      </template>
      <template v-else>
        <div class="side-user-info" style="padding: 0 10px">
          <div class="side-user-cid">登录后开启完整功能</div>
        </div>
      </template>
    </div>
  </aside>

  <!-- 收拢态的悬浮提示：刻意放在 .sidebar **之外**。
       .sidebar 带 backdrop-filter，它会让 position:fixed 的后代以它为包含块，
       放进去坐标就不再是视口坐标；另外 .side-nav 是 overflow-y:auto，放里面会被横向裁掉。
       两个坑都踩过，所以这里用组件根级独立元素 + 视口坐标。 -->
  <div
    v-if="isCollapsed"
    class="side-tip"
    :class="{ show: tip.show }"
    :style="{ left: tip.x + 'px', top: tip.y + 'px' }"
    role="tooltip"
    aria-hidden="true"
  >{{ tip.text }}</div>
</template>
