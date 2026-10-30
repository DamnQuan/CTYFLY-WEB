/**
 * 桌面小鲸灵的开关状态，跨组件共享
 *
 * 关闭后写入 localStorage，刷新或下次访问都不再出现；
 * 想要找回来，到「个人中心」把它打开即可，不能做成关了就永远回不来。
 */
import { ref } from 'vue';

const KEY = 'ctyfly_pet';
const HOVER_KEY = 'ctyfly_pet_hover';

function readEnabled() {
  try {
    return localStorage.getItem(KEY) !== 'off';
  } catch {
    return true; // 无法访问存储时按默认开启处理
  }
}

export const petEnabled = ref(readEnabled());

export function setPetEnabled(on) {
  petEnabled.value = !!on;
  try {
    if (on) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, 'off');
  } catch {
    /* 忽略：本次会话内仍然生效，只是不持久化 */
  }
}

/**
 * 悬停模式
 *   false，默认：松手后按重力落回页面底部，和现实里的小鲸灵一样
 *   true：松手就停在原地悬着，可以停在半空或页面顶部
 */
function readHover() {
  try {
    return localStorage.getItem(HOVER_KEY) === 'on';
  } catch {
    return false;
  }
}

export const petHover = ref(readHover());

export function setPetHover(on) {
  petHover.value = !!on;
  try {
    if (on) localStorage.setItem(HOVER_KEY, 'on');
    else localStorage.removeItem(HOVER_KEY);
  } catch {
    /* 忽略 */
  }
}
