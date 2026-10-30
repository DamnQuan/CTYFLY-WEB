# 全站冒烟

逐路由检查白屏、JS 异常、5xx、被踢回登录页，以及登录页面的桌宠图片是否加载。

## 用法

```powershell
# 测试站
powershell -NoProfile -File deploy\smoke.ps1 -TokenFile .audit-tmp\test-admin-token.txt

# 主站
powershell -NoProfile -File deploy\smoke.ps1 -BaseUrl https://ccflysim.cn -TokenFile .audit-tmp\prod-admin-token.txt
```

也可以从 `check-all.ps1` 调用：

```powershell
powershell -NoProfile -File .\check-all.ps1 -Smoke -SmokeBase https://test.ccflysim.cn -SmokeTokenFile .audit-tmp\test-admin-token.txt
```

## 前置条件

- 本机有 Edge 或 Chrome，也可以用 `-Browser` 指定 Chromium 内核浏览器路径
- 一个管理员账号的 JWT，放在文件里传入。令牌过期后需要重新签发
- 首次运行会自动在 `deploy/smoke` 下安装 `playwright-core`

## 输出

- 控制台逐页结果与总计
- 截图与 JSON 报告写到系统临时目录的 `ctyfly-smoke`，可用 `-Out` 指定目录
- 有页面失败时退出码为 1，脚本异常退出码为 2

## 维护

新增页面时，把路径加到 `deploy/smoke/smoke.js` 的 `ROUTES` 数组。带参数的详情页不受支持，避免依赖真实数据。
