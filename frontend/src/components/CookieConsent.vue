<script setup>
import { onMounted, ref } from 'vue';
import { clearPreferenceStorage, getConsent, setConsent } from '../consent.js';
import { showToast } from '../utils.js';
import Icon from './Icon.vue';

const visible = ref(false);
const leaving = ref(false);

const DISMISS_KEY = 'ctyfly_consent_dismissed';

onMounted(() => {
  // 已作过选择则不再打扰；本次会话手动关闭过也不再弹出
  let dismissed = false;
  try { dismissed = sessionStorage.getItem(DISMISS_KEY) === '1'; } catch { /* 忽略 */ }
  if (!getConsent() && !dismissed) {
    setTimeout(() => {
      visible.value = true;
    }, 800);
  }
});

function choose(v) {
  leaving.value = true;
  setTimeout(() => {
    setConsent(v);
    if (v === 'essential') {
      clearPreferenceStorage();
      showToast('已选择仅必需存储项，偏好设置本次会话内有效');
    } else {
      showToast('感谢！你的偏好设置将被记住');
    }
    visible.value = false;
  }, 240);
}

/** 暂不决定：本次会话收起，下次访问再次提示 */
function dismiss() {
  leaving.value = true;
  setTimeout(() => {
    try { sessionStorage.setItem(DISMISS_KEY, '1'); } catch { /* 忽略 */ }
    visible.value = false;
  }, 240);
}
</script>

<template>
  <transition name="consent">
    <div v-if="visible && !leaving" class="consent-banner" role="dialog" aria-live="polite">
      <button class="consent-close" title="暂不决定（本次会话不再提示）" @click="dismiss">
        <Icon name="x" :size="15" />
      </button>
      <div class="consent-text">
        <strong>存储使用提示</strong>
        <p>
          本站使用必要的本地存储维持登录功能；在你同意后，还会用偏好存储项记住主题与时区设置。
          本站不使用广告或追踪 Cookie。
          <router-link to="/cookies">了解 Cookie 政策</router-link>
          <span style="margin: 0 6px; color: var(--gray)">·</span>
          <router-link to="/privacy">隐私政策</router-link>
        </p>
      </div>
      <div class="consent-actions">
        <button class="btn btn-ghost" @click="choose('essential')">仅必需</button>
        <button class="btn btn-primary" @click="choose('all')">全部接受</button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.consent-banner {
  position: fixed;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  z-index: 400;
  width: min(680px, calc(100vw - 32px));
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 16px 20px;
  border-radius: 20px;
  /* 液态玻璃浮层：渐变描边 + 上缘 rim，折射由引擎注入，full 档*/
  border: 1px solid transparent;
  background:
    linear-gradient(var(--modal-bg), var(--modal-bg)) padding-box,
    linear-gradient(165deg, var(--lg-rim), var(--lg-rim-2) 40%, var(--lg-rim-2) 62%, var(--lg-rim)) border-box;
  backdrop-filter: blur(28px) saturate(180%);
  -webkit-backdrop-filter: blur(28px) saturate(180%);
  box-shadow: inset 0 1px 0 var(--lg-rim-2), 0 18px 60px rgba(0, 0, 0, 0.22);
}
.consent-close {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: var(--surface);
  color: var(--text-2);
  cursor: pointer;
  transition: all 0.15s ease;
}
.consent-close:hover { background: var(--surface-strong); color: var(--text); }
.consent-text { flex: 1; min-width: 0; }
.consent-text strong { font-size: 14px; }
.consent-text p {
  margin-top: 3px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-2);
}
.consent-text a { color: var(--blue); text-decoration: none; white-space: nowrap; }
.consent-text a:hover { text-decoration: underline; }
.consent-actions { display: flex; gap: 10px; flex-shrink: 0; }

@media (max-width: 620px) {
  .consent-banner { flex-direction: column; align-items: stretch; }
  .consent-actions { justify-content: flex-end; }
}

/* 丝滑出入场：底部回弹上浮，平滑收回 */
.consent-enter-active { transition: all 0.45s cubic-bezier(0.34, 1.4, 0.64, 1); }
.consent-leave-active { transition: all 0.24s ease; }
.consent-enter-from {
  opacity: 0;
  transform: translateX(-50%) translateY(90px) scale(0.96);
}
.consent-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(40px) scale(0.98);
}
</style>
