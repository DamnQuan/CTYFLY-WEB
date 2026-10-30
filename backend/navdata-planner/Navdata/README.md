AIRAC 导航数据库目录
====================

本目录需要放置 **nd.db3**（AIRAC 导航数据库，约 105MB）。

由于体积过大，`*.db3` 已在 `.gitignore` 中排除，不纳入版本控制。
换机器或回滚代码后，请单独把 nd.db3 放回本目录：

```
backend/navdata-planner/Navdata/nd.db3
```

说明：
- 数据来源为 Navigraph 等 AIRAC 周期数据，表结构需包含
  `Airports`、`Waypoints`、`Airways`、`AirwayLegs`、`Terminals`、`TerminalLegs`、`config`
- 更换新周期数据时直接覆盖 nd.db3，sidecar 会在下次请求时自动检测并重载
- 也可用环境变量 `NAVDATA_DB` 指定数据库的任意位置（见 backend/.env.example）
