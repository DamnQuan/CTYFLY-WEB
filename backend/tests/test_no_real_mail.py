"""回归：测试进程必须彻底关闭 SMTP，2026-10-18

背景：app/config.py 会读 backend/.env。开发机上有生产 SMTP 凭据时，用例里
notify_user 会真的用 noreply@ccflysim.cn 给 money_member@test.local 这类
夹具地址发通知邮件 —— .local 不是有效域名，全部退信，发件账号里因此堆满
"最近联系人"。conftest.py 现在在导入 app.* 之前把 SMTP_* 显式清空。

这两条用例守住两件事：
1. 测试进程里 smtp_enabled 必须为 False，否则 .env 又漏进来了
2. notify_user 在关掉 SMTP 后不能往发送队列里塞东西
"""
from tests.conftest import make_user


def test_smtp_is_disabled_in_test_process():
    from app.config import smtp_enabled

    assert smtp_enabled() is False


def test_notify_user_does_not_enqueue_when_smtp_disabled(conn):
    from app import mailer

    uid = make_user(conn, cid="8200", username="mail_probe")
    before = mailer._mail_queue.qsize()

    mailer.notify_user(uid, "回归探针", "这条通知不应该进入发送队列")

    assert mailer._mail_queue.qsize() == before, "关掉 SMTP 后仍在给夹具地址发邮件？"
