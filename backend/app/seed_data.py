"""演示与产品种子数据，与 database.py 初始化逻辑分开维护。"""

SAMPLE_ROUTES = [
    ("ZSPD", "ZBAA", "S0980", "PIKAS G330 SASAN W142 PDG B208 LADIX", "1078km"),
    ("ZSPD", "ZGGG", "S0960", "PIKAS A599 SLG A599 DUMET", "1235km"),
    ("ZBAA", "ZSHC", "S0920", "LADIX A461 GRIPS W142 PIMOL", "1120km"),
    ("ZGGG", "ZJSY", "S0940", "GUBCO G586 SANYA", "0750km"),
    ("ZLLL", "ZUUU", "S0890", "HUSAN B215 LZY", "0680km"),
    ("ZBAO", "ZBAD", "S0510", "TAJ W19 SADAN", "0165km"),
]

# 成就徽章种子： code, 名称, 说明, category, icon, event_type, metric, threshold, reward, badge
#
# 设计要点：
# - event_type 只是**触发时机**，真正的进度永远由服务器端 SQL 重新计算，见
# routers/achievements.py 的 METRIC_SQL，客户端传来的任何数字都不参与解锁判定 ——
#   否则「成就」就成了一个可以随手改数字的虚荣字段。
# - metric 必须是 METRIC_SQL 里的键，写错会当场 KeyError，不会静默算出错误进度。
# - 首飞/首胜这类 threshold=1 的成就与普通累计成就共用同一套结算逻辑，无需特判。
ACHIEVEMENT_SEEDS = [
    ("first_flight", "首飞纪念", "完成第一次飞行报告审核，飞行生涯正式开始", "flight",
     "plane", "flight_approved", "flight_count", 1, 1000, ""),
    ("flight_10", "展翅十次", "累计完成 10 次飞行", "flight",
     "trending", "flight_approved", "flight_count", 10, 3000, ""),
    ("flight_50", "五十航线", "累计完成 50 次飞行", "flight",
     "globe", "flight_approved", "flight_count", 50, 12000, ""),
    ("hours_10", "十小时", "累计飞行时长达到 10 小时", "flight",
     "wings", "flight_approved", "flight_hours", 10, 2000, ""),
    ("hours_50", "半百小时", "累计飞行时长达到 50 小时", "flight",
     "award", "flight_approved", "flight_hours", 50, 8000, ""),
    ("hours_200", "两百小时", "累计飞行时长达到 200 小时，跻身资深机组", "flight",
     "crown", "flight_approved", "flight_hours", 200, 30000, ""),
    ("dispatch_first", "初次放行", "签发第一份签派单", "airline",
     "file", "dispatch_created", "dispatch_count", 1, 1000, ""),
    ("dispatch_20", "签派达人", "累计签发 20 份签派单", "airline",
     "bolt", "dispatch_created", "dispatch_count", 20, 6000, ""),
    ("bid_first", "竞标首胜", "第一次在航线竞标中中标", "economy",
     "key", "bid_won", "bid_won_count", 1, 5000, ""),
    ("bid_3", "竞标之王", "累计中标 3 条航线", "economy",
     "crown", "bid_won", "bid_won_count", 3, 20000, ""),
    ("market_first_sale", "首单二手", "第一次通过二手市场卖出飞机", "economy",
     "shop", "market_sold", "market_sold_count", 1, 3000, ""),
    ("market_seller_5", "二手行家", "累计卖出 5 架飞机", "economy",
     "trending", "market_sold", "market_sold_count", 5, 15000, ""),
    ("market_buyer_3", "机队扩充", "累计买入 3 架二手飞机", "economy",
     "plane", "market_bought", "market_bought_count", 3, 10000, ""),
    ("safety_first", "安全至上", "主动上报一次飞行事故/事件，配合调查", "safety",
     "shield", "incident_reported", "incident_count", 1, 2000, ""),
]

def seed_default_partner(conn) -> None:
    """首个默认合作伙伴，已存在时跳过。"""
    conn.execute(
        "INSERT INTO partners (name, url, logo, sort)"
        " SELECT 'CW 平台', 'https://www.cwflysim.cn', '', 1"
        " WHERE NOT EXISTS (SELECT 1 FROM partners WHERE url LIKE '%cwflysim%')"
    )
