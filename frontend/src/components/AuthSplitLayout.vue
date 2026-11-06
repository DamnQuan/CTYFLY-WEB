<script setup>
/**
 * 认证页 6:4 分屏布局，登录 / 注册 / 找回密码共用
 *
 * 左 60%：品牌面板，停机坪实景 + 品牌语，底部压暗保证白字可读，右缘渐变融入表单区
 * 右 40%：无卡片表单容器，内容由各页面通过默认插槽提供
 * ≤900px：品牌面板折叠，表单独占整行
 *
 * 为什么做成组件：三个认证页共用同一套分屏结构，避免三份样式漂移；
 * 各页差异只有标题文案、插槽内容与表单宽度。
 */
import logoMark from '../assets/logo-mark.webp';
import heroImg from '../assets/login-hero-apron.webp';

defineProps({
  // 品牌语，内部静态文案，允许含 <br /> 换行；不接受任何外部输入
  headline: { type: String, default: '每一次飞行，<br />都从廊桥开始' },
  sub: { type: String, default: '虚拟航司 · 连飞活动 · 签派与飞行报告' },
  // 表单列最大宽度，注册表单字段更多，给宽一点
  paneWidth: { type: String, default: '380px' },
});
</script>

<template>
  <div class="auth-split" :style="{ '--pane-w': paneWidth }">
    <aside class="auth-hero">
      <img
        class="hero-img" :src="heroImg" alt=""
        loading="eager" fetchpriority="high"
      />
      <!-- 底部压暗保证品牌文字可读；右缘渐变融入表单区底色，暗/亮主题各自跟随变量-->
      <div class="hero-scrim" aria-hidden="true"></div>
      <div class="hero-fade" aria-hidden="true"></div>
      <div class="hero-content">
        <div class="hero-brand">
          <img :src="logoMark" alt="" width="30" height="30" />
          <span>CTYFLY</span>
        </div>
        <p class="hero-title" v-html="headline"></p>
        <p class="hero-sub">{{ sub }}</p>
      </div>
      <div class="hero-foot" aria-hidden="true">垂天云飞友集团</div>
      <a
        class="hero-credit"
        href="https://www.bilibili.com/video/BV1BUt26PEno?t=1.7"
        target="_blank" rel="noopener noreferrer"
      >品牌图来源 · 哔哩哔哩</a>
    </aside>

    <main class="auth-pane">
      <div class="pane-inner">
        <slot />
      </div>
    </main>
  </div>
</template>

<style scoped>
/* ===== 6:4 分屏布局 ===== */
.auth-split {
  min-height: calc(100vh - var(--topbar-h));
  display: grid;
  grid-template-columns: 3fr 2fr;   /* 6 : 4 */
  background: var(--auth-block);
}

/* ---------- 左：品牌面板 ----------
   高度跟随「整列内容高度」拉伸，不再固定 100vh 减顶栏：
   顶栏滚动后是悬浮覆盖在内容上的，若左栏按 100vh 减掉顶栏高度，
   滚动时左栏底部就会露出 56px 底色。2026-10-23 站长反馈的「图下面白底」正是由此产生。
   拉伸后图片始终铺满整列，任何滚动位置都不会露底。 */
.auth-hero {
  position: relative;
  align-self: stretch;
  overflow: hidden;
}
.hero-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* 焦点对准画面里的 A350 机头，约在横向 55% 处：窄面板裁切时飞机始终在视野内*/
  object-position: 55% 45%;
}
.hero-scrim {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(to top, rgba(8, 14, 24, 0.66), rgba(8, 14, 24, 0.08) 46%, rgba(8, 14, 24, 0.16));
}
/* 右缘淡出到表单区底色：两栏之间不是硬切线，是「融」过去的 */
.hero-fade {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: clamp(60px, 9vw, 150px);
  background: linear-gradient(to right, transparent, var(--auth-block));
}
.hero-content {
  position: absolute;
  left: clamp(24px, 4.5vw, 64px);
  right: clamp(80px, 12vw, 200px);
  bottom: clamp(26px, 6vh, 60px);
  color: #fff;
}
.hero-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 3px;
  opacity: 0.95;
}
.hero-brand img { border-radius: 8px; }
.hero-title {
  margin: 16px 0 10px;
  font-size: clamp(26px, 2.7vw, 40px);
  font-weight: 700;
  line-height: 1.3;
  letter-spacing: -0.4px;
  text-shadow: 0 2px 20px rgba(0, 0, 0, 0.4);
}
.hero-sub {
  margin: 0;
  font-size: 13.5px;
  letter-spacing: 1px;
  opacity: 0.85;
}
.hero-foot {
  position: absolute;
  right: 22px;
  bottom: 18px;
  color: rgba(255, 255, 255, 0.55);
  font-size: 11.5px;
  letter-spacing: 1.5px;
}
/* 品牌图来源：图片左上角的小胶囊，避开底部的 Cookie 提示条与品牌文字 */
.hero-credit {
  position: absolute;
  left: 22px;
  top: 18px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(8, 14, 24, 0.4);
  backdrop-filter: blur(6px);
  color: rgba(255, 255, 255, 0.82);
  font-size: 11.5px;
  letter-spacing: 0.6px;
  text-decoration: none;
  transition: background 0.18s ease, color 0.18s ease;
}
.hero-credit:hover { background: rgba(8, 14, 24, 0.62); color: #fff; text-decoration: underline; }

/* ---------- 右：无卡片表单 ---------- */
.auth-pane {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
}
.pane-inner {
  width: 100%;
  max-width: var(--pane-w, 380px);
}
/* 无卡片后标题与正文的间距比卡片版更舒展一点 */
.pane-inner :deep(.auth-brand) { margin-bottom: 32px; }

/* ---------- 移动端：折叠品牌面板 ---------- */
@media (max-width: 900px) {
  .auth-split { grid-template-columns: 1fr; }
  .auth-hero { display: none; }
  .auth-pane {
    align-items: flex-start;
    padding: 32px 16px;
  }
  .pane-inner { max-width: min(var(--pane-w, 380px), 420px); margin: 0 auto; }
}
</style>
