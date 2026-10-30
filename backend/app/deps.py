"""FastAPI 依赖：登录态、角色能力，ADM/SUP/USER、管理员鉴权"""
from fastapi import Depends, HTTPException, Request

from .audit import log_event
from .database import get_conn
from .permissions import CAPABILITIES, is_staff
from .requestinfo import client_ip_from_request, user_agent
from .security import decode_token

USER_COLUMNS = ("id, cid, username, email, qq, avatar_url, role, rating, "
                "pilot_rank, status, is_controller, token_ver, created_at, "
                "equipped_title, equipped_badge, last_ip_v6, last_ip_v6_at")


def public_user(row) -> dict | None:
    """去掉敏感字段，输出与前端约定一致的用户对象"""
    if row is None:
        return None
    user = dict(row)
    user.pop("password_hash", None)
    user.pop("status", None)
    user.pop("token_ver", None)
    return user


def _load_user(uid: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row) if row else None


def require_auth(request: Request) -> dict:
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    if not token:
        raise HTTPException(401, "请先登录")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "登录已过期，请重新登录")

    user = _load_user(payload["uid"])
    if not user:
        raise HTTPException(401, "账号不存在")
    # 令牌版本化：改密/被重置密码后旧 token 全部失效
    if payload.get("ver", 0) != user["token_ver"]:
        raise HTTPException(401, "登录状态已失效，请重新登录")
    if user["status"] == "banned":
        raise HTTPException(403, "账号已被封禁，请联系管理员")
    if user["status"] == "deleted":
        raise HTTPException(403, "账号已注销")

    user.pop("status", None)
    user.pop("token_ver", None)
    # 访问日志溯源用：中间件在响应阶段读取，APOC 事件同款溯源能力：
    # IP → 会话 → 用户身份 三点关联
    request.state.user_id = user["id"]
    return user


def optional_user(request: Request) -> dict | None:
    """公开接口的可选登录态：有有效令牌就返回用户，没有就按匿名处理"""
    try:
        return require_auth(request)
    except HTTPException:
        return None


def require_admin(user: dict = Depends(require_auth)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "看起来你没有权限访问这个页面，可惜可惜")
    return user


def capabilities_for(user: dict) -> set:
    """该用户实际拥有的能力。

    三条分支：
      - role，ADM/SUP/USER 表达「职务」；
      - rating，OBS..I3/SUP/ADM 表达「管制等级」；
      - user_permissions 针对具体某个人单独放开或收回。
    计算方式： role ∪ rating ∪ 个人放开 − 个人收回 —— 个人收回可以覆盖前两条分支，
    这样「按人分配权限」页面上取消勾选才真的能收回权限。
    """
    caps, deny = set(), set()
    try:
        with get_conn() as conn:
            role = user.get("role") or ""
            if role == "admin":
                caps |= {c for c, _ in CAPABILITIES}
            elif role:
                caps |= {
                    r["capability"]
                    for r in conn.execute(
                        "SELECT capability FROM role_permissions WHERE role = ? AND allowed = 1",
                        (role,),
                    )
                }
            rating = user.get("rating") or ""
            if rating:
                caps |= {
                    r["capability"]
                    for r in conn.execute(
                        "SELECT capability FROM rating_permissions WHERE rating = ? AND allowed = 1",
                        (rating,),
                    )
                }
            uid = user.get("id")
            if uid:
                for r in conn.execute(
                    "SELECT capability, allowed FROM user_permissions WHERE user_id = ?", (uid,)
                ):
                    (caps.add(r["capability"]) if r["allowed"] else deny.add(r["capability"]))
    except Exception:
        return set()
    return caps - deny


def with_capabilities(user: dict | None) -> dict | None:
    """把能力清单挂到用户对象上，前端据此决定侧边栏显示哪些后台节点"""
    if user is None:
        return None
    out = dict(user)
    out["capabilities"] = sorted(capabilities_for(out))
    return out


def has_capability(user: dict, capability: str) -> bool:
    """按 role / rating / 个人覆盖三条分支判断，个人的收回优先级最高"""
    uid = user.get("id")
    try:
        with get_conn() as conn:
            if uid:
                row = conn.execute(
                    "SELECT allowed FROM user_permissions WHERE user_id = ? AND capability = ?",
                    (uid, capability),
                ).fetchone()
                if row is not None:
                    return bool(row["allowed"])   # 个人设置直接定论，不再看 role/rating
            if user.get("role") == "admin":
                return True
            if conn.execute(
                "SELECT 1 FROM role_permissions WHERE role = ? AND capability = ? AND allowed = 1",
                (user.get("role"), capability),
            ).fetchone():
                return True
            return bool(conn.execute(
                "SELECT 1 FROM rating_permissions WHERE rating = ? AND capability = ? AND allowed = 1",
                (user.get("rating"), capability),
            ).fetchone())
    except Exception:
        return False


def require_capability(capability: str):
    """能力校验依赖工厂；越权访问写入审计"""

    def checker(request: Request, user: dict = Depends(require_auth)) -> dict:
        if not has_capability(user, capability):
            log_event(
                "risk", "越权访问被拒绝",
                actor=user, target_type="capability", target_id=capability,
                detail=f"{request.method} {request.url.path}",
                ip=client_ip_from_request(request), ua=user_agent(request),
            )
            raise HTTPException(403, "无权限访问该功能")

        return user

    return checker


def require_staff(user: dict = Depends(require_auth)) -> dict:
    if not is_staff(user["role"]):
        raise HTTPException(403, "无权限访问")
    return user
