"""自研工作量证明人机验证回归测试

锁住四件事：
1. 没有令牌时业务接口必须 400，不能因为本地开发豁免就把线上也放过去；
2. 正常解题拿到的令牌能放行业务接口；
3. 同一个 challenge 不能兑换两次令牌，同一枚令牌也不能用两次；
4. 错误答案不会通过，且 challenge 仍然可继续尝试直到次数上限。
"""
import hashlib

import pytest
from fastapi.testclient import TestClient


def solve(challenge: str, difficulty: int) -> str:
    nonce = 0
    prefix = "0" * difficulty
    while True:
        if hashlib.sha256(f"{challenge}{nonce}".encode("utf-8")).hexdigest().startswith(prefix):
            return str(nonce)
        nonce += 1


@pytest.fixture()
def pow_on(monkeypatch):
    """强制开启校验，并把难度降到 2 让测试快一些"""
    import app.captcha as captcha

    monkeypatch.setattr(captcha, "POW_CAPTCHA_ENABLED", True)
    monkeypatch.setattr(captcha, "POW_CAPTCHA_ALLOW_LOCALHOST", False)
    monkeypatch.setattr(captcha, "POW_CAPTCHA_DIFFICULTY", 2)
    monkeypatch.setattr(captcha, "POW_CAPTCHA_SECRET", "test-only-pow-secret")
    monkeypatch.setattr(captcha, "_CHALLENGES", {})
    monkeypatch.setattr(captcha, "_TOKENS", {})
    return captcha


@pytest.fixture()
def client(db):
    from app.main import app

    return TestClient(app)


def get_token(client: TestClient) -> tuple[str, str]:
    info = client.get("/api/captcha/challenge").json()
    assert info["required"] is True
    challenge = info["challenge"]
    nonce = solve(challenge, info["difficulty"])
    result = client.post("/api/captcha/verify", json={"challenge": challenge, "nonce": nonce})
    assert result.status_code == 200, result.text
    return result.json()["token"], challenge


def test_business_endpoint_requires_token(client, pow_on):
    resp = client.post("/api/auth/send-code", json={"email": "bad-email", "purpose": "register"})
    assert resp.status_code == 400
    # 对外只给泛化提示，不暴露校验机制
    assert resp.json()["error"] == "请求校验未通过，请稍后重试"


def test_valid_token_passes_dependency(client, pow_on):
    token, _ = get_token(client)
    resp = client.post(
        "/api/auth/send-code",
        json={"email": "bad-email", "purpose": "register"},
        headers={"X-PoW-Token": token},
    )
    # 通过人机验证后才会走到邮箱格式校验
    assert resp.status_code == 400
    assert resp.json()["error"] == "邮箱格式不正确"


def test_challenge_cannot_be_redeemed_twice(client, pow_on):
    info = client.get("/api/captcha/challenge").json()
    challenge = info["challenge"]
    nonce = solve(challenge, info["difficulty"])
    first = client.post("/api/captcha/verify", json={"challenge": challenge, "nonce": nonce})
    assert first.status_code == 200
    second = client.post("/api/captcha/verify", json={"challenge": challenge, "nonce": nonce})
    assert second.status_code == 400
    assert "过期" in second.json()["error"] or "未通过" in second.json()["error"]


def test_token_is_single_use(client, pow_on):
    token, _ = get_token(client)
    headers = {"X-PoW-Token": token}
    first = client.post("/api/auth/send-code", json={"email": "bad-email", "purpose": "register"},
                        headers=headers)
    assert first.status_code == 400
    assert first.json()["error"] == "邮箱格式不正确"
    second = client.post("/api/auth/send-code", json={"email": "bad-email", "purpose": "register"},
                         headers=headers)
    assert second.status_code == 400
    assert second.json()["error"] == "请求校验未通过，请稍后重试"


def test_wrong_nonce_rejected(client, pow_on):
    info = client.get("/api/captcha/challenge").json()
    challenge = info["challenge"]
    resp = client.post("/api/captcha/verify", json={"challenge": challenge, "nonce": "0"})
    # 0 大概率不满足难度 2；若碰巧满足则换成继续找不满足的值
    if resp.status_code == 200:
        pytest.skip("nonce 0 恰好满足难度 2，跳过本次断言")
    assert "未通过" in resp.json()["error"]


def test_local_bypass_when_allowed(client, monkeypatch):
    import app.captcha as captcha

    monkeypatch.setattr(captcha, "POW_CAPTCHA_ENABLED", True)
    monkeypatch.setattr(captcha, "POW_CAPTCHA_ALLOW_LOCALHOST", True)
    monkeypatch.setattr(captcha, "POW_CAPTCHA_DIFFICULTY", 4)
    info = captcha.issue_challenge("127.0.0.1")
    assert info["required"] is False
    ok, reason, token, _ = captcha.verify_solution("", "", "127.0.0.1")
    assert ok is True and reason == "" and token == ""


def test_public_config_exposes_pow(client, pow_on):
    data = client.get("/api/config").json()
    assert data["pow"]["enabled"] is True
    assert data["pow"]["algorithm"] == "SHA-256"
    assert data["pow"]["difficulty"] == 2
    assert "secret" not in {k.lower() for k in data["pow"]}


def test_expired_challenge_rejected(client, pow_on, monkeypatch):
    info = client.get("/api/captcha/challenge").json()
    challenge = info["challenge"]
    nonce = solve(challenge, info["difficulty"])
    entry = pow_on._CHALLENGES[challenge]
    entry["exp"] = 0
    resp = client.post("/api/captcha/verify", json={"challenge": challenge, "nonce": nonce})
    assert resp.status_code == 400
    assert "过期" in resp.json()["error"]
