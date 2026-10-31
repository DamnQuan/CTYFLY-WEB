<script setup>
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { fmtTime } from '../utils.js';
import Icon from '../components/Icon.vue';

const router = useRouter();
const events = ref([]);
const loading = ref(true);
const archiveQuery = ref('');

function searchArchive() {
  const q = archiveQuery.value.trim();
  router.push({ name: 'archive', query: q ? { q } : {} });
}

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
      <p class="hero-sub">加入我们，体验最真实的连飞乐趣</p>
      <div class="hero-actions">
        <router-link class="btn btn-primary btn-lg" to="/register">立即注册</router-link>
        <router-link class="btn btn-ghost btn-lg" to="/login">立即登录</router-link>
        <a
          target="_blank"
          href="https://qm.qq.com/cgi-bin/qm/qr?k=xX5rJgrrA98XZZjEzZ02QgA8MMUTwXFW&jump_from=webapi&authKey=o04NKjyHYlbl32mZH3fwbOTAyuYV0Kzkncuba2VI6kZ6gbqx4fUrtK9fZjmcO+Di"
          title="『CTY』垂天云飞友集团"
          class="qq-join-btn"
        >加入QQ群</a>
      </div>
    </section>

    <div class="glass card archive-entry">
      <div class="archive-entry-head">
        <div class="archive-entry-icon"><Icon name="book" :size="20" /></div>
        <div>
          <div class="archive-entry-title">飞圈事件检索</div>
          <div class="archive-entry-desc">检索近两年飞圈重要事件与资料，每条都附来源</div>
        </div>
      </div>
      <form class="archive-entry-search" @submit.prevent="searchArchive">
        <input v-model="archiveQuery" class="input" maxlength="60" placeholder="输入事件名、平台、航司或关键词" />
        <button class="btn btn-primary" type="submit"><Icon name="search" :size="15" /> 检索</button>
      </form>
      <div class="archive-entry-foot">
        <span>游客可检索，投稿需登录</span>
        <router-link class="link" to="/archive">查看全部事件</router-link>
      </div>
    </div>

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
      <p style="color: var(--gray); font-size: 12.5px">© 2026 CTYFLY - All rights reserved</p>
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
.archive-entry { margin-top: 8px; }
.archive-entry-head { display: flex; align-items: center; gap: 12px; }
.archive-entry-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(10, 132, 255, 0.12);
  color: var(--blue);
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.archive-entry-title { font-size: 17px; font-weight: 600; }
.archive-entry-desc { margin-top: 3px; color: var(--text-2); font-size: 13px; }
.archive-entry-search { display: flex; gap: 10px; margin-top: 14px; }
.archive-entry-search .input { flex: 1; }
.archive-entry-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; color: var(--gray); font-size: 12px; flex-wrap: wrap; }
@media (max-width: 620px) {
  .archive-entry-search { flex-direction: column; }
}
@media (max-width: 620px) {
  .hero { padding: 44px 18px; }
  .hero-title { font-size: 32px; }
  .hero-sub { font-size: 14.5px; margin-bottom: 22px; }
}
.hero-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
}
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
</style>
