import { defineConfig } from 'vitest/config';

// 只测纯逻辑：工具函数、状态 getter、守卫依赖的判断。不引入组件渲染测试。
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.js'],
    reporters: 'default',
  },
});
