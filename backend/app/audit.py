"""审计日志写入：统一记录"谁在何时对什么做了什么"，尽力而为，不影响主流程"""
import os
import threading

from .database import get_conn

CATEGORIES = ["auth", "permission", "content", "airline", "risk", "admin", "system"]

CATEGORY_LABELS = {
    "auth": "认证类",
    "permission": "权限类",
    "content": "内容类",
    "airline": "航司类",
    "risk": "越权与风控",
    "admin": "管理操作",
    "system": "系统类",
}

# 429 等高频事件降噪：同一 key 每分钟只记一次
_dedupe: dict[str, float] = {}
_lock = threading.Lock()
_DEDUPE_WINDOW = 60.0


def _should_dedupe(key: str) -> bool:
    import time

    now = time.time()
    with _lock:
        last = _dedupe.get(key)
        if last and now - last < _DEDUPE_WINDOW:
            return True
        _dedupe[key] = now
        return False


def log_event(category: str, action: str, *, actor=None, target_type: str = "",
              target_id="", detail: str = "", ip: str = "", ua: str = "",
              dedupe_key: str = "") -> None:
    """写入审计日志。actor 为 None 时表示系统/匿名事件。"""
    if dedupe_key and _should_dedupe(dedupe_key):
        return
    try:
        from .requestinfo import classify_ua

        ua_label, ua_bot = classify_ua(ua)
        actor_id = actor.get("id") if isinstance(actor, dict) else None
        actor_name = (actor.get("username") if isinstance(actor, dict) else "") or ""
        actor_role = (actor.get("role") if isinstance(actor, dict) else "") or ""
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO audit_logs (actor_id, actor_name, actor_role, category, action,"
                " target_type, target_id, detail, ip, ua, ua_label, ua_bot, pid)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (actor_id, actor_name, actor_role, category, action,
                 target_type, str(target_id or ""), detail[:500], ip, ua[:300],
                 ua_label, 1 if ua_bot else 0, os.getpid()),
            )
    except Exception:
        pass  # 审计失败不影响业务
