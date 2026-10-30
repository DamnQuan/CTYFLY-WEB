import { execSync } from 'node:child_process';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

/** 构建标识：git 短哈希 + 构建时间，注入到前端代码里，诊断面板会显示它。
 *  作用：出现问题时能立刻确认「浏览器里跑的是哪一版」，避免对着旧代码排查。*/
function buildId() {
  let commit = 'nogit';
  try {
    commit = execSync('git rev-parse --short HEAD', { encoding: 'utf8' }).trim() || 'nogit';
  } catch { /* 无 git 环境时忽略 */ }
  return `${commit}@${new Date().toISOString().slice(5, 16).replace('T', ' ')}`;
}

/* ===== 生产构建代码混淆，默认关闭，见下方 OBFUSCATE=====
 *
 * 目的：抬高他人阅读/复用我们业务代码的成本。
 * 前提认知：浏览器必须下载并执行 JS，所以混淆只是「抬高成本」，不是加密，也无法做到真正保护。
 *
 * 强度取舍，即便开启也刻意不开重型变换：
 *   - 打开：标识符十六进制重命名、字符串数组 + base64 编码、打乱/轮转、去掉 console 输出
 *   - 关闭：控制流扁平化、死代码注入、自防御
 *     这三项会让体积翻倍、首屏变慢，并且线上报错堆栈会彻底不可读。
 */
const OBFUSCATOR_OPTIONS = {
  compact: true,
  target: 'browser',
  identifierNamesGenerator: 'hexadecimal',
  renameGlobals: false,
  stringArray: process.env.OBF_NO_STRARR !== '1',
  // 抽成字符串数组的比例：越高越难读，体积也越大，中文经 base64 会 1.33 倍起步
  stringArrayThreshold: Number(process.env.OBF_THRESHOLD || 0.5),
  stringArrayEncoding: process.env.OBF_ENCODING === 'none' ? [] : ['base64'],
  // 轮转/打乱会重写字符串数组的下标，排查时可用 OBF_NO_SHUF=1 单独关掉
  stringArrayRotate: process.env.OBF_NO_SHUF !== '1',
  stringArrayShuffle: process.env.OBF_NO_SHUF !== '1',
  splitStrings: false,
  controlFlowFlattening: false,
  deadCodeInjection: false,
  selfDefending: false,
  debugProtection: false,
  disableConsoleOutput: true,
  unicodeEscapeSequence: false,
  sourceMap: false,
};

/** 混淆开关：默认 **关闭**。
 *
 *  实测代价，本仓库同一份代码：
 *      JS 原始 394 KB → 767 KB gzip 后 167 KB → 286 KB
 *      首屏静态资源 76.1 KB → 91.6 KB
 *      entry chunk 24.8 KB → 40.3 KB，gzip
 *  用户反馈「对网络要求有点高」，主要就来自这里。
 *
 *  而浏览器必须下载并执行 JS，混淆只是抬高阅读成本、不是加密；
 *  拿全体用户的流量换有限的「防抄」不划算，所以改为默认关闭。
 *  需要时仍可开启：OBFUSCATE=1 npm run build
 */
const OBFUSCATE = process.env.OBFUSCATE === '1';

/** 只混淆我们自己的业务 chunk；vendor，Vue / vue-router / pinia 保持原样。
 *  原因有二：一是第三方库本身开源、混淆没有意义；二是混淆 Vue 运行时容易引入难查的怪异问题。*/
function obfuscateAppChunks() {
  return {
    name: 'ctyfly:obfuscate',
    apply: 'build',
    enforce: 'post',
    async generateBundle(_options, bundle) {
      if (!OBFUSCATE) return;
      // 混淆器及其传递依赖只在真正开启时才加载：默认构建不需要它，
      // 也就不必把它和整条依赖链装进 node_modules，减少供应链暴露面。
      let JavaScriptObfuscator;
      try {
        JavaScriptObfuscator = (await import('javascript-obfuscator')).default;
      } catch {
        throw new Error('OBFUSCATE=1 需要先安装混淆器：npm install --no-save javascript-obfuscator');
      }
      for (const chunk of Object.values(bundle)) {
        if (chunk.type !== 'chunk' || !chunk.fileName.endsWith('.js')) continue;
        if (chunk.fileName.includes('vendor')) continue;
        chunk.code = JavaScriptObfuscator.obfuscate(chunk.code, OBFUSCATOR_OPTIONS).getObfuscatedCode();
      }
    },
  };
}

export default defineConfig({
  plugins: [vue(), obfuscateAppChunks()],
  define: {
    __BUILD_ID__: JSON.stringify(buildId()),
  },
  build: {
    // 绝不出 sourcemap：map 文件会把混淆后的代码 1:1 还原成源码
    sourcemap: false,
    // 默认把每个路由的 CSS 拆成独立文件，由 Vite 的运行时预加载器动态注入 <link>。
    // 但混淆，尤其 stringArray 会破坏那段注入逻辑，导致路由组件的 <style scoped> 静默失效，
    // 表现为「布局莫名其妙变了」。关掉拆分后所有 CSS 由 index.html 一次性引入，不再依赖运行时。
    // CSS_SPLIT=1 可临时恢复拆分，仅用于 A/B 对比排查。
    cssCodeSplit: process.env.CSS_SPLIT === '1',
    rollupOptions: {
      output: {
        // 把 node_modules 拆成独立 vendor chunk，便于上面按文件名跳过混淆
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor';
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // API_TARGET 便于起临时后端做隔离测试，默认仍是本地开发后端
        target: process.env.API_TARGET || 'http://localhost:3001',
        changeOrigin: true,
      },
      // 本地上传文件，航司 Logo 等由后端 /uploads 托管，开发环境同样需要代理
      '/uploads': {
        target: process.env.API_TARGET || 'http://localhost:3001',
        changeOrigin: true,
      },
    },
  },
});
