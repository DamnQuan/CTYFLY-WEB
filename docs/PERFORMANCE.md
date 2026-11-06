# 性能基线与优化记录

## 验收口径

- LCP < 2.5 s
- INP < 200 ms
- CLS < 0.1

Lighthouse 是实验室数据，INP 以真实用户上报的 `perf_metrics` 为准；CI 用 TBT 作为 INP 的实验室替代指标。

## 优化前基线

测试环境 `https://test.ccflysim.cn`，Lighthouse 移动端：

| 指标 | 数值 |
|---|---|
| Performance | 0.85 |
| LCP | 4.3 s |
| CLS | 0 |
| TBT | 50 ms |
| TTFB | 50 ms |
| LCP 元素 | 首页 ACIS 入口 Logo |

桌面端基线：Performance 0.99，LCP 0.8 s，CLS 0。

## 优化后

测试环境移动端：

| 指标 | 数值 |
|---|---|
| Performance | 0.98 |
| LCP | 2.0 s |
| CLS | 0 |
| TBT | 10 ms |
| TTFB | 90 ms |
| 现代图片可节省 | 0 |

LCP 从 4.3 s 降到 2.0 s，主要来自响应式 AVIF/WebP 图片。

## 已实施

### 网络层

- `/assets/` 带 hash 资源缓存一年并标记 `immutable`
- HTML 保持 `no-cache`，保证发布后立即拿到新入口
- Nginx 开启 gzip，覆盖 HTML、CSS、JS、JSON、SVG
- 当前服务器 Nginx 未编译 Brotli 模块，使用 gzip 作为兼容回退
- 站内 ACIS 与飞圈事件检索已合并，旧路径统一由前端路由重定向

### 首屏

- ACIS Logo 使用 AVIF 优先、WebP 回退、PNG 兜底
- 首页 LCP 图使用 400w/800w 响应式图片，移动端只取 7 KB 的 400w AVIF
- Logo 图片设置明确宽高，消除布局偏移
- 导航 Logo 使用 160w WebP，避免全站加载 488 KB 原图
- 首屏最小背景与字体栈内联到 `index.html`
- 首屏图片设置 `fetchpriority="high"`，装饰水印改为懒加载

### JavaScript 与交互

- 路由级代码分割保持现状，首屏基础包约 110 KB，gzip 后约 41 KB
- 性能采集延迟到 idle 阶段，避免与首屏竞争
- 动画使用 transform 与 opacity，避免触发布局
- 图片滚动到视口附近再加载

### 后端与数据

- SQLite 连接启用 WAL 下的 `synchronous=NORMAL`、`busy_timeout`、`cache_size`、`mmap_size`
- 为事件、报名、工单、飞行报告、钱包流水和 ACIS 评论补充索引
- 首页数据增加 20 秒进程内 TTL 缓存
- 列表接口保持分页，JSON 由 Nginx gzip 压缩
- 数据库连接继续使用线程本地复用

### 监控与门禁

- 前端 `src/perf.js` 采集 LCP、CLS、INP 近似值和 TTFB，通过 `sendBeacon` 上报 `/api/perf`
- 后端 `perf_metrics` 表存储真实用户指标
- `.lighthouserc.json` 设定 LCP 2.5 s、CLS 0.1 的硬阈值
- `.github/workflows/performance.yml` 在 PR 与 main 推送时构建并跑 Lighthouse CI

## 复测命令

```bash
# Lighthouse 移动端
npx lighthouse https://test.ccflysim.cn --output=json --output-path=baseline.json

# Lighthouse CI
npx @lhci/cli autorun --config=.lighthouserc.json

# 全站冒烟
pwsh ./deploy/smoke.ps1
```
