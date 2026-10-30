"""密码哈希与 JWT

密码存储使用 bcrypt，即「迭代加盐哈希」：
- 每条哈希携带独立的 16 字节随机盐，同密码每次哈希结果都不同；
- 算法内部按成本因子，2^rounds 做迭代式密钥扩展，rounds 越大破解成本越高；
- 哈希串自带算法标识与成本因子，$2b$12$...，升级成本后旧哈希仍可校验。

迭代强度：BCRYPT_ROUNDS = 12，约 250-400ms/次，登录可接受，离线破解成本 ×4。
旧哈希，cost 10 在用户下次成功登录时自动重哈希升级，needs_rehash + 透明迁移，
无需强制任何人改密码。
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import JWT_SECRET, jwt_ttl_seconds

BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """哈希的迭代成本低于当前配置时返回 True，应在登录成功后透明升级"""
    try:
        # bcrypt 格式：$2b$<cost>$<salt+hash>，第 3 段即成本因子
        return int(password_hash.split("$")[2]) < BCRYPT_ROUNDS
    except (IndexError, ValueError, AttributeError):
        return False


def sign_token(user) -> str:
    u = dict(user)  # 兼容 sqlite3.Row，无 .get 方法
    payload = {
        "uid": u["id"],
        "cid": u["cid"],
        "role": u["role"],
        "ver": u.get("token_ver", 0),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=jwt_ttl_seconds()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
