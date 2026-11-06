<script setup>
import { ref, onMounted } from 'vue';
import { api } from '../api.js';
import { fmtTime } from '../utils.js';
import Icon from '../components/Icon.vue';
import acisGlyph from '../assets/acis-glyph.png';
import acisGlyph400Avif from '../assets/acis-glyph-400.avif';
import acisGlyph800Avif from '../assets/acis-glyph-800.avif';
import acisGlyph400Webp from '../assets/acis-glyph-400.webp';
import acisGlyph800Webp from '../assets/acis-glyph-800.webp';

const events = ref([]);
const loading = ref(true);

onMounted(async () => {
  try {
    const data = await api.get('/api/home');
    events.value = data.events;
  } catch {
    /* 首页数据加载失败不阻塞 */
  }
  loading.value = false;
});
</script>

<template>
  <div class="home-shell">
  <div class="page home-page">
    <section class="hero" style="text-align: center">
      <h1 class="hero-title">CTYFLY</h1>
      <p class="hero-sub">加入 CTYFLY，和飞友一起连飞</p>
      <div class="hero-actions">
        <router-link class="btn btn-primary btn-lg" to="/register">立即注册</router-link>
        <router-link class="btn btn-ghost btn-lg" to="/login">立即登录</router-link>
        <a
          target="_blank"
          href="https://qm.qq.com/cgi-bin/qm/qr?k=xX5rJgrrA98XZZjEzZ02QgA8MMUTwXFW&jump_from=webapi&authKey=o04NKjyHYlbl32mZH3fwbOTAyuYV0Kzkncuba2VI6kZ6gbqx4fUrtK9fZjmcO+Di"
          title="「CTY」垂天云飞友集团"
          class="qq-join-btn"
        >加入QQ群</a>
      </div>
    </section>

    <router-link class="acis-entry" to="/acis">
      <picture class="acis-entry-picture">
        <source type="image/avif" :srcset="`${acisGlyph400Avif} 400w, ${acisGlyph800Avif} 800w`" sizes="(max-width: 620px) 76px, 112px" />
        <source type="image/webp" :srcset="`${acisGlyph400Webp} 400w, ${acisGlyph800Webp} 800w`" sizes="(max-width: 620px) 76px, 112px" />
        <img :src="acisGlyph" alt="ACIS" class="acis-entry-logo" width="1600" height="576" fetchpriority="high" decoding="async" />
      </picture>
      <span class="acis-entry-copy">
        <span class="acis-entry-title">ACIS 飞圈事件检索</span>
        <span class="acis-entry-desc">浏览全部飞圈事件资料，支持搜索、投稿与纠错</span>
      </span>
      <span class="acis-entry-cta">进入 ACIS <Icon name="chevron" :size="14" /></span>
    </router-link>

    <div style="margin-top: 48px">
      <div class="card-title" style="margin-bottom: 14px"><Icon name="calendar" :size="16" /> 近期活动</div>
      <div v-if="loading" class="loading">加载中…</div>
      <template v-else>
        <div v-for="e in events" :key="e.id" class="list-item">
          <div class="list-main">
            <div class="list-title">{{ e.title }}</div>
            <div class="list-sub">{{ e.dep }} → {{ e.arr }} · {{ fmtTime(e.start_time) }}</div>
          </div>
          <span class="tag tag-blue">{{ e.signup_count }} 人报名</span>
        </div>
        <div v-if="!events.length" class="empty">
          <div class="empty-icon"><Icon name="calendar" :size="22" /></div>
          <div>近期暂无活动</div>
        </div>
      </template>
    </div>

    
    <footer style="margin-top: auto; padding-top: 40px; text-align: center">
      <p style="color: var(--gray); font-size: 12.5px">© 2026 CTYFLY 保留所有权利</p>
      <div class="footer-links">
        <router-link to="/about" class="footer-link">关于我们</router-link>
        <router-link to="/docs" class="footer-link">发展问卷</router-link>
        <router-link to="/terms" class="footer-link">用户政策</router-link>
        <router-link to="/privacy" class="footer-link">隐私政策</router-link>
        <router-link to="/cookies" class="footer-link">Cookie 政策</router-link>
        <a
          class="footer-link"
          href="https://beian.miit.gov.cn/"
          target="_blank"
          rel="noopener noreferrer"
        >黔ICP备2026013829号</a>
      </div>
    </footer>
  </div>
  </div>
</template>

<style scoped>
/* 页脚贴底：仅改变纵向布局，宽度与内容区保持原样，顶栏为全局组件，高度 56px*/
.home-page {
  min-height: calc(100vh - 56px);
  display: flex;
  flex-direction: column;
  padding-bottom: 28px;
}
.hero { padding: 64px 24px; }
.hero-title { font-size: 44px; font-weight: 700; letter-spacing: -1px; }
.hero-sub { color: var(--text-2); font-size: 16px; max-width: 520px; margin: 12px auto 28px; }
.hero-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
}
.acis-entry {
  position: relative;
  display: flex;
  align-items: center;
  gap: 18px;
  margin-top: 10px;
  padding: 18px 22px;
  overflow: hidden;
  border-radius: 24px;
  border: 1px solid var(--glass-border);
  background: var(--glass-strong);
  color: inherit;
  text-decoration: none;
  backdrop-filter: blur(26px) saturate(180%);
  -webkit-backdrop-filter: blur(26px) saturate(180%);
  box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(255, 255, 255, 0.9);
  transition: transform 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease;
}
.acis-entry:hover {
  transform: translateY(-3px);
  border-color: rgba(92, 180, 255, 0.45);
  box-shadow: var(--shadow-lg-hover), inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.acis-entry-picture {
  position: relative;
  display: block;
  flex: none;
  width: 112px;
}
.acis-entry-logo {
  position: relative;
  display: block;
  width: 100%;
  height: auto;
  filter: drop-shadow(0 6px 14px rgba(10, 110, 210, 0.18));
}
.acis-entry-copy { position: relative; display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
.acis-entry-title { color: var(--text); font-size: 16px; font-weight: 700; letter-spacing: 0.01em; }
.acis-entry-desc { color: var(--text-2); font-size: 12px; line-height: 1.5; }
.acis-entry-cta {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex: none;
  padding: 7px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.34);
  border: 1px solid var(--glass-border);
  color: var(--text-2);
  font-size: 11.5px;
  font-weight: 600;
  transition: background 0.18s ease, color 0.18s ease;
}
.acis-entry:hover .acis-entry-cta { background: var(--blue); color: #fff; border-color: var(--blue); }
[data-theme="dark"] .acis-entry {
  box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
[data-theme="dark"] .acis-entry-cta { background: rgba(60, 60, 64, 0.5); }
[data-theme="dark"] .acis-entry:hover { box-shadow: var(--shadow-lg-hover), inset 0 1px 0 rgba(255, 255, 255, 0.16); }
/* QQ 官方风格加群按钮，QQ 蓝 #12B7F5*/
.qq-join-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 12px 26px;
  border-radius: 980px;
  background: #12b7f5;
  color: #fff;
  font-size: 15px;
  font-weight: 500;
  text-decoration: none;
  transition: all 0.18s ease;
}
.qq-join-btn:hover {
  background: #0da8e4;
  transform: scale(1.03);
}
.footer-links {
  display: flex;
  gap: 18px;
  justify-content: center;
  align-items: center;
  margin-top: 4px;
}
.footer-link {
  font-size: 12px;
  color: var(--gray);
  text-decoration: none;
}
.footer-link:hover { color: var(--text-2); text-decoration: underline; }
@media (max-width: 620px) {
  .hero { padding: 44px 18px; }
  .hero-title { font-size: 32px; }
  .hero-sub { font-size: 14.5px; margin-bottom: 22px; }
  .acis-entry {
    gap: 11px;
    padding: 14px 14px;
    border-radius: 20px;
    background: var(--glass-strong);
    backdrop-filter: blur(14px) saturate(150%);
    -webkit-backdrop-filter: blur(14px) saturate(150%);
    box-shadow: var(--shadow), inset 0 1px 0 rgba(255, 255, 255, 0.9);
  }
  .acis-entry-picture { width: 76px; }
  .acis-entry-logo { width: 100%; }
  .acis-entry-title { font-size: 14px; line-height: 1.35; }
  .acis-entry-desc { display: none; }
  .acis-entry-cta { padding: 6px 8px; font-size: 10px; }
}
</style>
