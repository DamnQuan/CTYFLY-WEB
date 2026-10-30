"""数据库建表语句，与 database.py 的初始化逻辑分开维护。

本文件只放 SQL 文本，不含迁移，迁移仍在 database.py 的 init_db 中顺序执行。
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cid TEXT NOT NULL UNIQUE,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  qq TEXT DEFAULT '',
  avatar_url TEXT DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user',
  rating TEXT NOT NULL DEFAULT '飞行员',
  pilot_rank TEXT NOT NULL DEFAULT '学员',
  status TEXT NOT NULL DEFAULT 'active',
  is_controller INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS verification_codes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL COLLATE NOCASE,
  code TEXT NOT NULL,
  purpose TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS cid_random_log (
  sid TEXT PRIMARY KEY,
  count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  dep TEXT NOT NULL DEFAULT '',
  arr TEXT NOT NULL DEFAULT '',
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'upcoming',
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  route TEXT NOT NULL DEFAULT '',
  distance_nm REAL,
  notams TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS event_signups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  callsign TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'pilot',
  aircraft TEXT NOT NULL DEFAULT '',           -- 飞行员机型（席位制报名，管制员为空）
  position_id INTEGER,                         -- 管制员占用的席位 id（event_atc_positions.id，飞行员为 NULL）
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE(event_id, user_id)
);

-- 活动管制席位：管理员为活动预设席位（如 ZBAA_TWR / S1 / 121.600），
-- 管制员报名时占用某一席位（event_signups.position_id 引用本表），一席一人。
-- event_id 必须带 ON DELETE CASCADE：删活动要连带清席位，否则留下孤儿行
-- （2026-10-05 生产/测试各踩过一次，旧表当年漏了这个约束，见下方重建迁移）。
CREATE TABLE IF NOT EXISTS event_atc_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  name TEXT NOT NULL,        -- 席位名，如 ZBAA_TWR
  rating TEXT NOT NULL DEFAULT '',  -- 等级，如 S1/S2/C1
  frequency TEXT NOT NULL DEFAULT '',  -- 频率，如 121.600
  sort INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- IP 黑名单：脚本/爬虫注册/登录自动封禁（UA 识别触发），命中后注册/登录直接 403。
-- expires_at 为 NULL 表示永久；自动封禁默认 90 天（BAN_AUTO_DAYS），动态 IP 复用不至于永久误伤。
CREATE TABLE IF NOT EXISTS banned_ips (
  ip TEXT PRIMARY KEY,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  expires_at TEXT,
  source TEXT NOT NULL DEFAULT 'auto',
  note TEXT NOT NULL DEFAULT ''
);

-- IP 白名单：误封兜底 + 内网/办公网固定出口放行；白名单优先于黑名单
CREATE TABLE IF NOT EXISTS ip_whitelist (
  ip TEXT PRIMARY KEY,
  note TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 活动简报：每场已结束活动一篇（管理员撰写），正文之外自动带报名/呼号数据；
-- 仅登录成员可见，图片经鉴权接口读取。
CREATE TABLE IF NOT EXISTS event_briefings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS event_briefing_images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  briefing_id INTEGER NOT NULL REFERENCES event_briefings(id) ON DELETE CASCADE,
  orig_name TEXT NOT NULL DEFAULT '',
  stored_name TEXT NOT NULL UNIQUE,
  content_type TEXT NOT NULL,
  size INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  type TEXT NOT NULL,
  nickname TEXT NOT NULL DEFAULT '',
  age TEXT NOT NULL DEFAULT '',
  hours TEXT NOT NULL DEFAULT '',
  experience TEXT NOT NULL DEFAULT '',
  motivation TEXT NOT NULL DEFAULT '',
  available_time TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  review_note TEXT NOT NULL DEFAULT '',
  reviewed_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  reviewed_at TEXT,
  -- 面试流程（2026-10-05）：职员申请必须先安排并完成面试，才能给出通过/驳回结论
  interview_status TEXT NOT NULL DEFAULT '',   -- '' 未安排 | sent 已发邀约 | done 已完成
  interview_at1 TEXT NOT NULL DEFAULT '',      -- 可用面试时间 1（YYYY-MM-DDTHH:mm）
  interview_at2 TEXT NOT NULL DEFAULT '',      -- 可用面试时间 2（同上）
  interview_sent_at TEXT,                      -- 邀约发出时间
  interview_done_at TEXT,                      -- 面试完成（管理员标记）时间
  interview_by INTEGER REFERENCES users(id)    -- 发邀约的管理员
);

CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '其他',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS ticket_replies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  is_staff INTEGER NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 工单附件：图片 / PDF / Word。按文件头（magic bytes）识别类型后落盘，
-- stored_name 为服务端随机名；只能经 /api/attachments/{id} 鉴权读取。
CREATE TABLE IF NOT EXISTS ticket_attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  reply_id INTEGER REFERENCES ticket_replies(id) ON DELETE SET NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  orig_name TEXT NOT NULL,
  stored_name TEXT NOT NULL UNIQUE,
  content_type TEXT NOT NULL,
  kind TEXT NOT NULL,                            -- image | pdf | word
  size INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS routes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dep TEXT NOT NULL,
  arr TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT '',
  route_text TEXT NOT NULL,
  distance TEXT NOT NULL DEFAULT '',
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS notices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  pinned INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS airlines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  icao TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  logo_url TEXT NOT NULL DEFAULT '',
  owner_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pending',      -- pending | approved | rejected
  review_note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  reviewed_at TEXT,
  reviewed_by INTEGER REFERENCES users(id),
  -- 对外主页（/va/{icao}）可由 CEO 自定义的内容与板块开关
  public_slogan TEXT NOT NULL DEFAULT '',
  public_welcome TEXT NOT NULL DEFAULT '',
  show_members INTEGER NOT NULL DEFAULT 1,
  show_routes INTEGER NOT NULL DEFAULT 1,
  show_fleet INTEGER NOT NULL DEFAULT 1,
  show_stats INTEGER NOT NULL DEFAULT 1,
  hub TEXT NOT NULL DEFAULT ''                 -- 主基地机场（ICAO，机队驻地/包机与转场体系基准）
);
CREATE TABLE IF NOT EXISTS airline_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL DEFAULT 'pilot',          -- ceo | pilot
  status TEXT NOT NULL DEFAULT 'pending',      -- pending | active
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  joined_at TEXT,
  UNIQUE(airline_id, user_id)
);

CREATE TABLE IF NOT EXISTS airline_routes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  flight_no TEXT NOT NULL DEFAULT '',
  dep TEXT NOT NULL DEFAULT '',
  arr TEXT NOT NULL DEFAULT '',
  aircraft TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  base_salary INTEGER NOT NULL DEFAULT 200,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS flight_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  route_id INTEGER REFERENCES airline_routes(id) ON DELETE SET NULL,
  dep TEXT NOT NULL DEFAULT '',
  arr TEXT NOT NULL DEFAULT '',
  flight_no TEXT NOT NULL DEFAULT '',
  aircraft TEXT NOT NULL DEFAULT '',
  hours REAL NOT NULL DEFAULT 0,
  flight_date TEXT NOT NULL DEFAULT '',
  base_salary INTEGER NOT NULL DEFAULT 0,
  amount INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',     -- pending | approved | rejected
  reject_reason TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  reviewed_at TEXT,
  reviewed_by INTEGER REFERENCES users(id)
);

-- 签派单：飞行前的放行计划（航线快照 + 机型/高度/油量/备降场）。
-- 一个签派单在其生命周期内只允许关联一份飞行报告（提交报告时置 flown）。
CREATE TABLE IF NOT EXISTS dispatches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  route_id INTEGER REFERENCES airline_routes(id) ON DELETE SET NULL,
  fleet_id INTEGER REFERENCES airline_fleet(id) ON DELETE SET NULL,
  flight_no TEXT NOT NULL DEFAULT '',
  dep TEXT NOT NULL DEFAULT '',
  arr TEXT NOT NULL DEFAULT '',
  aircraft TEXT NOT NULL DEFAULT '',
  captain TEXT NOT NULL DEFAULT '',
  callsign TEXT NOT NULL DEFAULT '',
  sched_dep TEXT NOT NULL DEFAULT '',
  pax INTEGER NOT NULL DEFAULT 0,
  cargo INTEGER NOT NULL DEFAULT 0,
  network TEXT NOT NULL DEFAULT '',
  copilot TEXT NOT NULL DEFAULT '',
  ci INTEGER NOT NULL DEFAULT 0,
  dep_rwy TEXT NOT NULL DEFAULT '',
  arr_rwy TEXT NOT NULL DEFAULT '',
  cruise_alt INTEGER NOT NULL DEFAULT 0,
  fuel_kg INTEGER NOT NULL DEFAULT 0,
  alternate TEXT NOT NULL DEFAULT '',
  remarks TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',        -- open | flown | cancelled
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  flown_at TEXT,
  flight_token TEXT NOT NULL DEFAULT '',      -- 飞行上报令牌（签派生成时签发，防代报）
  flight_state TEXT NOT NULL DEFAULT 'issued', -- issued → departed → landed（ACARS 时间线状态）
  kind TEXT NOT NULL DEFAULT 'line',          -- line（航线签派）| ferry（转场）| charter（包机）
  distance_nm REAL                            -- 任务距离（转场/包机按大圆距离预计算存档）
);

-- 飞行事件时间线（平台 ACARS）：飞行员在飞行各节点主动上报，
-- 服务器记录接收时间作为核验基准。一个签派单一条时间线。
CREATE TABLE IF NOT EXISTS flight_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dispatch_id INTEGER NOT NULL REFERENCES dispatches(id) ON DELETE CASCADE,
  airline_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,                   -- depart | arrive
  server_time TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 按请求访问日志（/api）：溯源能力的关键一层。
-- APOC 平台 2026-08 事件的溯源即依赖「HTTP 全量日志 + 会话/身份关联」：
-- 记录每个 /api 请求的 时间/IP/用户/方法/路径/查询串/状态/耗时/UA/Referer，
-- 使任意 IP 的行为可回放、任意异常（含 429 探测与越权尝试）可归因到账号。
-- 隐私：含 IP 与账号信息，保留 30 天（与隐私政策 1.5 条一致），由 logretention 清理。
CREATE TABLE IF NOT EXISTS api_access_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  user_id INTEGER,
  pid INTEGER NOT NULL DEFAULT 0,
  ip TEXT NOT NULL DEFAULT '',
  method TEXT NOT NULL DEFAULT '',
  path TEXT NOT NULL DEFAULT '',
  query TEXT NOT NULL DEFAULT '',
  status INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  ua TEXT NOT NULL DEFAULT '',
  referer TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_api_access_ip_ts ON api_access_log(ip, created_at);
CREATE INDEX IF NOT EXISTS idx_api_access_uid_ts ON api_access_log(user_id, created_at);

-- 航司账本：报告通过后的公司分成入账（以及未来的公司支出）
CREATE TABLE IF NOT EXISTS airline_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  amount INTEGER NOT NULL,
  type TEXT NOT NULL DEFAULT 'revenue',       -- revenue | expense
  note TEXT NOT NULL DEFAULT '',
  report_id INTEGER REFERENCES flight_reports(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 航司机队：CEO 购买的飞机（建司审核通过时赠送 2 架 A320）。
-- 签派必须从本表选择可用飞机；签派期间置 dispatched，报告提交/取消签派后释放。
CREATE TABLE IF NOT EXISTS airline_fleet (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  aircraft TEXT NOT NULL,
  reg TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'available',   -- available | dispatched
  location TEXT NOT NULL DEFAULT '',          -- 飞机当前所在机场（ICAO）
  purchased_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS wallets (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  balance INTEGER NOT NULL DEFAULT 0,
  total_hours REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wallet_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount INTEGER NOT NULL,
  type TEXT NOT NULL DEFAULT 'salary',
  note TEXT NOT NULL DEFAULT '',
  report_id INTEGER REFERENCES flight_reports(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 日志与审计 ----------

CREATE TABLE IF NOT EXISTS login_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  cid TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  geo TEXT NOT NULL DEFAULT '',
  fingerprint TEXT NOT NULL DEFAULT '',
  ua TEXT NOT NULL DEFAULT '',
  pid INTEGER NOT NULL DEFAULT 0,
  success INTEGER NOT NULL DEFAULT 1,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS register_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  cid TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  geo TEXT NOT NULL DEFAULT '',
  fingerprint TEXT NOT NULL DEFAULT '',
  ua TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS api_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  status INTEGER NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  last_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE(day, method, path, status)
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id INTEGER,
  actor_name TEXT NOT NULL DEFAULT '',
  actor_role TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  ua TEXT NOT NULL DEFAULT '',
  pid INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,                              -- role_change | ban | delete_account
  target_user_id INTEGER NOT NULL,
  target_label TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}',
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',          -- pending | approved | rejected
  initiator_id INTEGER NOT NULL,
  initiator_name TEXT NOT NULL DEFAULT '',
  required INTEGER NOT NULL DEFAULT 2,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  decided_at TEXT,
  decision_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS approval_votes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  approval_id INTEGER NOT NULL REFERENCES approvals(id) ON DELETE CASCADE,
  voter_id INTEGER NOT NULL,
  voter_name TEXT NOT NULL DEFAULT '',
  vote TEXT NOT NULL,                              -- approve | reject
  comment TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE(approval_id, voter_id)
);

CREATE TABLE IF NOT EXISTS role_permissions (
  role TEXT NOT NULL,
  capability TEXT NOT NULL,
  allowed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (role, capability)
);

-- rating 权限分支：按管制等级（OBS/S1..I3/SUP/ADM）授权，
-- 与 role_permissions 并行，任一授予即拥有该能力。
CREATE TABLE IF NOT EXISTS rating_permissions (
  rating TEXT NOT NULL,
  capability TEXT NOT NULL,
  allowed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (rating, capability)
);

-- 用户级权限覆盖：针对具体某个人单独放开或收回。
-- allowed=1 强制拥有，allowed=0 强制收回（覆盖 role/rating 分支的结果）。
CREATE TABLE IF NOT EXISTS user_permissions (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,  capability TEXT NOT NULL,
  allowed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, capability)
);

-- ---------- 虚拟航司扩展：考核 / 动态 / 商城 ----------

CREATE TABLE IF NOT EXISTS rank_exams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  target_rank TEXT NOT NULL,                    -- 机长 | 教员
  flight_date TEXT NOT NULL DEFAULT '',
  route_flown TEXT NOT NULL DEFAULT '',
  aircraft TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',       -- pending | approved | rejected
  reject_reason TEXT NOT NULL DEFAULT '',
  reviewed_by INTEGER REFERENCES users(id),
  reviewed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS airline_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL REFERENCES users(id),
  content TEXT NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS airline_post_likes (
  post_id INTEGER NOT NULL REFERENCES airline_posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  PRIMARY KEY (post_id, user_id)
);

CREATE TABLE IF NOT EXISTS airline_post_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES airline_posts(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS shop_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price INTEGER NOT NULL DEFAULT 0,
  type TEXT NOT NULL DEFAULT 'title',           -- title | badge
  payload TEXT NOT NULL DEFAULT '',             -- 称号文字或徽章符号
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS shop_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  item_id INTEGER NOT NULL REFERENCES shop_items(id),
  price INTEGER NOT NULL DEFAULT 0,
  equipped INTEGER NOT NULL DEFAULT 0,          -- 称号类购买后自动装备
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 航司专属商城：CEO 自定义奖品（价格上限 500,000），成员用个人钱包兑换，
-- 货款进公司账上，CEO 标记发放。
CREATE TABLE IF NOT EXISTS airline_shop_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price INTEGER NOT NULL DEFAULT 0,             -- CEO 定价，上限 AIRLINE_SHOP_MAX_PRICE
  stock INTEGER NOT NULL DEFAULT -1,            -- -1 = 不限量；>0 = 限量
  created_by INTEGER REFERENCES users(id),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS airline_shop_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES airline_shop_items(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  price INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',       -- pending | delivered | cancelled
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  handled_at TEXT,
  handled_by INTEGER REFERENCES users(id)
);

-- 跳槽（转司）申请：批准前仍留在原航司，避免出现无航司空档
CREATE TABLE IF NOT EXISTS airline_transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  from_airline_id INTEGER REFERENCES airlines(id) ON DELETE SET NULL,
  from_icao TEXT NOT NULL DEFAULT '',
  from_name TEXT NOT NULL DEFAULT '',
  to_airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',        -- pending | approved | rejected | cancelled
  reject_reason TEXT NOT NULL DEFAULT '',
  reviewed_by INTEGER REFERENCES users(id),
  reviewed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 更新日志：管理员维护、前端公开展示的版本更新记录。
-- released_at 是展示用「发布日期」，允许管理员填写任意 ≤10 字符日期字符串（如 '2026-10-04'）。
CREATE TABLE IF NOT EXISTS changelogs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  released_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ================= 第二批功能（2026-10-18）：竞标 / 成就 / 二手市场 / 事故 =================

-- 航线招标：平台放出「待竞争的航线」，航司出价竞标，截止后一次性结算分配。
-- 出价即冻结资金（从 airlines.balance 原子扣除并记 airline_ledger 账本），
-- 结算时中标者资金不退（航线归属），未中标者全额退回 —— 账本与余额始终自洽。
CREATE TABLE IF NOT EXISTS bid_tenders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dep TEXT NOT NULL DEFAULT '',
  arr TEXT NOT NULL DEFAULT '',
  flight_no TEXT NOT NULL DEFAULT '',
  distance_nm REAL,
  intl INTEGER NOT NULL DEFAULT 0,
  base_salary INTEGER NOT NULL DEFAULT 200,
  start_price INTEGER NOT NULL DEFAULT 0,        -- 起拍价（低于此价不接受）
  min_step INTEGER NOT NULL DEFAULT 1000,        -- 最小加价幅度
  opens_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  closes_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',           -- open | settled | cancelled
  winner_airline_id INTEGER REFERENCES airlines(id) ON DELETE SET NULL,
  winner_offer_id INTEGER,
  settle_price INTEGER NOT NULL DEFAULT 0,
  settled_at TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_bid_tenders_status ON bid_tenders(status, closes_at);

-- 竞标出价：一次出价一条记录，代表一笔已冻结的资金。
-- ledger_hold_id 记录冻结时写入 airline_ledger 的行号，便于对账时逐笔核对。
CREATE TABLE IF NOT EXISTS bid_offers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tender_id INTEGER NOT NULL REFERENCES bid_tenders(id) ON DELETE CASCADE,
  airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  amount INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',         -- active | won | lost | refunded | withdrawn
  ledger_hold_id INTEGER,                        -- 冻结账本行（airline_ledger.id）
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  settled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_bid_offers_tender ON bid_offers(tender_id, amount DESC, id);
CREATE INDEX IF NOT EXISTS idx_bid_offers_airline ON bid_offers(airline_id, status);
-- 一家航司在同一招标里只允许存在一笔「在标」出价（改价 = 先退旧的再冻新的）。
-- 用部分索引而不是普通唯一索引：已结算/已退款的旧记录必须能保留。
CREATE UNIQUE INDEX IF NOT EXISTS uq_bid_offers_active
  ON bid_offers(tender_id, airline_id) WHERE status = 'active';

-- 成就定义：管理员可增删（seed 内置 14 枚），event_type 决定何时触发检查，
-- metric 是进度取值口径（见 routers/achievements.py 的 METRIC_SQL，绝不接受用户输入）。
CREATE TABLE IF NOT EXISTS achievement_defs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT 'flight',       -- flight | airline | economy | safety
  icon TEXT NOT NULL DEFAULT 'award',
  event_type TEXT NOT NULL DEFAULT '',           -- 触发事件（空=仅展示，不自动解锁）
  metric TEXT NOT NULL DEFAULT 'count',
  threshold INTEGER NOT NULL DEFAULT 1,
  reward INTEGER NOT NULL DEFAULT 0,             -- 解锁奖励（游戏币，进个人钱包）
  badge TEXT NOT NULL DEFAULT '',                -- 徽章符号（可空）
  sort INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 用户成就进度：UNIQUE(user_id, achievement_id) 是「只解锁一次」的硬约束，
-- 奖励发放以解锁时的条件 UPDATE（unlocked_at IS NULL）为准，天然幂等。
CREATE TABLE IF NOT EXISTS user_achievements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  achievement_id INTEGER NOT NULL REFERENCES achievement_defs(id) ON DELETE CASCADE,
  progress INTEGER NOT NULL DEFAULT 0,
  unlocked_at TEXT,
  reward_paid INTEGER NOT NULL DEFAULT 0,
  notified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE(user_id, achievement_id)
);
CREATE INDEX IF NOT EXISTS idx_user_achievements_user ON user_achievements(user_id, unlocked_at);

-- 二手飞机市场：卖家把机队里一架可用飞机挂牌（价格自定），买家整机买走。
-- 成交在**一个事务**里完成：扣买家航司余额 → 加卖家（扣手续费）→ 飞机换机队 → 挂牌置 sold。
-- fee_rate 与价格在挂牌时快照，成交时按快照计算，后续改价不影响已成交订单。
CREATE TABLE IF NOT EXISTS market_listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seller_id INTEGER NOT NULL REFERENCES users(id),
  seller_airline_id INTEGER NOT NULL REFERENCES airlines(id) ON DELETE CASCADE,
  fleet_id INTEGER REFERENCES airline_fleet(id) ON DELETE SET NULL,
  aircraft TEXT NOT NULL,
  aircraft_name TEXT NOT NULL DEFAULT '',
  reg TEXT NOT NULL DEFAULT '',
  price INTEGER NOT NULL,
  fee_rate INTEGER NOT NULL DEFAULT 5,           -- 成交手续费百分比（5 = 5%）
  hours REAL NOT NULL DEFAULT 0,                 -- 累计使用小时（影响展示，不参与计价）
  condition_pct INTEGER NOT NULL DEFAULT 90,     -- 机况百分比
  location TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'listed',         -- listed | sold | cancelled
  buyer_id INTEGER REFERENCES users(id),
  buyer_airline_id INTEGER REFERENCES airlines(id),
  sold_price INTEGER NOT NULL DEFAULT 0,
  fee INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  sold_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_listings_status ON market_listings(status, id);
CREATE INDEX IF NOT EXISTS idx_market_listings_seller ON market_listings(seller_airline_id, status);
-- 同一架飞机同时只能有一条在售挂牌（防止重复卖出同一架物理飞机）
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_listings_fleet
  ON market_listings(fleet_id) WHERE status = 'listed';

-- 成交流水：与挂牌表分开保存成交快照，便于事后对账（手续费、到账金额、双方航司）
CREATE TABLE IF NOT EXISTS market_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER NOT NULL REFERENCES market_listings(id) ON DELETE CASCADE,
  fleet_id INTEGER,
  seller_id INTEGER NOT NULL,
  seller_airline_id INTEGER NOT NULL,
  buyer_id INTEGER NOT NULL,
  buyer_airline_id INTEGER NOT NULL,
  aircraft TEXT NOT NULL DEFAULT '',
  reg TEXT NOT NULL DEFAULT '',
  price INTEGER NOT NULL DEFAULT 0,
  fee INTEGER NOT NULL DEFAULT 0,
  seller_received INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_market_trades_buyer ON market_trades(buyer_airline_id, id);

-- 事故记录：飞行员上报的飞行事故/事件（及后续调查处置）。
-- 溯源口径与 login_logs / audit_logs 一致：上报瞬间的 IP、UA、UA 分类、进程号全部落库，
-- 供管理员在「事故记录」里回放「谁在什么环境下报的」（requestinfo.classify_ua）。
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_no TEXT NOT NULL UNIQUE,                -- INC-YYYYMMDD-NNN（服务端生成）
  user_id INTEGER NOT NULL REFERENCES users(id),
  airline_id INTEGER REFERENCES airlines(id) ON DELETE SET NULL,
  dispatch_id INTEGER REFERENCES dispatches(id) ON DELETE SET NULL,
  flight_no TEXT NOT NULL DEFAULT '',
  dep TEXT NOT NULL DEFAULT '',
  arr TEXT NOT NULL DEFAULT '',
  aircraft TEXT NOT NULL DEFAULT '',
  reg TEXT NOT NULL DEFAULT '',
  severity TEXT NOT NULL DEFAULT 'incident',     -- incident | serious | accident | hull_loss
  phase TEXT NOT NULL DEFAULT '',                -- 地面/起飞/爬升/巡航/下降/进近/落地
  occurred_at TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',           -- open | investigating | closed
  conclusion TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  -- 溯源字段（上报时的请求环境快照，只读留痕）
  ip TEXT NOT NULL DEFAULT '',
  ua TEXT NOT NULL DEFAULT '',
  ua_label TEXT NOT NULL DEFAULT '',
  ua_bot INTEGER NOT NULL DEFAULT 0,
  pid INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, id);
CREATE INDEX IF NOT EXISTS idx_incidents_user ON incidents(user_id, id);
CREATE INDEX IF NOT EXISTS idx_incidents_airline ON incidents(airline_id, id);

-- 事故处置记录：管理员每次流转（受理/调查/结案）都留一条，含操作者与请求环境。
CREATE TABLE IF NOT EXISTS incident_updates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  actor_id INTEGER REFERENCES users(id),
  actor_name TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL DEFAULT '',              -- investigate | close | comment
  note TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  ua TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_incident_updates_incident ON incident_updates(incident_id, id);

-- 平台发展问卷：公开页 /docs 收集的反馈，管理员在后台按能力查看。
-- answers 存归一化后的 JSON，题目定义在 app/survey.py，后台按同一份定义翻译成可读文本。
CREATE TABLE IF NOT EXISTS survey_responses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  cid TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '',
  nickname TEXT NOT NULL DEFAULT '',
  contact TEXT NOT NULL DEFAULT '',
  answers TEXT NOT NULL DEFAULT '{}',
  ip TEXT NOT NULL DEFAULT '',
  ua TEXT NOT NULL DEFAULT '',
  anon_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_survey_responses_time ON survey_responses(created_at, id);
"""
