# NOTICE — 桌宠素材来自开源项目 dsh-pet

本站桌面宠物（「鲸宝」）的形象与动画素材来自开源项目 **dsh-pet**：

> https://github.com/PC2005-cloud/dsh-pet
> npm 包名 `dsh-pet`（本仓库素材自 0.3.7 导入）

## 许可与合规

| 部分 | 许可 | 本站使用方式 |
| --- | --- | --- |
| dsh-pet 代码（播放器 / 物理曲线的参考实现） | MIT（见 `frontend/public/pet/LICENSE-dsh-pet`） | 移植到 `frontend/src/deskpet/`（physics.js / stage.js），保留出处注释 |
| 动画 / 提示词 / 源视频（assets/webm 等） | 允许**开源使用**，**禁止商用** | 挑选 33 段放入 `frontend/public/pet/webm/`，仅用于本站桌宠 |

合规结论与依据：

- **本站是公益社区站**：站内「飞行工资 / 余额 / 商城」全部是游戏数值，没有任何真实货币充值、付费或广告，不属于上游许可所指的「商用」。
- **署名义务**：本文件、`frontend/src/deskpet/catalog.js` 头注释、宠物右键菜单「关于桌宠」三处均注明来源与许可；代码文件头部保留 MIT 版权与出处。
- **未修改素材本体**：仅重命名为 ASCII slug（映射见 `frontend/scripts/pet-assets.mjs`）并按需挑选，未对画面做任何改动。
- **衍生说明**：播放器/物理按上游 MIT 代码移植并按网页场景裁剪，属于 MIT 允许的范畴；素材保持原样分发。

## 日常维护

- 素材导入：`node scripts/import-pet-assets.mjs`（来源默认取 `$DSH_HOME/profiles/web/node_modules/dsh-pet/assets/webm`）
- 一致性校验：`npm run check:pet`（CI 前端 job 会跑）
- Safari/iOS 兜底静态立绘：`node scripts/gen-pet-posters.mjs`（开发机跑，产物已入库）

若未来本站出现真实商业用途（付费功能、广告等），必须先移除 dsh-pet 素材或取得上游授权，这一点已写入交接文档。

## 与 GPLv3 的关系

本仓库代码整体以 GPLv3 发布，但上述 dsh-pet 素材仍按上游许可单独分发，不适用 GPLv3。需要纯 GPLv3 代码时，删除 `frontend/public/pet/` 即可。
