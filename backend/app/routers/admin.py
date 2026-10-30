"""管理后台 API：数据概览、用户管理、权限管理、审批中心、
申请审核，管制/职员、活动管理、公告管理、登录/注册/网络/审计日志"""
import re
import secrets
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..approvals import TYPE_LABELS, create_approval, vote_approval
from ..audit import CATEGORY_LABELS, log_event
from ..database import get_conn
from ..deps import has_capability, require_admin, require_capability
from ..mailer import notify_user
from ..permissions import (ADMIN_NODES, CAPABILITIES, CAPABILITY_SHORT,
                           PILOT_RANKS, PILOT_RATING, RATINGS, ROLE_LABELS,
                           affects_controller_flag, is_valid_pilot_rank,
                           is_valid_rating)
from ..requestinfo import client_ip_from_request, user_agent
def _audit(request, category: str, action: str, *, actor, target_type: str = "",
           target_id="", detail: str = "") -> None:
    """与 airlines._audit 同构的审计包装：补齐请求 IP/UA 后落审计日志"""
    log_event(category, action, actor=actor, target_type=target_type, target_id=target_id,
              detail=detail, ip=client_ip_from_request(request), ua=user_agent(request))
from ..security import hash_password
from ..text import clean

router = APIRouter(prefix="/api/admin", tags=["admin"])

USER_LIST_COLUMNS = (
    "id, cid, username, email, qq, avatar_url, role, rating, pilot_rank, status,"
    " is_controller, created_at, reg_ip, reg_geo, reg_fingerprint, reg_ua,"
    " last_login_ip, last_login_geo, last_login_fingerprint, last_login_at,"
    " last_ip_v6, last_ip_v6_at"
)


# ==================== 数据概览 ====================

@router.get("/stats")
def stats(user: dict = Depends(require_capability("view_stats"))):
    with get_conn() as conn:
        def count(sql: str) -> int:
            return conn.execute(sql).fetchone()["c"]

        trend = conn.execute(
            "SELECT date(created_at) AS day, COUNT(*) AS count FROM users"
            " WHERE created_at >= datetime('now','-6 day','localtime')"
            " GROUP BY date(created_at) ORDER BY day"
        ).fetchall()
        pending_approvals = count("SELECT COUNT(*) c FROM approvals WHERE status = 'pending'")
        today_logins = count(
            "SELECT COUNT(*) c FROM login_logs WHERE success = 1 AND created_at >= date('now','localtime')"
        )
        failed_logins = count(
            "SELECT COUNT(*) c FROM login_logs WHERE success = 0 AND created_at >= datetime('now','-1 day','localtime')"
        )
        risk_events = count(
            "SELECT COUNT(*) c FROM audit_logs WHERE category = 'risk' AND created_at >= datetime('now','-1 day','localtime')"
        )

    return {
        "ok": True,
        "stats": {
            "total": count_all("users"),
            "today": count_today("users"),
            "controllers": count_all("users", "is_controller = 1"),
            "pendingApps": count_all("applications", "status = 'pending'"),
            "pendingApprovals": pending_approvals,
            "openTickets": count_all("tickets", "status != 'closed'"),
            "events": count_all("events", "status IN ('upcoming','ongoing')"),
            "routes": count_all("routes"),
            "airlines": count_all("airlines", "status = 'approved'"),
            "todayLogins": today_logins,
            "failedLogins": failed_logins,
            "riskEvents": risk_events,
        },
        "trend": [dict(t) for t in trend],
    }


def _q(sql: str, args: tuple = ()) -> int:
    with get_conn() as conn:
        return conn.execute(sql, args).fetchone()["c"]


def count_all(table: str, where: str = "1=1") -> int:
    return _q(f"SELECT COUNT(*) c FROM {table} WHERE {where}")


def count_today(table: str) -> int:
    return _q(f"SELECT COUNT(*) c FROM {table} WHERE created_at >= date('now','localtime')")


# ==================== 用户管理 ====================

@router.get("/users")
def list_users(q: str = "", role: str = "", status: str = "",
                     user: dict = Depends(require_capability("view_users"))):
    from ..requestinfo import classify_ua

    like = f"%{q.strip()}%"
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {USER_LIST_COLUMNS} FROM users"
            " WHERE (? = '' OR cid LIKE ? OR username LIKE ? OR email LIKE ? OR CAST(id AS TEXT) LIKE ?)"
            " AND (? = '' OR role = ?) AND (? = '' OR status = ?)"
            " ORDER BY id DESC LIMIT 300",
            (q.strip(), like, like, like, like, role, role, status, status),
        ).fetchall()
    users = []
    for r in rows:
        item = dict(r)
        item["reg_ua_label"], item["reg_ua_bot"] = classify_ua(item.get("reg_ua") or "")
        users.append(item)
    # 一并下发给前端做下拉选项，避免两端各维护一份
    return {"ok": True, "users": users, "ratings": RATINGS, "pilotRanks": PILOT_RANKS}


class UserPatchBody(BaseModel):
    rating: str | None = Field(None, max_length=8)
    pilotRank: str | None = Field(None, max_length=16)
    resetPassword: bool = False


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatchBody, request: Request,
                     admin: dict = Depends(require_capability("manage_users"))):
    """仅允许直接修改非敏感字段；角色变更/封禁/删除必须走审批"""
    with get_conn() as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "用户不存在")

        # 越权防护：只有 role=admin 的操作者才能动管理员账号。
        # 否则拿到 manage_users 能力的 SUP 可以直接重置管理员密码接管全站。
        if admin["role"] != "admin" and target["role"] == "admin":
            raise HTTPException(403, "不能对管理员账号执行该操作")

        rating_change = ""  # 等级实际变化时填充「旧 → 新」
        rank_change = ""    # 职级实际变化时填充
        # 管制等级 = banned：不直接改等级字段，而是发起封禁审批，双人复核，通过后
        # 自动执行封禁并邮件通知。重复发起由 create_approval 的 pending 去重拦截
        if body.rating == "banned":
            if target["status"] == "banned":
                raise HTTPException(400, "该账号已被封禁")
            approval_id = create_approval(
                type_="ban", target_user_id=user_id, payload={},
                reason=f"用户管理将管制等级调整为 banned 触发封禁审议，操作人 {admin['username']}",
                initiator=admin, ip=client_ip_from_request(request), ua=user_agent(request),
            )
            log_event(
                "permission", "发起封禁审批，管制等级=banned", actor=admin,
                target_type="user", target_id=user_id,
                detail=f"{target['username']} CID {target['cid']} · 审批 #{approval_id}",
            )
            return {"ok": True, "message": "已发起封禁审批，需另一位管理员复核通过后生效"}
        if body.rating:
            rating = clean(body.rating, 8)
            if not is_valid_rating(rating):
                raise HTTPException(400, f"无效的管制等级：{rating}")
            old_rating = target["rating"]
            conn.execute("UPDATE users SET rating = ? WHERE id = ?", (rating, user_id))
            if old_rating != rating:
                rating_change = f"{old_rating} → {rating}"
            # 等级本身表明管制员身份：飞行员=非管制，OBS~I3=管制员；SUP/ADM 不动该标记
            if affects_controller_flag(rating):
                conn.execute(
                    "UPDATE users SET is_controller = ? WHERE id = ?",
                    (0 if rating == PILOT_RATING else 1, user_id),
                )
        if body.pilotRank:
            rank = clean(body.pilotRank, 16)
            if not is_valid_pilot_rank(rank):
                raise HTTPException(400, f"无效的飞行员等级：{rank}")
            old_rank = target["pilot_rank"]
            conn.execute("UPDATE users SET pilot_rank = ? WHERE id = ?", (rank, user_id))
            if old_rank != rank:
                rank_change = f"{old_rank} → {rank}"

        new_password = ""
        if body.resetPassword:
            # secrets 替换 random：临时密码要防爆破，token_urlsafe 有 ~5.9bit/字符熵，
            # random.randint 1000,9999 只有约 10bit，可被瞬间穷举。
            # 保留 Ctyfly@ 前缀满足站内「含字母数字 ≥8 位」的复杂度要求。
            new_password = f"Ctyfly@{secrets.token_urlsafe(9)}"
            conn.execute(
                "UPDATE users SET password_hash = ?, token_ver = token_ver + 1 WHERE id = ?",
                (hash_password(new_password), user_id),
            )

    # 权限/等级变更通知：写明原值 → 现值，站长要求
    changes = []
    if rating_change:
        changes.append(f"管制等级：{rating_change}")
    if rank_change:
        changes.append(f"飞行员职级：{rank_change}")
    if changes:
        try:
            notify_user(
                user_id, "你的账号权限已变更",
                "管理员已调整你的账号信息：\n" + "\n".join(changes)
                + "\n如有疑问，请联系管理员。",
            )
        except Exception:
            pass  # 通知失败不影响变更本身
    if new_password:
        try:
            notify_user(
                user_id, "你的密码已被管理员重置",
                "你的账号密码已被管理员重置，请向管理员获取临时密码，"
                "登录后请尽快在个人中心修改。",
            )
        except Exception:
            pass  # 通知失败不影响重置本身

    log_event(
        "permission", "修改用户资料", actor=admin, target_type="user", target_id=user_id,
        detail=f"{target['username']}，CID {target['cid']}"
               + (f" · 等级={body.rating}" if body.rating else "")
               + (f" · 职级={body.pilotRank}" if body.pilotRank else "")
               + (" · 重置密码" if body.resetPassword else ""),
        ip=client_ip_from_request(request), ua=user_agent(request),
    )
    return {"ok": True, **({"newPassword": new_password} if new_password else {})}


class ApprovalCreateBody(BaseModel):
    type: str = Field("", max_length=20)
    role: str | None = Field(None, max_length=8)
    reason: str = Field("", max_length=200)


@router.post("/users/{user_id}/approvals")
def request_user_change(user_id: int, body: ApprovalCreateBody, request: Request,
                              admin: dict = Depends(require_capability("approve_sensitive"))):
    """发起审批：角色变更 / 封禁 / 删除账户"""
    if body.type not in TYPE_LABELS:
        raise HTTPException(400, "无效的审批类型")
    if user_id == admin["id"]:
        raise HTTPException(400, "不能对自己发起该类审批")
    if not body.reason.strip():
        raise HTTPException(400, "请填写申请理由")
    # 越权防护：非 role=admin 的操作者不能对管理员账号发起角色变更/封禁/删除
    with get_conn() as conn:
        target_role = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target_role:
        raise HTTPException(404, "用户不存在")
    if admin["role"] != "admin" and target_role["role"] == "admin":
        raise HTTPException(403, "不能对管理员账号执行该操作")

    payload = {}
    if body.type == "role_change":
        if body.role not in ("user", "sup", "admin"):
            raise HTTPException(400, "无效的角色")
        payload = {"role": body.role}

    approval_id = create_approval(
        type_=body.type, target_user_id=user_id, payload=payload,
        reason=clean(body.reason, 200), initiator=admin,
        ip=client_ip_from_request(request), ua=user_agent(request),
    )
    return {"ok": True, "id": approval_id, "message": "已提交审批，需 2 名管理员/主管复核通过后生效"}


# ==================== 审批中心 ====================

@router.get("/approvals")
def list_approvals(status: str = "pending", user: dict = Depends(require_capability("approve_sensitive"))):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.*, t.cid AS target_cid, t.username AS target_username, t.role AS target_role"
            " FROM approvals a LEFT JOIN users t ON t.id = a.target_user_id"
            " WHERE (? = '' OR a.status = ?) ORDER BY a.id DESC LIMIT 200",
            (status, status),
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            votes = conn.execute(
                "SELECT voter_id, voter_name, vote, comment, created_at FROM approval_votes"
                " WHERE approval_id = ? ORDER BY id", (r["id"],),
            ).fetchall()
            item["votes"] = [dict(v) for v in votes]
            item["type_label"] = TYPE_LABELS.get(r["type"], r["type"])
            item["my_voted"] = any(v["voter_id"] == user["id"] for v in votes)
            item["can_vote"] = (
                r["status"] == "pending" and r["initiator_id"] != user["id"]
                and r["target_user_id"] != user["id"] and not item["my_voted"]
            )
            result.append(item)
    return {"ok": True, "approvals": result}


class VoteBody(BaseModel):
    vote: str = Field("", max_length=10)
    comment: str = Field("", max_length=200)


@router.post("/approvals/{approval_id}/vote")
def vote(approval_id: int, body: VoteBody, request: Request,
               staff: dict = Depends(require_capability("approve_sensitive"))):
    result = vote_approval(
        approval_id=approval_id, voter=staff, vote=body.vote,
        comment=clean(body.comment, 200),
        ip=client_ip_from_request(request), ua=user_agent(request),
    )
    return {**result, **({"message": "复核通过并已执行"} if result.get("finished") and result.get("status") == "approved"
                         else {"message": "已驳回" if result.get("status") == "rejected" else "已记录，等待其他复核人"})}


# ==================== 权限管理 ====================

@router.get("/permissions")
def list_permissions(user: dict = Depends(require_capability("manage_permissions"))):
    with get_conn() as conn:
        role_rows = conn.execute("SELECT role, capability, allowed FROM role_permissions").fetchall()
        rating_rows = conn.execute("SELECT rating, capability, allowed FROM rating_permissions").fetchall()
        counts = conn.execute(
            "SELECT role, COUNT(*) c FROM users WHERE status = 'active' GROUP BY role"
        ).fetchall()
        rating_counts = conn.execute(
            "SELECT rating, COUNT(*) c FROM users WHERE status = 'active' GROUP BY rating"
        ).fetchall()

    matrix = {r: {} for r in ("admin", "sup", "user")}
    for r in role_rows:
        matrix.setdefault(r["role"], {})[r["capability"]] = bool(r["allowed"])

    # rating 分支：键是管制等级，值是该等级在后台各节点上的开关
    rating_matrix = {x: {} for x in RATINGS}
    for r in rating_rows:
        rating_matrix.setdefault(r["rating"], {})[r["capability"]] = bool(r["allowed"])

    return {
        "ok": True,
        "capabilities": [{"key": k, "label": v} for k, v in CAPABILITIES],
        "roles": [{"key": k, "label": v} for k, v in ROLE_LABELS.items()],
        "ratings": [{"key": r, "label": r} for r in RATINGS],
        "matrix": matrix,
        "ratingMatrix": rating_matrix,
        # 节点分布：后台每个菜单节点需要哪项能力
        "nodes": [{"to": to, "label": label, "cap": cap} for to, label, cap in ADMIN_NODES],
        "roleCounts": {r["role"]: r["c"] for r in counts},
        "ratingCounts": {r["rating"]: r["c"] for r in rating_counts},
    }


class RatingPermissionBody(BaseModel):
    rating: str = Field("", max_length=16)
    capability: str = Field("", max_length=32)
    allowed: bool = False


@router.put("/rating-permissions")
def update_rating_permission(body: RatingPermissionBody, request: Request,
                                   admin: dict = Depends(require_capability("manage_permissions"))):
    """rating 权限分支：按管制等级授权，与 role 矩阵并行，任一授予即拥有"""
    if body.rating not in RATINGS:
        raise HTTPException(400, "无效的管制等级")
    if body.capability not in [c for c, _ in CAPABILITIES]:
        raise HTTPException(400, "无效的能力项")

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO rating_permissions (rating, capability, allowed) VALUES (?, ?, ?)"
            " ON CONFLICT(rating, capability) DO UPDATE SET allowed = excluded.allowed",
            (body.rating, body.capability, 1 if body.allowed else 0),
        )
    log_event(
        "permission", "修改管制等级能力矩阵", actor=admin, target_type="rating", target_id=body.rating,
        detail=f"{body.capability} = {'允许' if body.allowed else '禁止'}",
        ip=client_ip_from_request(request), ua=user_agent(request),
    )
    return {"ok": True}


# ---------- 按用户分配细分权限 ----------

@router.get("/user-permissions")
def list_user_permissions(q: str = "", role: str = "",
                                user: dict = Depends(require_capability("manage_permissions"))):
    """用户列表 + 每人当前的有效能力，含 role/rating 继承与个人覆盖"""
    with get_conn() as conn:
        sql = "SELECT id, cid, username, role, rating, status FROM users WHERE status != 'deleted'"
        args: list = []
        if q:
            sql += " AND (cid LIKE ? OR username LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        if role:
            sql += " AND role = ?"
            args.append(role)
        sql += " ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'sup' THEN 1 ELSE 2 END, cid"
        rows = [dict(r) for r in conn.execute(sql, args)]

        # 一次取齐三条分支，避免每个用户各查一遍
        role_caps: dict = {}
        for r in conn.execute("SELECT role, capability FROM role_permissions WHERE allowed = 1"):
            role_caps.setdefault(r["role"], set()).add(r["capability"])
        rating_caps: dict = {}
        for r in conn.execute("SELECT rating, capability FROM rating_permissions WHERE allowed = 1"):
            rating_caps.setdefault(r["rating"], set()).add(r["capability"])
        overrides: dict = {}
        for r in conn.execute("SELECT user_id, capability, allowed FROM user_permissions"):
            overrides.setdefault(r["user_id"], {})[r["capability"]] = bool(r["allowed"])
        counts = conn.execute(
            "SELECT role, COUNT(*) c FROM users WHERE status != 'deleted' GROUP BY role"
        ).fetchall()

    all_caps = {c for c, _ in CAPABILITIES}
    for u in rows:
        base = set()
        if u["role"] == "admin":
            base |= all_caps
        else:
            base |= role_caps.get(u["role"], set())
        base |= rating_caps.get(u["rating"], set())
        ov = overrides.get(u["id"], {})
        allow = {c for c, ok in ov.items() if ok}
        deny = {c for c, ok in ov.items() if not ok}
        u["overrides"] = ov
        u["effective"] = sorted((base | allow) - deny)

    return {
        "ok": True,
        "users": rows,
        "capabilities": [
            {"key": k, "label": v, "short": CAPABILITY_SHORT.get(k, v)} for k, v in CAPABILITIES
        ],
        "roleCounts": {r["role"]: r["c"] for r in counts},
        "totalCount": len(rows),
    }


class UserPermissionBody(BaseModel):
    userId: int = 0
    capability: str = Field("", max_length=32)
    allowed: bool = False


@router.put("/user-permissions")
def update_user_permission(body: UserPermissionBody, request: Request,
                                 admin: dict = Depends(require_capability("manage_permissions"))):
    """针对具体某个人放开或收回某项能力，个人设置优先级最高"""
    if body.capability not in [c for c, _ in CAPABILITIES]:
        raise HTTPException(400, "无效的能力项")
    # 防自锁：不能收回自己的「权限管理」，否则这一页再也进不来了
    if body.userId == admin["id"] and body.capability == "manage_permissions" and not body.allowed:
        raise HTTPException(400, "不能收回自己的「权限管理」能力，否则将无法再进入本页")
    # 防提权，节点级自限：不能授予自己没有的权限，ADM 全能豁免
    if body.allowed and admin["role"] != "admin" and not has_capability(admin, body.capability):
        log_event(
            "risk", "尝试授予自己没有的权限", actor=admin, target_type="user",
            target_id=body.userId, detail=f"{body.capability}",
            ip=client_ip_from_request(request), ua=user_agent(request),
        )
        raise HTTPException(403, "你不能授予自己没有的权限")

    with get_conn() as conn:
        target = conn.execute(
            "SELECT username, cid FROM users WHERE id = ?", (body.userId,)
        ).fetchone()
        if not target:
            raise HTTPException(404, "用户不存在")
        prev = conn.execute(
            "SELECT allowed FROM user_permissions WHERE user_id = ? AND capability = ?",
            (body.userId, body.capability),
        ).fetchone()
        # 无变化则不发通知，同值覆盖视为未调整
        changed = not (prev and (1 if prev["allowed"] else 0) == (1 if body.allowed else 0))
        conn.execute(
            "INSERT INTO user_permissions (user_id, capability, allowed) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, capability) DO UPDATE SET allowed = excluded.allowed",
            (body.userId, body.capability, 1 if body.allowed else 0),
        )
        if changed:
            cap_label = next((label for cap, label in CAPABILITIES if cap == body.capability), body.capability)
            perm_action = "已放行" if body.allowed else "已收回"

    log_event(
        "permission", "调整用户细分权限", actor=admin, target_type="user", target_id=body.userId,
        detail=f"{target['username']}，CID {target['cid']} · {body.capability}: "
               f"改前={'允许' if prev and prev['allowed'] else ('禁止' if prev else '角色默认')} "
               f"→ 改后={'允许' if body.allowed else '禁止'}",
        ip=client_ip_from_request(request), ua=user_agent(request),
    )
    if changed:
        try:
            notify_user(
                body.userId, "你的权限已更新",
                f"管理员已对你的「{cap_label}」能力做出调整：{perm_action}。\n"
                f"刷新页面后即可生效。如有疑问，请联系管理员。",
            )
        except Exception:
            pass  # 通知失败不影响权限变更本身
    return {"ok": True}


class PermissionBody(BaseModel):
    role: str = Field("", max_length=8)
    capability: str = Field("", max_length=32)
    allowed: bool = False


@router.put("/permissions")
def update_permission(body: PermissionBody, request: Request,
                            admin: dict = Depends(require_capability("manage_permissions"))):
    if body.role not in ROLE_LABELS or body.role == "admin":
        raise HTTPException(400, "ADM 权限不可修改")
    if body.capability not in [c for c, _ in CAPABILITIES]:
        raise HTTPException(400, "无效的能力项")

    # 防提权，节点级自限：不能授予自己没有的权限，ADM 全能豁免
    if body.allowed and admin["role"] != "admin" and not has_capability(admin, body.capability):
        log_event(
            "risk", "尝试授予自己没有的权限", actor=admin, target_type="role",
            target_id=body.role, detail=f"{body.capability}",
            ip=client_ip_from_request(request), ua=user_agent(request),
        )
        raise HTTPException(403, "你不能授予自己没有的权限")

    with get_conn() as conn:
        prev = conn.execute(
            "SELECT allowed FROM role_permissions WHERE role = ? AND capability = ?",
            (body.role, body.capability),
        ).fetchone()
        conn.execute(
            "INSERT INTO role_permissions (role, capability, allowed) VALUES (?, ?, ?)"
            " ON CONFLICT(role, capability) DO UPDATE SET allowed = excluded.allowed",
            (body.role, body.capability, 1 if body.allowed else 0),
        )
    log_event(
        "permission", "修改角色能力矩阵", actor=admin, target_type="role", target_id=body.role,
        detail=f"{body.capability}: 改前={'允许' if prev and prev['allowed'] else ('禁止' if prev else '默认')} "
               f"→ 改后={'允许' if body.allowed else '禁止'}",
        ip=client_ip_from_request(request), ua=user_agent(request),
    )
    return {"ok": True}


# ==================== 申请审核，管制员 / 职员 ====================

@router.get("/applications")
def list_applications(status: str = "", type: str = "",
                            user: dict = Depends(require_capability("review_applications"))):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.*, u.cid, u.username, u.avatar_url, u.email FROM applications a"
            " JOIN users u ON u.id = a.user_id"
            " WHERE (? = '' OR a.status = ?) AND (? = '' OR a.type = ?)"
            " ORDER BY a.id DESC LIMIT 200",
            (status, status, type, type),
        ).fetchall()
    return {"ok": True, "applications": [dict(r) for r in rows]}


class ReviewBody(BaseModel):
    action: str = Field("", max_length=10)
    note: str = Field("", max_length=200)


# ---------- 面试流程，职员申请：先面试，再决定通过 / 驳回 ----------
# 站长 2026-10-05 要求：职员申请必须先安排面试，邮件告知两个可用时间，
# 面试完成后才允许给出通过/驳回结论；不能直接点通过/驳回。

def _norm_interview_at(raw: str) -> str:
    """归一化面试时间：接受 'YYYY-MM-DDTHH:mm' 或 'YYYY-MM-DD HH:mm'，统一存前者。"""
    s = (raw or "").strip().replace(" ", "T")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", s):
        raise HTTPException(400, "面试时间格式不正确，请重新选择")
    return s


def _pretty_at(s: str) -> str:
    return (s or "").replace("T", " ")


class InterviewBody(BaseModel):
    at1: str = Field("", max_length=32)
    at2: str = Field("", max_length=32)


@router.post("/applications/{application_id}/interview")
def arrange_interview(application_id: int, body: InterviewBody, request: Request,
                            staff: dict = Depends(require_capability("review_applications"))):
    """安排面试：记录两个可用时间，并把面试邀约邮件发给申请人。

    通知走 notify_user，进程内队列异步发送—— 在请求处理函数里调用是安全的；
    注意千万别在 ad-hoc 脚本，ssh ... python -c 里用它，进程会在邮件发出前退出
    运维手册血泪清单 §8 / 交接文档 §2.8 记过两次丢邮件。
    """
    at1 = _norm_interview_at(body.at1)
    at2 = _norm_interview_at(body.at2)
    if at1 == at2:
        raise HTTPException(400, "两个面试时间不能相同")
    now_local = datetime.now().strftime("%Y-%m-%dT%H:%M")
    if at1 <= now_local or at2 <= now_local:
        raise HTTPException(400, "面试时间必须晚于当前时间")

    with get_conn() as conn:
        app = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if not app:
            raise HTTPException(404, "申请不存在")
        if app["type"] != "staff":
            raise HTTPException(400, "仅职员申请需要面试")
        if app["status"] != "pending":
            raise HTTPException(400, "该申请已处理，无法再安排面试")
        applicant = conn.execute(
            "SELECT cid, username, email FROM users WHERE id = ?", (app["user_id"],)
        ).fetchone()
        conn.execute(
            "UPDATE applications SET interview_status = 'sent', interview_at1 = ?,"
            " interview_at2 = ?, interview_sent_at = datetime('now','localtime'),"
            " interview_done_at = NULL, interview_by = ? WHERE id = ?",
            (at1, at2, staff["id"], application_id),
        )

    name = app["nickname"] or applicant["username"]
    notify_user(
        app["user_id"], "你的职员申请：面试时间安排",
        f"你好 {name}：\n"
        f"我们已收到你的职员申请，想约你做一次线上面试。以下两个时间请任选一个方便的：\n\n"
        f"  1. {_pretty_at(at1)}\n"
        f"  2. {_pretty_at(at2)}\n\n"
        f"请通过 QQ 群或直接回复本邮件告知你选择的时间；两个时间都不方便的话，"
        f"也请告知你可用的时间，我们会另行安排。\n"
        f"面试完成后我们才会给出审核结论，感谢你的耐心配合。",
    )
    _audit(request, "content", "发送面试邀约", actor=staff, target_type="application",
           target_id=application_id,
           detail=f"{name}，CID {applicant['cid']}· 备选 {_pretty_at(at1)} / {_pretty_at(at2)}")
    return {"ok": True, "message": "面试邀约已发送，邮件已发出",
            "interviewStatus": "sent", "at1": at1, "at2": at2}


@router.post("/applications/{application_id}/interview/done")
def finish_interview(application_id: int, request: Request,
                           staff: dict = Depends(require_capability("review_applications"))):
    """标记面试已完成 —— 完成后才允许通过/驳回，门禁在 review_application 里。"""
    with get_conn() as conn:
        app = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if not app:
            raise HTTPException(404, "申请不存在")
        if app["type"] != "staff":
            raise HTTPException(400, "仅职员申请需要面试")
        if app["interview_status"] == "done":
            return {"ok": True, "message": "面试此前已标记完成", "interviewStatus": "done"}
        if app["interview_status"] != "sent":
            raise HTTPException(400, "请先发送面试邀约，再标记面试完成")
        conn.execute(
            "UPDATE applications SET interview_status = 'done',"
            " interview_done_at = datetime('now','localtime') WHERE id = ?",
            (application_id,),
        )
    _audit(request, "content", "标记面试完成", actor=staff, target_type="application",
           target_id=application_id,
           detail=f"备选时间 {_pretty_at(app['interview_at1'])} / {_pretty_at(app['interview_at2'])}")
    return {"ok": True, "message": "已标记面试完成，现在可以通过或驳回",
            "interviewStatus": "done"}


@router.patch("/applications/{application_id}")
def review_application(application_id: int, body: ReviewBody, request: Request,
                             staff: dict = Depends(require_capability("review_applications"))):
    if body.action not in ("approve", "reject"):
        raise HTTPException(400, "无效操作")
    rating_change = ""  # 仅管制员申请通过且等级实际变化时填充

    with get_conn() as conn:
        app = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if not app:
            raise HTTPException(404, "申请不存在")
        if app["status"] != "pending":
            raise HTTPException(400, "该申请已处理")
        # 门禁：职员申请必须先完成面试才能给结论，通过/驳回都拦
        if app["type"] == "staff" and (app["interview_status"] or "") != "done":
            raise HTTPException(
                400,
                "该职员申请尚未完成面试：请先点「面试」发送邀约，面试结束后点「面试已完成」，"
                "再决定通过或驳回",
            )

        conn.execute(
            "UPDATE applications SET status = ?, review_note = ?, reviewed_by = ?,"
            " reviewed_at = datetime('now','localtime') WHERE id = ?",
            ("approved" if body.action == "approve" else "rejected",
             clean(body.note, 200), staff["id"], application_id),
        )
        if body.action == "approve":
            if app["type"] == "controller":
                # 通过管制员申请：默认给入门等级 OBS，已有管制等级则保留
                current = conn.execute(
                    "SELECT rating FROM users WHERE id = ?", (app["user_id"],)
                ).fetchone()
                keep = current and current["rating"] in RATINGS and current["rating"] != PILOT_RATING
                old_rating = current["rating"] if current else ""
                new_rating = current["rating"] if keep else "OBS"
                conn.execute(
                    "UPDATE users SET is_controller = 1, rating = ? WHERE id = ?",
                    (new_rating, app["user_id"]),
                )
                if old_rating != new_rating:
                    rating_change = f"{old_rating or '无'} → {new_rating}"
            # 职员申请：仅标记通过，不自动授予任何角色/权限——
            # 权限由管理员在「用户管理 / 权限管理」中按需单独配置
    passed = body.action == "approve"
    kind = "管制员" if app["type"] == "controller" else "职员"
    note = clean(body.note, 200)
    # 职员申请通过不再自动授予 SUP：权限由管理员单独配置，邮件中说明
    staff_no_perm = app["type"] == "staff" and passed
    notify_user(
        app["user_id"],
        f"你的{kind}注册申请{'已通过' if passed else '未通过'}",
        (f"你提交的{kind}申请已被管理员{'通过' if passed else '驳回'}。"
         + (f"\n审核意见：{note}" if note else "")
         + (f"\n管制等级变更：{rating_change}。" if passed and app["type"] == "controller" and rating_change else "")
         + ("\n相关权限将由管理员单独配置，配置完成后即可使用对应功能。" if staff_no_perm else "")
         + ("" if passed else "\n如需再次申请，可登录后在个人中心重新提交。")),
    )

    log_event(
        "content", f"{'通过' if body.action == 'approve' else '驳回'}"
                   f"{'管制员' if app['type'] == 'controller' else '职员'}申请",
        actor=staff, target_type="application", target_id=application_id,
        detail=f"申请人 uid={app['user_id']} · {clean(body.note, 100)}",
        ip=client_ip_from_request(request), ua=user_agent(request),
    )
    return {"ok": True}


# ==================== 活动管理 ====================

@router.get("/events")
def list_events(user: dict = Depends(require_capability("manage_events"))):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT e.*, u.username AS creator,"
            " (SELECT COUNT(*) FROM event_signups s WHERE s.event_id = e.id) AS signup_count"
            " FROM events e LEFT JOIN users u ON u.id = e.created_by"
            " ORDER BY e.start_time DESC LIMIT 200"
        ).fetchall()
    return {"ok": True, "events": [dict(r) for r in rows]}


class EventBody(BaseModel):
    title: str = Field("", max_length=120)
    description: str = Field("", max_length=2000)
    dep: str = Field("", max_length=8)
    arr: str = Field("", max_length=8)
    startTime: str = Field("", max_length=32)
    endTime: str = Field("", max_length=32)
    route: str = Field("", max_length=200)
    distanceNm: float | None = Field(None, ge=0)
    notams: str = Field("", max_length=500)


@router.post("/events")
def create_event(body: EventBody, request: Request,
                       staff: dict = Depends(require_capability("manage_events"))):
    title = clean(body.title, 100)
    if not title:
        raise HTTPException(400, "请填写活动标题")
    if not body.startTime or not body.endTime:
        raise HTTPException(400, "请选择活动起止时间")

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO events (title, description, dep, arr, start_time, end_time, status,"
            " created_by, route, distance_nm, notams)"
            " VALUES (?, ?, ?, ?, ?, ?, 'upcoming', ?, ?, ?, ?)",
            (title, clean(body.description, 2000), clean(body.dep, 4).upper(), clean(body.arr, 4).upper(),
             body.startTime, body.endTime, staff["id"],
             clean(body.route, 200), body.distanceNm, clean(body.notams, 500)),
        )
    log_event("content", "创建活动", actor=staff, target_type="event", target_id=cur.lastrowid,
              detail=f"{title} · {body.startTime} ~ {body.endTime}",
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True, "id": cur.lastrowid}


@router.put("/events/{event_id}")
def update_event_info(event_id: int, body: EventBody, request: Request,
                            staff: dict = Depends(require_capability("manage_events"))):
    """编辑活动基础信息与简报字段，航路 / 飞行距离 / NOTAMS"""
    title = clean(body.title, 100)
    if not title:
        raise HTTPException(400, "请填写活动标题")
    if not body.startTime or not body.endTime:
        raise HTTPException(400, "请选择活动起止时间")

    with get_conn() as conn:
        row = conn.execute("SELECT title FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "活动不存在")
        conn.execute(
            "UPDATE events SET title = ?, description = ?, dep = ?, arr = ?,"
            " start_time = ?, end_time = ?, route = ?, distance_nm = ?, notams = ?"
            " WHERE id = ?",
            (title, clean(body.description, 2000), clean(body.dep, 4).upper(),
             clean(body.arr, 4).upper(), body.startTime, body.endTime,
             clean(body.route, 200), body.distanceNm, clean(body.notams, 500), event_id),
        )
    log_event("content", "编辑活动信息", actor=staff, target_type="event", target_id=event_id,
              detail=f"{row['title']} → {title}",
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True}


class EventStatusBody(BaseModel):
    status: str = Field("", max_length=16)


@router.patch("/events/{event_id}")
def update_event(event_id: int, body: EventStatusBody, request: Request,
                       staff: dict = Depends(require_capability("manage_events"))):
    if body.status not in ("upcoming", "ongoing", "ended", "cancelled"):
        raise HTTPException(400, "无效的活动状态")
    with get_conn() as conn:
        row = conn.execute("SELECT title FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "活动不存在")
        conn.execute("UPDATE events SET status = ? WHERE id = ?", (body.status, event_id))
    log_event("content", f"活动状态改为 {body.status}", actor=staff, target_type="event",
              target_id=event_id, detail=row["title"],
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True}


@router.delete("/events/{event_id}")
def delete_event(event_id: int, request: Request,
                       staff: dict = Depends(require_capability("manage_events"))):
    with get_conn() as conn:
        row = conn.execute("SELECT title FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise HTTPException(404, "活动不存在")
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        # 席位表历史上没有 REFERENCES events id 外键，报名/简报有 CASCADE，席位没有，
        # 不显式清理会在库里留下孤儿席位，生产 event 2 / 测试 event 3 都踩过，
        # 因此这里必须与活动删除同事务清理。
        conn.execute("DELETE FROM event_atc_positions WHERE event_id = ?", (event_id,))
    log_event("content", "删除活动", actor=staff, target_type="event", target_id=event_id,
              detail=row["title"], ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True}


# ==================== 活动管制席位管理 ====================

def _load_position_event(conn, event_id: int) -> dict:
    """席位管理端点共用的活动存在性校验"""
    row = conn.execute("SELECT id, title FROM events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        raise HTTPException(404, "活动不存在")
    return row


@router.get("/events/{event_id}/atc-positions")
def list_atc_positions(event_id: int,
                             user: dict = Depends(require_capability("manage_events"))):
    """席位列表，含占用状态：报名者 cid/username"""
    with get_conn() as conn:
        _load_position_event(conn, event_id)
        rows = conn.execute(
            "SELECT p.*, s.user_id AS taken_user_id, u.cid AS taken_cid,"
            " u.username AS taken_username"
            " FROM event_atc_positions p"
            " LEFT JOIN event_signups s ON s.position_id = p.id"
            " LEFT JOIN users u ON u.id = s.user_id"
            " WHERE p.event_id = ?"
            " ORDER BY p.sort, p.id",
            (event_id,),
        ).fetchall()
    positions = []
    for p in rows:
        d = dict(p)
        taken = d.pop("taken_user_id") is not None
        d["taken"] = {"cid": d.pop("taken_cid"), "username": d.pop("taken_username")} if taken else None
        positions.append(d)
    return {"ok": True, "positions": positions}


class AtcPositionBody(BaseModel):
    name: str = Field("", max_length=16)
    rating: str = Field("", max_length=8)
    frequency: str = Field("", max_length=12)
    sort: int = Field(0, ge=0)


@router.post("/events/{event_id}/atc-positions")
def add_atc_position(event_id: int, body: AtcPositionBody, request: Request,
                           staff: dict = Depends(require_capability("manage_events"))):
    """为活动添加管制席位"""
    name = clean(body.name, 16)
    if not name:
        raise HTTPException(400, "请填写席位名称")
    with get_conn() as conn:
        event = _load_position_event(conn, event_id)
        cur = conn.execute(
            "INSERT INTO event_atc_positions (event_id, name, rating, frequency, sort)"
            " VALUES (?, ?, ?, ?, ?)",
            (event_id, name, clean(body.rating, 8).upper(), clean(body.frequency, 12),
             max(0, int(body.sort))),
        )
        pos_id = cur.lastrowid
    _audit(request, "content", "添加活动管制席位", actor=staff,
           target_type="event", target_id=event_id,
           detail=f"{event['title']} · {name} · {clean(body.rating, 8).upper()}")
    return {"ok": True, "id": pos_id}


@router.delete("/events/{event_id}/atc-positions/{pos_id}")
def delete_atc_position(event_id: int, pos_id: int, request: Request,
                              staff: dict = Depends(require_capability("manage_events"))):
    """删除管制席位：若已被占用则连同删除对应报名行，一并释放报名"""
    with get_conn() as conn:
        event = _load_position_event(conn, event_id)
        pos = conn.execute(
            "SELECT * FROM event_atc_positions WHERE id = ? AND event_id = ?",
            (pos_id, event_id),
        ).fetchone()
        if not pos:
            raise HTTPException(404, "席位不存在或不属于该活动")
        # 已被占用：先删占用者的报名行，释放席位 + 撤销其报名
        taken = conn.execute(
            "SELECT * FROM event_signups WHERE position_id = ?", (pos_id,)
        ).fetchone()
        if taken:
            conn.execute("DELETE FROM event_signups WHERE id = ?", (taken["id"],))
        conn.execute("DELETE FROM event_atc_positions WHERE id = ?", (pos_id,))
    detail = f"{event['title']} · {pos['name']}"
    if taken:
        detail += " · 已释放占用报名"
    _audit(request, "content", "删除活动管制席位", actor=staff,
           target_type="event", target_id=event_id, detail=detail)
    return {"ok": True}


# ==================== 公告管理 ====================

@router.get("/notices")
def list_notices(user: dict = Depends(require_capability("manage_notices"))):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM notices ORDER BY pinned DESC, id DESC").fetchall()
    return {"ok": True, "notices": [dict(r) for r in rows]}


class NoticeBody(BaseModel):
    title: str = Field("", max_length=120)
    content: str = Field("", max_length=2000)
    # 新公告默认置顶，保证发出来就在仪表盘最上面；需要时可手动取消
    pinned: bool = True


@router.post("/notices")
def create_notice(body: NoticeBody, request: Request,
                        staff: dict = Depends(require_capability("manage_notices"))):
    title = clean(body.title, 100)
    if not title:
        raise HTTPException(400, "请填写公告标题")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notices (title, content, pinned) VALUES (?, ?, ?)",
            (title, clean(body.content, 2000), 1 if body.pinned else 0),
        )
    log_event("content", "发布公告", actor=staff, target_type="notice", target_id=cur.lastrowid,
              detail=title, ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/notices/{notice_id}")
def delete_notice(notice_id: int, request: Request,
                        staff: dict = Depends(require_capability("manage_notices"))):
    with get_conn() as conn:
        row = conn.execute("SELECT title FROM notices WHERE id = ?", (notice_id,)).fetchone()
        conn.execute("DELETE FROM notices WHERE id = ?", (notice_id,))
    log_event("content", "删除公告", actor=staff, target_type="notice", target_id=notice_id,
              detail=row["title"] if row else "", ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True}


# ==================== 更新日志管理 ====================

@router.get("/changelogs")
def list_changelogs(user: dict = Depends(require_capability("manage_notices"))):
    """后台更新日志列表，仿公告管理：与公开接口同权限节点"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, version, title, body, released_at, created_at FROM changelogs"
            " ORDER BY released_at DESC, id DESC LIMIT 200"
        ).fetchall()
    return {"ok": True, "changelogs": [dict(r) for r in rows]}


class ChangelogBody(BaseModel):
    version: str = Field("", max_length=20)
    title: str = Field("", max_length=80)
    body: str = Field("", max_length=2000)
    releasedAt: str = Field("", max_length=10)


@router.post("/changelogs")
def create_changelog(body: ChangelogBody, request: Request,
                           staff: dict = Depends(require_capability("manage_notices"))):
    title = clean(body.title, 80)
    if not title:
        raise HTTPException(400, "请填写更新日志标题")
    content = clean(body.body, 2000)
    if not content:
        raise HTTPException(400, "请填写更新日志内容")
    # 发布日期为前端展示用的自由字符串，≤10 字符，如 '2026-10-04'；留空则默认今天
    released_at = clean(body.releasedAt, 10) or time.strftime("%Y-%m-%d")
    version = clean(body.version, 20)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO changelogs (version, title, body, released_at) VALUES (?, ?, ?, ?)",
            (version, title, content, released_at),
        )
    log_event("admin", "新增更新日志", actor=staff, target_type="changelog", target_id=cur.lastrowid,
              detail=f"{version or '无版本号'} · {title} · 发布日期 {released_at}",
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/changelogs/{changelog_id}")
def delete_changelog(changelog_id: int, request: Request,
                           staff: dict = Depends(require_capability("manage_notices"))):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, version, title FROM changelogs WHERE id = ?", (changelog_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "更新日志不存在")
        conn.execute("DELETE FROM changelogs WHERE id = ?", (changelog_id,))
    log_event("admin", "删除更新日志", actor=staff, target_type="changelog", target_id=changelog_id,
              detail=f"{row['version']} · {row['title']}",
              ip=client_ip_from_request(request), ua=user_agent(request))
    return {"ok": True}


@router.delete("/routes/{route_id}")
def delete_route(route_id: int, user: dict = Depends(require_admin)):
    with get_conn() as conn:
        conn.execute("DELETE FROM routes WHERE id = ?", (route_id,))
    return {"ok": True}


# ==================== 日志：登录 / 注册 / 网络 / 审计 ====================

def _days_filter(days: int) -> str:
    days = max(1, min(days, 90))
    return f"-{days} day"


@router.get("/logs/login")
def login_logs(q: str = "", success: str = "", bot: str = "", days: int = 7,
                     page: int = 1, user: dict = Depends(require_capability("view_logs"))):
    like = f"%{q.strip()}%"
    page = max(1, min(page, 10000))
    offset = (page - 1) * 50
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM login_logs WHERE created_at >= datetime('now', ?, 'localtime')"
            " AND (? = '' OR cid LIKE ? OR username LIKE ? OR ip LIKE ?)"
            " AND (? = '' OR success = CAST(? AS INTEGER))"
            " AND (? = '' OR ua_bot = CAST(? AS INTEGER))"
            " ORDER BY id DESC LIMIT 50 OFFSET ?",
            (_days_filter(days), q.strip(), like, like, like, success, success or 0,
             bot, bot or 0, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) c FROM login_logs WHERE created_at >= datetime('now', ?, 'localtime')"
            " AND (? = '' OR ua_bot = CAST(? AS INTEGER))",
            (_days_filter(days), bot, bot or 0),
        ).fetchone()["c"]
        failed = conn.execute(
            "SELECT COUNT(*) c FROM login_logs WHERE success = 0 AND created_at >= datetime('now', ?, 'localtime')",
            (_days_filter(days),),
        ).fetchone()["c"]
        bots = conn.execute(
            "SELECT COUNT(*) c FROM login_logs WHERE ua_bot = 1 AND created_at >= datetime('now', ?, 'localtime')",
            (_days_filter(days),),
        ).fetchone()["c"]
    return {
        "ok": True, "logs": [dict(r) for r in rows], "total": total,
        "failed": failed, "botLogins": bots, "page": page,
    }


@router.get("/logs/register")
def register_logs(q: str = "", bot: str = "", days: int = 7, page: int = 1,
                        user: dict = Depends(require_capability("view_logs"))):
    like = f"%{q.strip()}%"
    page = max(1, min(page, 10000))
    offset = (page - 1) * 50
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM register_logs WHERE created_at >= datetime('now', ?, 'localtime')"
            " AND (? = '' OR cid LIKE ? OR username LIKE ? OR email LIKE ? OR ip LIKE ?)"
            " AND (? = '' OR ua_bot = CAST(? AS INTEGER))"
            " ORDER BY id DESC LIMIT 50 OFFSET ?",
            (_days_filter(days), q.strip(), like, like, like, like, bot, bot or 0, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) c FROM register_logs WHERE created_at >= datetime('now', ?, 'localtime')"
            " AND (? = '' OR ua_bot = CAST(? AS INTEGER))",
            (_days_filter(days), bot, bot or 0),
        ).fetchone()["c"]
        bots = conn.execute(
            "SELECT COUNT(*) c FROM register_logs WHERE ua_bot = 1 AND created_at >= datetime('now', ?, 'localtime')",
            (_days_filter(days),),
        ).fetchone()["c"]
    return {"ok": True, "logs": [dict(r) for r in rows], "total": total, "botLogins": bots, "page": page}


@router.get("/logs/network")
def network_logs(days: int = 7, user: dict = Depends(require_capability("view_logs"))):
    days = max(1, min(days, 90))
    with get_conn() as conn:
        # 日期口径：api_metrics 的 day 由中间件按本地日，time.strftime 写入，
        # 这里必须用 date 'now','localtime',? 对齐本地日界，否则 UTC 日界会错位
        summary = conn.execute(
            "SELECT COALESCE(SUM(count), 0) AS total,"
            " COALESCE(SUM(CASE WHEN status >= 400 THEN count ELSE 0 END), 0) AS errors"
            " FROM api_metrics WHERE day >= date('now', ?, 'localtime')", (f"-{days} day",),
        ).fetchone()
        by_status = conn.execute(
            "SELECT status, SUM(count) AS count FROM api_metrics WHERE day >= date('now', ?, 'localtime')"
            " GROUP BY status ORDER BY count DESC", (f"-{days} day",),
        ).fetchall()
        top_paths = conn.execute(
            "SELECT method, path, SUM(count) AS count,"
            " SUM(CASE WHEN status >= 400 THEN count ELSE 0 END) AS errors"
            " FROM api_metrics WHERE day >= date('now', ?, 'localtime')"
            " GROUP BY method, path ORDER BY count DESC LIMIT 40", (f"-{days} day",),
        ).fetchall()
        daily = conn.execute(
            "SELECT day, SUM(count) AS count FROM api_metrics WHERE day >= date('now', ?, 'localtime')"
            " GROUP BY day ORDER BY day", (f"-{days} day",),
        ).fetchall()
    return {
        "ok": True,
        "summary": {"total": summary["total"], "errors": summary["errors"]},
        "byStatus": [dict(r) for r in by_status],
        "topPaths": [dict(r) for r in top_paths],
        "daily": [dict(r) for r in daily],
    }


@router.get("/logs/audit")
def audit_logs(category: str = "", q: str = "", days: int = 7, page: int = 1,
                     user: dict = Depends(require_capability("view_logs"))):
    like = f"%{q.strip()}%"
    page = max(1, min(page, 10000))
    offset = (page - 1) * 50
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs WHERE created_at >= datetime('now', ?, 'localtime')"
            " AND (? = '' OR category = ?)"
            " AND (? = '' OR actor_name LIKE ? OR action LIKE ? OR detail LIKE ? OR target_id = ?)"
            " ORDER BY id DESC LIMIT 50 OFFSET ?",
            (_days_filter(days), category, category, q.strip(), like, like, like, q.strip(), offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) c FROM audit_logs WHERE created_at >= datetime('now', ?, 'localtime')"
            " AND (? = '' OR category = ?)", (_days_filter(days), category, category),
        ).fetchone()["c"]
        by_category = conn.execute(
            "SELECT category, COUNT(*) AS count FROM audit_logs"
            " WHERE created_at >= datetime('now', ?, 'localtime') GROUP BY category"
            " ORDER BY count DESC", (_days_filter(days),),
        ).fetchall()
    return {
        "ok": True, "logs": [dict(r) for r in rows], "total": total, "page": page,
        "byCategory": [dict(r) for r in by_category],
        "categoryLabels": CATEGORY_LABELS,
    }


# ---------- 合作伙伴管理，首页展示位 ----------

class ToggleEnabled(BaseModel):
    enabled: int = Field(1, ge=0, le=1)


class PartnerBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    url: str = Field(..., min_length=1, max_length=200)
    logo: str = Field("", max_length=300)
    description: str = Field("", max_length=200)
    sort: int = Field(0, ge=0, le=999)


@router.get("/partners")
def list_partners(user: dict = Depends(require_capability("manage_notices"))):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM partners ORDER BY sort, id").fetchall()
    return {"ok": True, "partners": [dict(r) for r in rows]}


@router.post("/partners")
def create_partner(body: PartnerBody, request: Request,
                         user: dict = Depends(require_capability("manage_notices"))):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "链接需以 http 或 https 协议开头")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO partners (name, url, logo, description, sort) VALUES (?, ?, ?, ?, ?)",
            (clean(body.name, 40), url, clean(body.logo, 300), clean(body.description, 200), body.sort),
        )
    _audit(request, "admin", "新增合作伙伴", actor=user, target_id=cur.lastrowid,
           detail=f"{body.name} → {url}")
    return {"ok": True, "id": cur.lastrowid, "message": f"合作伙伴「{body.name}」已添加"}


@router.put("/partners/{partner_id}")
def update_partner(partner_id: int, body: PartnerBody, request: Request,
                         user: dict = Depends(require_capability("manage_notices"))):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "链接需以 http 或 https 协议开头")
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM partners WHERE id = ?", (partner_id,)).fetchone():
            raise HTTPException(404, "合作伙伴不存在")
        conn.execute(
            "UPDATE partners SET name = ?, url = ?, logo = ?, description = ?, sort = ? WHERE id = ?",
            (clean(body.name, 40), url, clean(body.logo, 300), clean(body.description, 200), body.sort, partner_id),
        )
    _audit(request, "admin", "修改合作伙伴", actor=user, target_id=partner_id,
           detail=f"{body.name} → {url}")
    return {"ok": True, "message": "已更新"}


@router.patch("/partners/{partner_id}/enabled")
def toggle_partner(partner_id: int, body: ToggleEnabled, request: Request,
                         user: dict = Depends(require_capability("manage_notices"))):
    with get_conn() as conn:
        row = conn.execute("SELECT id, name, enabled FROM partners WHERE id = ?", (partner_id,)).fetchone()
        if not row:
            raise HTTPException(404, "合作伙伴不存在")
        newval = 0 if row["enabled"] else 1
        conn.execute("UPDATE partners SET enabled = ? WHERE id = ?", (newval, partner_id))
    _audit(request, "admin", "切换合作伙伴展示状态", actor=user, target_id=partner_id,
           detail=f"{row['name']} → {'上架' if newval else '下架'}")
    return {"ok": True, "enabled": newval, "message": f"已{'上架' if newval else '下架'}"}


@router.delete("/partners/{partner_id}")
def delete_partner(partner_id: int, request: Request,
                         user: dict = Depends(require_capability("manage_notices"))):
    with get_conn() as conn:
        row = conn.execute("SELECT id, name FROM partners WHERE id = ?", (partner_id,)).fetchone()
        if not row:
            raise HTTPException(404, "合作伙伴不存在")
        conn.execute("DELETE FROM partners WHERE id = ?", (partner_id,))
    _audit(request, "admin", "删除合作伙伴", actor=user, target_id=partner_id, detail=row["name"])
    return {"ok": True, "message": f"已删除「{row['name']}」"}


# ---------- IP 黑名单 / 白名单管理，2026-10-10 新增，见运维手册 §6.8----------
# 背景：banned_ips 之前只能手工 SQL 维护 —— 动态 IP 复用导致误封时无人可解，也无处可看。
# 权限：查看沿用 view_logs，日志类能力；封禁/解封/白名单属改动型，用 manage_users。

class BanBody(BaseModel):
    ip: str = Field(..., max_length=64)
    reason: str = Field("", max_length=200)
    days: int = Field(0, ge=0, le=3650)   # 0 = 永久
    note: str = Field("", max_length=200)


class WhitelistBody(BaseModel):
    ip: str = Field(..., max_length=64)
    note: str = Field("", max_length=200)


def _valid_ip(raw: str) -> str:
    from ipaddress import ip_address
    try:
        return str(ip_address((raw or "").strip()))
    except Exception:
        raise HTTPException(400, "IP 地址格式不正确")


@router.get("/banned-ips")
def banned_ips_list(q: str = "", user: dict = Depends(require_capability("view_logs"))):
    """黑名单 + 白名单总览；过期条目顺带清理，与登录入口的判定保持一致"""
    like = f"%{q.strip()}%"
    with get_conn() as conn:
        now = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
        conn.execute("DELETE FROM banned_ips WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        rows = conn.execute(
            "SELECT ip, reason, created_at, expires_at, source, note FROM banned_ips"
            " WHERE (? = '%%' OR ip LIKE ? OR reason LIKE ?) ORDER BY created_at DESC LIMIT 500",
            (like, like, like),
        ).fetchall()
        white = conn.execute(
            "SELECT ip, note, created_by, created_at FROM ip_whitelist ORDER BY created_at DESC"
        ).fetchall()
    bans = [{
        "ip": r["ip"], "reason": r["reason"], "createdAt": r["created_at"],
        "expiresAt": r["expires_at"] or "", "source": r["source"], "note": r["note"],
        "permanent": not r["expires_at"],
    } for r in rows]
    return {"ok": True, "bans": bans, "total": len(bans),
            "whitelist": [{"ip": w["ip"], "note": w["note"], "createdBy": w["created_by"],
                           "createdAt": w["created_at"]} for w in white]}


@router.post("/banned-ips")
def banned_ips_add(body: BanBody, request: Request,
                         user: dict = Depends(require_capability("manage_users"))):
    """手动封禁：days=0 永久，否则按天数到期"""
    from .auth import _ban_ip
    ip = _valid_ip(body.ip)
    with get_conn() as conn:
        _ban_ip(conn, ip, body.reason or "管理员手动封禁", days=body.days or 0,
                source="manual", note=body.note)
    _audit(request, "admin", "手动封禁 IP", actor=user, target_type="ip", target_id=ip,
           detail=f"{body.reason or '未填原因'} · {'永久' if not body.days else f'{body.days} 天'}")
    return {"ok": True, "message": f"已封禁 {ip}"}


@router.delete("/banned-ips/{ip}")
def banned_ips_remove(ip: str, request: Request,
                            user: dict = Depends(require_capability("manage_users"))):
    ip = _valid_ip(ip)
    with get_conn() as conn:
        row = conn.execute("SELECT reason FROM banned_ips WHERE ip = ?", (ip,)).fetchone()
        if not row:
            raise HTTPException(404, "该 IP 不在黑名单中")
        conn.execute("DELETE FROM banned_ips WHERE ip = ?", (ip,))
    _audit(request, "admin", "解封 IP", actor=user, target_type="ip", target_id=ip,
           detail=row["reason"] or "")
    return {"ok": True, "message": f"已解封 {ip}"}


@router.post("/banned-ips/whitelist")
def whitelist_add(body: WhitelistBody, request: Request,
                        user: dict = Depends(require_capability("manage_users"))):
    """加入白名单：白名单优先于黑名单，同时把已有黑名单条目清掉"""
    ip = _valid_ip(body.ip)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO ip_whitelist (ip, note, created_by, created_at)"
            " VALUES (?, ?, ?, datetime('now','localtime'))"
            " ON CONFLICT(ip) DO UPDATE SET note = excluded.note",
            (ip, body.note, user.get("username", "")),
        )
        conn.execute("DELETE FROM banned_ips WHERE ip = ?", (ip,))
    _audit(request, "admin", "加入 IP 白名单", actor=user, target_type="ip", target_id=ip,
           detail=body.note or "")
    return {"ok": True, "message": f"{ip} 已加入白名单"}


@router.delete("/banned-ips/whitelist/{ip}")
def whitelist_remove(ip: str, request: Request,
                           user: dict = Depends(require_capability("manage_users"))):
    ip = _valid_ip(ip)
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM ip_whitelist WHERE ip = ?", (ip,)).fetchone():
            raise HTTPException(404, "该 IP 不在白名单中")
        conn.execute("DELETE FROM ip_whitelist WHERE ip = ?", (ip,))
    _audit(request, "admin", "移出 IP 白名单", actor=user, target_type="ip", target_id=ip)
    return {"ok": True, "message": f"{ip} 已移出白名单"}

# ---------- 航司货币管理，2026-10-11 新增----------
# 背景：航司余额，airlines.balance 是 PIREP 结算里发工资的钱，余额为 0 时会员拿不到工资，
# 用户集中反映「没钱」。此前改余额只能手工 SQL，且没有流水口径。
# 这里提供：总览，余额/成员/费率+ 批量发放，基础金+ 单个发放/扣除 + 最近调整记录。
# 口径与既有资金流一致：airlines.balance 加减 + airline_ledger 记一行。
# 注意：前端账本只把 type='revenue' 显示成「收入」，其余一律显示为「支出」，
# 因此发放必须写 revenue，扣除写 expense，金额取正、方向由 type 表达。

ADMIN_FUND_NOTE_PREFIX = "【管理后台】"


class FundGrantBody(BaseModel):
    amount: int = Field(..., ge=1, le=10_000_000)          # 每家公司发放金额
    reason: str = Field("", max_length=200)
    scope: str = Field("approved", max_length=12)          # approved，运营中| all，全部| ids
    airlineIds: list[int] = Field(default_factory=list)


class FundAdjustBody(BaseModel):
    airlineId: int
    amount: int = Field(..., ge=-10_000_000, le=10_000_000)  # 正=发放，负=扣除
    reason: str = Field("", max_length=200)


def _airline_fund_move(conn, airline_id: int, amount: int, note: str) -> None:
    """余额与账本同事务写；amount 带符号：正=发放，负=扣除

    账本口径，见 airline_ledger_view 文档字符串：**amount 带符号，收入为正、支出为负**，
    且 `net = SUM amount ` 应恒等于 airlines.balance。
    ⚠️ 这里曾写 `abs amount `，支出也存正数，与结算路径口径相反 →
    账本「支出」显示成正数、账实自检 reconciled 变 False。
    2026-10-11 由端到端结算测试连带抓出，同一天先修了结算侧两处同类问题。
    """
    conn.execute("UPDATE airlines SET balance = balance + ? WHERE id = ?", (amount, airline_id))
    conn.execute(
        "INSERT INTO airline_ledger (airline_id, amount, type, note) VALUES (?, ?, ?, ?)",
        (airline_id, amount, "revenue" if amount >= 0 else "expense", note),
    )


@router.get("/airlines/funds")
def airline_funds(user: dict = Depends(require_capability("manage_airline_funds"))):
    """总览：各航司余额 / 成员数 / 费率 + 汇总 + 最近的后台调整记录"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.id, a.name, a.status, a.balance, a.hourly_rate, a.distance_rate,"
            " a.owner_id, u.username AS owner,"
            " (SELECT COUNT(*) FROM airline_members m WHERE m.airline_id = a.id) AS members"
            " FROM airlines a LEFT JOIN users u ON u.id = a.owner_id"
            " ORDER BY a.balance DESC, a.id"
        ).fetchall()
        recent = conn.execute(
            "SELECT l.id, l.airline_id, l.amount, l.type, l.note, l.created_at, a.name"
            " FROM airline_ledger l LEFT JOIN airlines a ON a.id = l.airline_id"
            " WHERE l.note LIKE ? ORDER BY l.id DESC LIMIT 50",
            (ADMIN_FUND_NOTE_PREFIX + "%",),
        ).fetchall()
    airlines = [{
        "id": r["id"], "name": r["name"], "status": r["status"], "balance": r["balance"],
        "members": r["members"], "hourlyRate": r["hourly_rate"], "distanceRate": r["distance_rate"],
        "owner": r["owner"] or "",
    } for r in rows]
    approved = [a for a in airlines if a["status"] == "approved"]
    return {
        "ok": True,
        "airlines": airlines,
        "summary": {
            "count": len(airlines),
            "approved": len(approved),
            "totalBalance": sum(a["balance"] for a in airlines),
            "zeroBalance": sum(1 for a in airlines if a["balance"] <= 0),
            "members": sum(a["members"] for a in airlines),
        },
        "recent": [{
            "id": r["id"], "airlineId": r["airline_id"], "airline": r["name"] or f"#{r['airline_id']}",
            "amount": r["amount"], "type": r["type"], "note": r["note"], "createdAt": r["created_at"],
        } for r in recent],
    }


@router.post("/airlines/funds/grant")
def airline_funds_grant(body: FundGrantBody, request: Request,
                              user: dict = Depends(require_capability("manage_airline_funds"))):
    """批量发放基础金：scope=approved 运营中 / all 全部 / ids 指定"""
    with get_conn() as conn:
        if body.scope == "ids":
            ids = [int(i) for i in (body.airlineIds or [])]
            if not ids:
                raise HTTPException(400, "未指定航司")
            marks = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT id, name, status FROM airlines WHERE id IN ({marks})", ids
            ).fetchall()
        elif body.scope == "all":
            rows = conn.execute("SELECT id, name, status FROM airlines").fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, status FROM airlines WHERE status = 'approved'"
            ).fetchall()
        if not rows:
            raise HTTPException(400, "没有符合条件的航司")
        note = f"{ADMIN_FUND_NOTE_PREFIX}{body.reason or '基础金发放'}，每家 {body.amount}"
        for r in rows:
            _airline_fund_move(conn, r["id"], body.amount, note)
    total = body.amount * len(rows)
    _audit(request, "admin", "发放航司基础金", actor=user, target_type="airline",
           target_id=",".join(str(r["id"]) for r in rows[:20]),
           detail=f"每家 {body.amount} · {len(rows)} 家 · 合计 {total} · 范围 {body.scope}"
                  f" · 原因：{body.reason or '未填'}")
    return {"ok": True, "airlineCount": len(rows), "amount": body.amount, "total": total,
            "airlines": [{"id": r["id"], "name": r["name"]} for r in rows],
            "message": f"已向 {len(rows)} 家航司各发放 {body.amount}，合计 {total}"}


@router.post("/airlines/funds/adjust")
def airline_funds_adjust(body: FundAdjustBody, request: Request,
                               user: dict = Depends(require_capability("manage_airline_funds"))):
    """单个航司发放，正数或扣除，负数"""
    if body.amount == 0:
        raise HTTPException(400, "金额不能为 0")
    with get_conn() as conn:
        row = conn.execute("SELECT id, name, balance FROM airlines WHERE id = ?",
                           (body.airlineId,)).fetchone()
        if not row:
            raise HTTPException(404, "航司不存在")
        if body.amount < 0 and row["balance"] + body.amount < 0:
            raise HTTPException(400, f"扣除后余额会变成负数，当前 {row['balance']}")
        note = (f"{ADMIN_FUND_NOTE_PREFIX}{body.reason or ('发放' if body.amount > 0 else '扣除')}")
        _airline_fund_move(conn, body.airlineId, body.amount, note)
        after = row["balance"] + body.amount
    _audit(request, "admin", "调整航司余额", actor=user, target_type="airline",
           target_id=body.airlineId,
           detail=f"{row['name']} {row['balance']} → {after}，{'+' if body.amount > 0 else ''}{body.amount}"
                  f" · 原因：{body.reason or '未填'}")
    return {"ok": True, "balance": after, "message": f"{row['name']} 余额已调整为 {after}"}