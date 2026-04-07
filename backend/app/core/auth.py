# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Authentication module - JWT + local password."""
import os
import json
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from app.core.config import settings
from app.core.token_blacklist import get_blacklist

security = HTTPBearer(auto_error=False)

_AUTH_FILE = os.path.join(settings.DATA_DIR, "auth.json")


def _load_auth() -> dict:
    if os.path.exists(_AUTH_FILE):
        with open(_AUTH_FILE, "r") as f:
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
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    """Dependency: require valid JWT if AUTH_ENABLED."""
    if not settings.AUTH_ENABLED:
        return "anonymous"

    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证信息")

    payload = decode_token(credentials.credentials)
    return payload.get("sub", "unknown")
