// 前端 lint 配置，ESLint 9 flat config
//
// 策略与后端 ruff 一致：**只拦真错误**，未定义变量、模板语法/指令误用、Vue 核心规则，
// 风格类规则一律不开 —— 17.6k 行存量代码一次全改只会淹没真实问题。
// 想更严时的加固顺序：先开 pluginVue.configs['flat/strongly-recommended']，
// 再把存量告警清干净，最后才考虑 recommended + 格式化规则。
//
// 为什么值得有：后端刚接入 ruff 就抓出三处真问题，见交接文档 §34；
// 前端 71 个 .vue / 21 个 .js 此前完全没有任何静态检查，只靠 vite build 挡语法错误。
import js from '@eslint/js';
import pluginVue from 'eslint-plugin-vue';
import globals from 'globals';

export default [
  {
    ignores: ['dist/**', 'node_modules/**', 'public/**'],
  },
  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
        // vite 的编译期替换，见 vite.config.js 的 define：lint 时应视为已声明
        __BUILD_ID__: 'readonly',
      },
    },
    rules: {
      // 真错误：未使用变量/导入，args 不检查，允许 rest 兄弟忽略
      // caughtErrors:'none' —— `catch e { /* 有意不处理 */ }` 是常见写法，不算问题
      'no-unused-vars': ['error', {
        args: 'none',
        caughtErrors: 'none',
        varsIgnorePattern: '^_',
        ignoreRestSiblings: true,
      }],
      // 项目里大量使用 `catch { /* 忽略 */ }`，有意吞掉，允许空 catch
      'no-empty': ['error', { allowEmptyCatch: true }],
      // 单文件组件名：项目有 Icon.vue 这类单词组件，是刻意的
      'vue/multi-word-component-names': 'off',
      // 允许 `v-html` 的既有用法；但新增使用请自行确认内容已转义
      'vue/no-v-html': 'off',
    },
  },
];
