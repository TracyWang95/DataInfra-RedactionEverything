"""Authentication module - JWT + local password."""
import os
import json
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from app.core.config import settings

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


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
    return f"{salt}:{hashed}"


def verify_password(password: str, stored: str) -> bool:
    if ":" not in stored:
        return False
    salt, hashed = stored.split(":", 1)
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
    return hmac.compare_digest(check, hashed)


def create_token(subject: str = "local_user") -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效 Token")


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
