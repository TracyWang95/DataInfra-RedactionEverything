"""Authentication module - JWT + local password."""
import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.token_blacklist import get_blacklist

security = HTTPBearer(auto_error=False)

_AUTH_FILE = os.path.join(settings.DATA_DIR, "auth.json")


def _load_auth() -> dict:
    if os.path.exists(_AUTH_FILE):
        with open(_AUTH_FILE) as f:
            return json.load(f)
    return {}


def _save_auth(data: dict) -> None:
    os.makedirs(os.path.dirname(_AUTH_FILE) or ".", exist_ok=True)
    with open(_AUTH_FILE, "w") as f:
        json.dump(data, f)


_PBKDF2_ITERATIONS = 600_000  # NIST SP 800-132 (2023) 推荐最低值


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS).hex()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored: str) -> bool:
    if ":" not in stored:
        return False
    salt, hashed = stored.split(":", 1)
    # 兼容旧迭代次数：先用新迭代次数验证，失败后尝试旧值
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS).hex()
    if hmac.compare_digest(check, hashed):
        return True
    # 兼容旧 100_000 次迭代的哈希
    check_legacy = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return hmac.compare_digest(check_legacy, hashed)


def create_token(subject: str = "local_user") -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "exp": expire,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效 Token")

    # Check blacklist
    jti = payload.get("jti")
    if jti and get_blacklist().is_revoked(jti):
        raise HTTPException(status_code=401, detail="Token 已注销")

    return payload


def revoke_token(token: str) -> None:
    """Decode a token (without blacklist check) and add its JTI to the blacklist."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        # Still revoke expired tokens (belt-and-suspenders)
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        return  # nothing to revoke

    jti = payload.get("jti")
    exp = payload.get("exp", 0)
    if jti:
        get_blacklist().revoke(jti, int(exp))


def validate_password_strength(password: str) -> list[str]:
    """Validate password complexity. Returns a list of error messages (empty = valid)."""
    errors: list[str] = []
    if len(password) < 8:
        errors.append("密码长度至少 8 位")
    if not any(c.isupper() for c in password):
        errors.append("密码需要包含至少一个大写字母 (uppercase)")
    if not any(c.islower() for c in password):
        errors.append("密码需要包含至少一个小写字母 (lowercase)")
    if not any(c.isdigit() for c in password):
        errors.append("密码需要包含至少一个数字 (digit)")
    if not any(not c.isalnum() for c in password):
        errors.append("密码需要包含至少一个特殊字符 (special character)")
    return errors


def is_password_set() -> bool:
    auth = _load_auth()
    return bool(auth.get("password_hash"))


def set_password(password: str) -> None:
    auth = _load_auth()
    auth["password_hash"] = hash_password(password)
    _save_auth(auth)


def check_password(password: str) -> bool:
    auth = _load_auth()
    stored = auth.get("password_hash", "")
    if not stored:
        return False
    return verify_password(password, stored)


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str | None:
    """Dependency: require valid JWT if AUTH_ENABLED.

    Checks both the Authorization header and the ``access_token`` cookie so
    that browser-based auth (httpOnly cookie) works alongside programmatic
    Bearer-token auth.
    """
    if not settings.AUTH_ENABLED:
        return "anonymous"

    # 1. Prefer Authorization header (Bearer token)
    token: str | None = None
    if credentials is not None:
        token = credentials.credentials

    # 2. Fall back to httpOnly cookie
    if token is None:
        token = request.cookies.get("access_token")

    if token is None:
        raise HTTPException(status_code=401, detail="未提供认证信息")

    payload = decode_token(token)
    return payload.get("sub", "unknown")
