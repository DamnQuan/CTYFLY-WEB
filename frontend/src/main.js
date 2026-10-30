import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import { router } from './router/index.js';
import { initTheme } from './theme.js';
import { installRecovery, markAppHealthy, watchForNewBuild } from './recover.js';
import { installDiag, reportPreviousSession, watchLinkClicks } from './diag.js';
import './styles/main.css';

initTheme();

// 先装自恢复：部署后旧页面点到已失效的 chunk 时自动整页恢复，而不是卡住
installRecovery();
// 再装新构建检测：停留期间发布了新版本就提示刷新
watchForNewBuild();
// 卡顿/错误自检：真卡死时页面无法自救，靠下次启动汇报上一次会话的异常
installDiag();
watchLinkClicks();

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.mount('#app');

// 应用挂载成功：解除自恢复节流，允许后续部署再次触发
markAppHealthy();

// 稍后汇报上一次会话的异常，避免与首屏渲染抢时间
setTimeout(reportPreviousSession, 900);
