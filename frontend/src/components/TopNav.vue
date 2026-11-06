<script setup>
/**
 * 顶部栏导航，用户可在个人中心把侧边栏切换成它
 *
 * 交互要点，站长 2026-10-06 第 3 项要求：
 *  - 导航横排
 *  - 鼠标悬停时从导航条下方「下落」一个通栏面板
 *  - 子页面在面板里分列展示，每项带图标与说明
 *  - 在菜单项之间移动时面板保持打开、只换内容，所以 openLabel 直接切换，
 *    面板的 .open 状态不动，只有内容用 key 触发一次淡入
 *
 * 另外：窄屏，≤860px 不放顶部横排，由 navlayout.js 的 isTopLayout 回退到侧边抽屉，
 * 所以这里不需要自己处理移动端断点。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth.js';
import { useNavItems } from '../nav.js';
import { toggleNavLayout } from '../navlayout.js';
import { confirmModal } from '../modal.js';
import { prefetchRoute } from '../prefetch.js';
import Icon from './Icon.vue';
import UserAvatar from './UserAvatar.vue';
import UserTag from './UserTag.vue';
import AppTopbar from './AppTopbar.vue';
// 站点标志：走构建产物，文件名带 hash，可长期缓存
import logoMark from '../assets/logo-mark.png';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { navItems, visibleChildren } = useNavItems();

/** 面板当前展示的一级分组，'' = 收起*/
const openLabel = ref('');
let closeTimer = null;

const topItems = computed(() =>
  navItems.value.filter((i) => !i.admin || visibleChildren(i).length > 0));
const openItem = computed(() =>
  topItems.value.find((i) => i.label === openLabel.value && i.children) || null);

/** 悬停到某个一级项：直接换面板内容，不关闭再打开，要求里的「保持打开只换内容」*/
function openGroup(item) {
  cancelClose();
  if (!item.children || !visibleChildren(item).length) return;
  openLabel.value = item.label;
}
function cancelClose() {
  if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
}
function closeNow() {
  cancelClose();
  openLabel.value = '';
}
/** 鼠标离开导航条/面板时给一点缓冲：斜着移动到面板或相邻菜单项都不会闪断 */
function scheduleClose() {
  cancelClose();
  closeTimer = setTimeout(() => { openLabel.value = ''; closeTimer = null; }, 140);
}
/** 触摸/键盘：点一下开合 */
function toggleGroup(item) {
  if (openLabel.value === item.label) closeNow();
  else openGroup(item);
}

function onKey(e) {
  if (e.key === 'Escape') closeNow();
}
onMounted(() => window.addEventListener('keydown', onKey));
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey);
  cancelClose();
});

// 路由变化即收起
watch(() => route.fullPath, closeNow);

const isCurrent = (to) => route.path === to || route.path.startsWith(`${to}/`);
const groupActive = (item) => item.children?.some((c) => isCurrent(c.to));

async function logout() {
  closeNow();
  const ok = await confirmModal({
    title: '退出登录',
    message: '确定要退出当前账号吗？退出后需要重新登录才能继续使用。',
    confirmText: '退出登录',
  });
  if (!ok) return;
  await auth.logout();
  router.push('/login');
}
</script>

<template>
  <header class="topnav">
    <div class="topnav-bar" @mouseleave="scheduleClose" @mouseenter="cancelClose">
      <router-link class="topnav-logo" to="/" @click="closeNow">
        <img class="brand-mark" :src="logoMark" alt="" width="20" height="20" /> CTYFLY
      </router-link>

      <nav class="topnav-items">
        <template v-for="item in topItems" :key="item.label">
          <!-- 无子项：直接跳转 -->
          <router-link
            v-if="!item.children"
            class="topnav-item"
            :class="{ 'is-current': isCurrent(item.to) }"
            :to="item.to"
            @mouseenter="prefetchRoute(item.to)"
            @focus="openGroup(item)"
            @click="closeNow"
          >
            <img v-if="item.image" class="topnav-item-logo" :src="item.image" alt="" />
            {{ item.label }}
          </router-link>

          <!-- 有子项：悬停下落面板 -->
          <button
            v-else
            type="button"
            class="topnav-item"
            :class="{ 'is-current': groupActive(item), 'is-open': openLabel === item.label }"
            :aria-expanded="openLabel === item.label"
            aria-haspopup="true"
            @mouseenter="openGroup(item)"
            @focus="openGroup(item)"
            @click="toggleGroup(item)"
          >
            {{ item.label }}
            <Icon name="chevron" :size="13" class="topnav-caret" />
          </button>
        </template>
      </nav>

      <div class="topnav-right">
        <!-- 时钟 / 时区 / 主题：复用顶栏控件，compact 模式只去掉外壳，不重复实现-->
        <AppTopbar compact />
        <router-link class="topnav-user" to="/profile" title="个人中心" @click="closeNow">
          <UserAvatar :user="auth.user" :size="26" />
          <UserTag
            :badge="auth.user?.equipped_badge" :title="auth.user?.equipped_title" size="sm"
          >{{ auth.user?.username }}</UserTag>
        </router-link>
        <button class="topnav-icon" title="改回左侧边栏" @click="toggleNavLayout">
          <Icon name="menu" :size="16" />
        </button>
        <button class="topnav-icon" title="退出登录" @click="logout">
          <Icon name="logout" :size="15" />
        </button>
      </div>
    </div>

    <!-- 通栏下落面板：open 状态与内容分离，换菜单项时只换内容 -->
    <div
      class="topnav-panel"
      :class="{ open: !!openItem }"
      @mouseenter="cancelClose"
      @mouseleave="scheduleClose"
    >
      <div v-if="openItem" :key="openItem.label" class="topnav-panel-inner">
        <div class="topnav-panel-head">
          <span class="topnav-panel-icon"><Icon :name="openItem.icon" :size="16" /></span>
          <span class="topnav-panel-title">{{ openItem.label }}</span>
          <span class="topnav-panel-desc">{{ openItem.desc }}</span>
        </div>
        <div class="topnav-cols">
          <router-link
            v-for="c in visibleChildren(openItem)"
            :key="c.to"
            class="topnav-card"
            :class="{ 'is-current': isCurrent(c.to) }"
            :to="c.to"
            @mouseenter="prefetchRoute(c.to)"
            @click="closeNow"
          >
            <span class="topnav-card-icon"><Icon :name="c.icon || 'link'" :size="17" /></span>
            <span class="topnav-card-body">
              <span class="topnav-card-title">{{ c.label }}</span>
              <span class="topnav-card-desc">{{ c.desc || '' }}</span>
            </span>
            <Icon name="chevron" :size="12" class="topnav-card-arrow" />
          </router-link>
        </div>
      </div>
    </div>
  </header>
</template>
