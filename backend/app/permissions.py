"""角色与能力矩阵：ADM，管理员 > SUP，主管 > USER，普通用户"""

ROLE_LABELS = {"admin": "ADM 管理员", "sup": "SUP 主管", "user": "USER 用户"}
ROLE_ORDER = {"admin": 3, "sup": 2, "user": 1}

# 能力清单，权限管理页可编辑
CAPABILITIES = [
    ("view_stats", "查看数据概览"),
    ("view_users", "查看用户列表与资料"),
    ("manage_users", "修改用户等级/职级，非敏感字段"),
    ("approve_sensitive", "审批角色变更 / 封禁 / 删除账户"),
    ("manage_permissions", "修改角色/等级能力矩阵"),
    ("manage_notices", "公告增删"),
    ("manage_events", "活动创建 / 取消 / 删除"),
    ("manage_archive", "飞圈事件检索审核与发布"),
    ("manage_tickets", "工单回复与关闭"),
    ("review_applications", "管制员 / 职员申请审核"),
    ("review_airlines", "虚拟航司建司审核"),
    ("manage_airline_funds", "航司货币发放 / 扣除，基础金、补贴"),
    ("manage_shop", "商城商品管理"),
    ("view_logs", "查看登录 / 注册 / 网络 / 审计日志"),
    ("export_logs", "导出日志数据"),
    ("view_surveys", "查看平台发展问卷反馈"),
]

# 能力简称：按用户分配权限时表头要放 14 列，全称会宽到没法看
CAPABILITY_SHORT = {
    "view_stats": "概览",
    "view_users": "用户查看",
    "manage_users": "等级管理",
    "approve_sensitive": "审批",
    "manage_permissions": "权限管理",
    "manage_notices": "公告",
    "manage_events": "活动",
    "manage_archive": "事件检索",
    "manage_tickets": "工单",
    "review_applications": "申请审核",
    "review_airlines": "航司审核",
    "manage_airline_funds": "航司货币",
    "manage_shop": "商城",
    "view_logs": "日志",
    "export_logs": "日志导出",
    "view_surveys": "问卷",
}

# 默认矩阵
DEFAULT_MATRIX = {
    "admin": {c for c, _ in CAPABILITIES},
    "sup": {
        "view_stats", "view_users", "manage_notices", "manage_events", "manage_archive",
        "manage_tickets", "review_applications", "review_airlines", "view_logs",
        "approve_sensitive", "view_surveys",
    },
    "user": set(),
}


def role_rank(role: str) -> int:
    return ROLE_ORDER.get(role, 0)


def is_staff(role: str) -> bool:
    return role in ("admin", "sup")


# ---------- 管制等级阶梯，VATSIM 体系----------
# 飞行员 = 无管制等级；OBS..I3 为管制员等级；SUP / ADM 为管理层等级
PILOT_RATING = "飞行员"
CONTROLLER_GRADES = ["OBS", "S1", "S2", "S3", "T2", "C1", "C2", "C3", "I1", "I2", "I3"]
STAFF_RATINGS = ["SUP", "ADM"]
RATINGS = [PILOT_RATING, *CONTROLLER_GRADES, *STAFF_RATINGS]


def is_valid_rating(rating: str) -> bool:
    return rating in RATINGS


def rating_rank(rating: str) -> int:
    """管制等级序，用于席位/职位的最低等级门槛比较。

    CONTROLLER_GRADES 按升序排列，序号越大等级越高；
    SUP / ADM 属管理职务等级，视为高于所有管制等级；
    飞行员或未知值返回 -1，未取得任何管制资格。
    """
    if rating in STAFF_RATINGS:
        return len(CONTROLLER_GRADES)
    return CONTROLLER_GRADES.index(rating) if rating in CONTROLLER_GRADES else -1


def affects_controller_flag(rating: str) -> bool:
    """该等级是否明确表示「是/不是管制员」。

    SUP / ADM 是管理职务等级，不改变管制员身份，返回 False 表示保持不变。
    """
    return rating == PILOT_RATING or rating in CONTROLLER_GRADES


# ---------- 飞行员等级阶梯 ----------
# 与航司考核晋升逻辑，airlines.RANK_REQUIREMENTS 保持一致
PILOT_RANKS = ["学员", "副驾驶", "机长", "教员"]


def is_valid_pilot_rank(rank: str) -> bool:
    return rank in PILOT_RANKS


# ---------- 管理后台的节点分布 ----------
# 每个后台节点需要哪项能力。侧边栏按这张表决定「这个节点给不给当前用户看」，
# 后端接口用同一套能力做校验，保证「看得到 = 调得通」。
ADMIN_NODES = [
    ("/admin/stats", "数据概览", "view_stats"),
    ("/admin/users", "用户管理", "view_users"),
    ("/admin/permissions", "权限管理", "manage_permissions"),
    ("/admin/approvals", "审批中心", "approve_sensitive"),
    ("/admin/applications/controller", "管制申请", "review_applications"),
    ("/admin/applications/staff", "职员申请", "review_applications"),
    ("/admin/airlines", "航司审核", "review_airlines"),
    ("/admin/events", "活动管理", "manage_events"),
    ("/admin/archive", "事件检索", "manage_archive"),
    ("/admin/tickets", "工单管理", "manage_tickets"),
    ("/admin/notices", "公告管理", "manage_notices"),
    ("/admin/partners", "合作伙伴", "manage_notices"),
    ("/admin/shop", "商城管理", "manage_shop"),
    ("/admin/logs-login", "登录日志", "view_logs"),
    ("/admin/logs-register", "注册日志", "view_logs"),
    ("/admin/logs-network", "网络日志", "view_logs"),
    ("/admin/logs-audit", "审计日志", "view_logs"),
    ("/admin/surveys", "问卷反馈", "view_surveys"),
]


# ---------- rating 权限分支 ----------
# 与 role 分支，ADM/SUP/USER 并行：任一分支授予即拥有该能力。
# 默认只有管理等级，SUP / ADM 拿到全部后台节点，其余管制等级一律为空 ——
# 需要时在「权限管理 → 管制等级矩阵」里逐项放开。
DEFAULT_RATING_MATRIX = {
    rating: ({c for c, _ in CAPABILITIES} if rating in STAFF_RATINGS else set())
    for rating in RATINGS
}


def admin_nodes_for(caps) -> list:
    """按能力集合算出实际可见的后台节点路径"""
    caps = set(caps or ())
    return [to for to, _label, cap in ADMIN_NODES if cap in caps]

