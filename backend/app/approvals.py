"""审批流：角色变更 / 封禁 / 删除账户

规则，按需求：
- 需要 2 名不同的 ADM/SUP 复核通过才生效
- 发起人不能审批自己发起的申请
- 目标用户本人不能审批针对自己的申请
- 任一人驳回即驳回
"""
import json

from fastapi import HTTPException

from .audit import log_event
from .database import get_conn
from .mailer import notify_user

TYPE_LABELS = {
    "role_change": "角色变更",
    "ban": "封禁账号",
    "delete_account": "删除账户",
}

REQUIRED_APPROVALS = 2


def _target_label(conn, user_id: int) -> str:
    row = conn.execute("SELECT cid, username FROM users WHERE id = ?", (user_id,)).fetchone()
    return f"{row['username']}(CID {row['cid']})" if row else f"用户#{user_id}"


def create_approval(*, type_: str, target_user_id: int, payload: dict, reason: str,
                    initiator: dict, ip: str = "", ua: str = "") -> int:
    with get_conn() as conn:
        target = conn.execute("SELECT id, role FROM users WHERE id = ?", (target_user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "目标用户不存在")

        existing = conn.execute(
            "SELECT id FROM approvals WHERE target_user_id = ? AND type = ? AND status = 'pending'",
            (target_user_id, type_),
        ).fetchone()
        if existing:
            raise HTTPException(400, "该用户已有同类型待审批申请")

        label = _target_label(conn, target_user_id)
        cur = conn.execute(
            "INSERT INTO approvals (type, target_user_id, target_label, payload, reason,"
            " initiator_id, initiator_name, required) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (type_, target_user_id, label, json.dumps(payload, ensure_ascii=False),
             reason[:200], initiator["id"], initiator["username"], REQUIRED_APPROVALS),
        )

    log_event(
        "permission", f"发起{TYPE_LABELS.get(type_, type_)}审批",
        actor=initiator, target_type="user", target_id=target_user_id,
        detail=f"{label} · {reason[:80]} · payload={json.dumps(payload, ensure_ascii=False)}",
        ip=ip, ua=ua,
    )
    return cur.lastrowid


def vote_approval(*, approval_id: int, voter: dict, vote: str, comment: str = "",
                  ip: str = "", ua: str = "") -> dict:
    if vote not in ("approve", "reject"):
        raise HTTPException(400, "无效操作")

    with get_conn() as conn:
        ap = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if not ap:
            raise HTTPException(404, "审批不存在")
        if ap["status"] != "pending":
            raise HTTPException(400, "该审批已结束")
        if ap["initiator_id"] == voter["id"]:
            raise HTTPException(400, "发起人不能审批自己发起的申请")
        if ap["target_user_id"] == voter["id"]:
            raise HTTPException(400, "不能审批针对自己的申请")

        voted = conn.execute(
            "SELECT 1 FROM approval_votes WHERE approval_id = ? AND voter_id = ?",
            (approval_id, voter["id"]),
        ).fetchone()
        if voted:
            raise HTTPException(400, "你已审批过该申请")

        conn.execute(
            "INSERT INTO approval_votes (approval_id, voter_id, voter_name, vote, comment)"
            " VALUES (?, ?, ?, ?, ?)",
            (approval_id, voter["id"], voter["username"], vote, comment[:200]),
        )

        approvals = conn.execute(
            "SELECT COUNT(*) c FROM approval_votes WHERE approval_id = ? AND vote = 'approve'",
            (approval_id,),
        ).fetchone()["c"]

        payload = json.loads(ap["payload"] or "{}")
        finished, status, note = False, ap["status"], ""

        if vote == "reject":
            finished, status, note = True, "rejected", "有审批人驳回"
        elif approvals >= ap["required"]:
            finished, status, note = True, "approved", "复核通过"

        if finished:
            conn.execute(
                "UPDATE approvals SET status = ?, decided_at = datetime('now','localtime'),"
                " decision_note = ? WHERE id = ?",
                (status, note, approval_id),
            )
            if status == "approved":
                _apply(conn, ap, payload, voter)

    log_event(
        "permission", f"审批{'通过' if vote == 'approve' else '驳回'}：{TYPE_LABELS.get(ap['type'], ap['type'])}",
        actor=voter, target_type="user", target_id=ap["target_user_id"],
        detail=f"{ap['target_label']} · 累计通过 {approvals}/{ap['required']} · {comment[:80]}",
        ip=ip, ua=ua,
    )
    return {
        "ok": True, "status": status, "approvals": approvals,
        "required": ap["required"], "finished": finished,
    }


def _apply(conn, ap, payload: dict, actor: dict) -> None:
    """审批通过后执行实际动作"""
    uid = ap["target_user_id"]
    if ap["type"] == "role_change":
        new_role = payload.get("role")
        if new_role in ("user", "sup", "admin"):
            old_role = conn.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()
            old_role = old_role["role"] if old_role else ""
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, uid))
            conn.execute("UPDATE users SET token_ver = token_ver + 1 WHERE id = ?", (uid,))
            # 角色变更通知：写明原角色 → 现角色，集体审议结果
            role_names = {"user": "普通用户", "sup": "主管，SUP", "admin": "管理员，ADM"}
            notify_user(
                uid, "你的账号角色已变更",
                f"经管理员集体审议，你的账号角色已调整：\n"
                f"{role_names.get(old_role, old_role)} → {role_names.get(new_role, new_role)}。\n"
                f"重新登录后生效。如有疑问，请联系管理员。",
            )
    elif ap["type"] == "ban":
        conn.execute("UPDATE users SET status = 'banned', token_ver = token_ver + 1 WHERE id = ?", (uid,))
        # 安全提醒：封禁发生在用户不在线时，邮件是唯一的告知渠道
        notify_user(
            uid, "你的账号已被封禁",
            f"经管理员集体审议，你的账号已被封禁，无法再登录本站。\n"
            f"审议备注：{ap['target_label'] or '详见站内审议记录'}\n"
            f"如有异议，请通过邮箱联系管理员申诉。",
        )
    elif ap["type"] == "delete_account":
        # 软删除并匿名化：保留关联数据，工单/报告等的引用完整性
        anon = f"deleted_{uid}"
        conn.execute(
            "UPDATE users SET status = 'deleted', username = ?, email = ?, qq = '', avatar_url = '',"
            " password_hash = '', token_ver = token_ver + 1 WHERE id = ?",
            (anon, f"{anon}@deleted.local", uid),
        )
    log_event(
        "permission", f"执行{TYPE_LABELS.get(ap['type'], ap['type'])}",
        actor=actor, target_type="user", target_id=uid,
        detail=f"{ap['target_label']} · payload={json.dumps(payload, ensure_ascii=False)}",
    )
