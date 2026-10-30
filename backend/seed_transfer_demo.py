"""搭建「跳槽，转司」演示数据 —— 幂等，可重复执行

用法：
    cd backend && python seed_transfer_demo.py

布局，目标状态：
- 来源航司：CTY，CEO = testpilot，成员含 secuser，正式飞行员
- 演示航司：DEMO 演示航空，CEO = admin，即主账号，成员含 audituser
- 待审批跳槽：secuser CTY → DEMO

于是用 admin 登录进入「演示航空」即可看到跳槽审批面板；
用 secuser 登录则能看到申请方的「跳槽审核中 / 撤销」状态。

注意：所有前置校验都在写入之前完成，避免中途失败导致前面的写入被回滚。
"""
from app.database import get_conn, init_db

DEMO_ICAO = "DEMO"
DEMO_NAME = "演示航空"
DEMO_DESC = "用于演示跳槽（转司）流程的航司：CEO 为 admin，接收来自其他航司的转司申请。"
TRANSFER_REASON = "想加入演示航空体验双发宽体机队"


def main() -> None:
    init_db()
    with get_conn() as conn:
        users = {
            r["username"]: r["id"]
            for r in conn.execute("SELECT id, username FROM users").fetchall()
        }
        missing = [u for u in ("admin", "testpilot", "secuser", "audituser") if u not in users]
        if missing:
            raise SystemExit(f"缺少演示账号 {missing}，无法搭建演示数据")

        admin, secuser, audituser = users["admin"], users["secuser"], users["audituser"]

        cty = conn.execute("SELECT id, icao, name FROM airlines WHERE icao = 'CTY'").fetchone()
        if not cty:
            raise SystemExit("缺少来源航司 CTY，无法演示跳槽")

        # ---- 前置清理：admin 若有「待审核的加入申请」，先撤回，否则无法成为演示航司 CEO ----
        stray = conn.execute(
            "SELECT m.id, a.icao FROM airline_members m JOIN airlines a ON a.id = m.airline_id"
            " WHERE m.user_id = ? AND m.status = 'pending'",
            (admin,),
        ).fetchall()
        for s in stray:
            conn.execute("DELETE FROM airline_members WHERE id = ?", (s["id"],))
            print(f"[清理] 已撤回 admin 对 {s['icao']} 的待审核加入申请（否则无法创建/拥有航司）")

        active_elsewhere = conn.execute(
            "SELECT a.icao FROM airline_members m JOIN airlines a ON a.id = m.airline_id"
            " WHERE m.user_id = ? AND m.status = 'active' AND a.icao != ?",
            (admin, DEMO_ICAO),
        ).fetchall()
        if active_elsewhere:
            raise SystemExit(
                f"admin 目前是 {[a['icao'] for a in active_elsewhere]} 的正式成员，"
                "请先在界面上退出该航司再运行本脚本"
            )

        # ---- 1. 演示航司 DEMO，CEO = admin----
        demo = conn.execute("SELECT id FROM airlines WHERE icao = ?", (DEMO_ICAO,)).fetchone()
        if demo:
            demo_id = demo["id"]
            conn.execute(
                "UPDATE airlines SET name = ?, description = ?, owner_id = ?, status = 'approved'"
                " WHERE id = ?",
                (DEMO_NAME, DEMO_DESC, admin, demo_id),
            )
            print(f"[已存在] {DEMO_ICAO} {DEMO_NAME}（id={demo_id}）")
        else:
            cur = conn.execute(
                "INSERT INTO airlines (icao, name, description, owner_id, status)"
                " VALUES (?, ?, ?, ?, 'approved')",
                (DEMO_ICAO, DEMO_NAME, DEMO_DESC, admin),
            )
            demo_id = cur.lastrowid
            print(f"[新建] {DEMO_ICAO} {DEMO_NAME}（id={demo_id}，CEO=admin）")

        for member, role in ((admin, "ceo"), (audituser, "pilot")):
            conn.execute(
                "INSERT INTO airline_members (airline_id, user_id, role, status, joined_at)"
                " VALUES (?, ?, ?, 'active', datetime('now','localtime'))"
                " ON CONFLICT(airline_id, user_id) DO UPDATE SET role = ?, status = 'active'",
                (demo_id, member, role, role),
            )
        print("[成员] DEMO: admin(CEO)、audituser(飞行员)")

        # ---- 2. 来源侧：secuser 必须是 CTY 正式成员，申请方----
        conn.execute(
            "INSERT INTO airline_members (airline_id, user_id, role, status, joined_at)"
            " VALUES (?, ?, 'pilot', 'active', datetime('now','localtime'))"
            " ON CONFLICT(airline_id, user_id) DO UPDATE SET role = 'pilot', status = 'active'",
            (cty["id"], secuser),
        )

        # ---- 3. 待审批跳槽申请：secuser  CTY → DEMO ----
        existing = conn.execute(
            "SELECT id, to_airline_id FROM airline_transfers WHERE user_id = ? AND status = 'pending'",
            (secuser,),
        ).fetchone()
        if existing and existing["to_airline_id"] == demo_id:
            print(f"[已存在] secuser 的待审批跳槽申请（id={existing['id']}）")
        else:
            if existing:
                conn.execute("DELETE FROM airline_transfers WHERE id = ?", (existing["id"],))
                print(f"[重置] 已删除 secuser 指向其他航司的旧申请（id={existing['id']}）")
            cur = conn.execute(
                "INSERT INTO airline_transfers"
                " (user_id, from_airline_id, from_icao, from_name, to_airline_id, reason)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (secuser, cty["id"], cty["icao"], cty["name"], demo_id, TRANSFER_REASON),
            )
            print(f"[新建] 跳槽申请 id={cur.lastrowid}：secuser  {cty['icao']} → {DEMO_ICAO}")

        # ---- 汇总 ----
        print("\n当前演示状态：")
        for a in conn.execute(
            "SELECT a.icao, a.name,"
            " (SELECT COUNT(*) FROM airline_members m"
            "   WHERE m.airline_id = a.id AND m.status = 'active') AS members,"
            " (SELECT username FROM users u WHERE u.id = a.owner_id) AS ceo"
            " FROM airlines a WHERE a.status = 'approved' ORDER BY a.id"
        ).fetchall():
            print(f"  {a['icao']:5} {a['name']:10} 成员 {a['members']}  CEO {a['ceo']}")
        for t in conn.execute(
            "SELECT t.id, u.username, t.from_icao, a.icao AS to_icao FROM airline_transfers t"
            " JOIN users u ON u.id = t.user_id JOIN airlines a ON a.id = t.to_airline_id"
            " WHERE t.status = 'pending'"
        ).fetchall():
            print(f"  待审批跳槽 #{t['id']}: {t['username']}  {t['from_icao']} → {t['to_icao']}")

        print("\n演示步骤：")
        print("  A. 审批方（你的主账号）：admin / change-me-in-env")
        print("     虚拟航司 → 航司列表 → 进入「演示航空」→ 顶部「跳槽申请（1）」→ 接收 / 驳回")
        print("  B. 申请方：secuser / NewPass1234")
        print("     虚拟航司 → 列表里「演示航空」显示「跳槽审核中」，我的航司卡片可「撤销跳槽」")
        print("  C. 其他可登录账号：testpilot / Test1234（CTY CEO）、pypilot / Py123456、audituser / Test1234")


if __name__ == "__main__":
    main()
