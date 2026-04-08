"""Auth API endpoints."""
import secrets as _secrets

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import (
    check_password,
    create_token,
    is_password_set,
    require_auth,
    revoke_token,
    set_password,
)
from app.core.config import settings
from app.core.rate_limit import RateLimiter
from app.models.schemas import PasswordRequest, ChangePasswordRequest, TokenResponse, AuthStatusResponse

router = APIRouter(tags=["auth"])

# Stricter rate limit for auth-sensitive endpoints (5 req/min per IP)
_auth_limiter = RateLimiter(max_requests=5, window_seconds=60)


async def _check_auth_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    if not _auth_limiter.check(f"auth:{client_ip}"):
        raise HTTPException(
            status_code=429,
            detail="认证请求过于频繁，请稍后重试",
        )


@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status():
    return AuthStatusResponse(
        auth_enabled=settings.AUTH_ENABLED,
        password_set=is_password_set(),
    )


@router.post("/auth/setup", response_model=TokenResponse, dependencies=[Depends(_check_auth_rate_limit)])
async def setup_password(req: PasswordRequest):
    if is_password_set():
        raise HTTPException(status_code=400, detail="密码已设置，请使用登录接口")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")
    set_password(req.password)
    token = create_token()
    return TokenResponse(
        access_token=token,
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
    )


@router.post("/auth/login", response_model=TokenResponse, dependencies=[Depends(_check_auth_rate_limit)])
async def login(req: PasswordRequest):
    if not is_password_set():
        raise HTTPException(status_code=400, detail="请先设置密码")
    if not check_password(req.password):
        raise HTTPException(status_code=401, detail="密码错误")
    token = create_token()
    return TokenResponse(
        access_token=token,
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
    )


@router.post("/auth/change-password", dependencies=[Depends(_check_auth_rate_limit)])
async def change_password(req: ChangePasswordRequest, _: str = Depends(require_auth)):
    """Change password (requires current auth + old password verification)."""
    if not check_password(req.old_password):
        raise HTTPException(status_code=401, detail="旧密码错误")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")
    set_password(req.new_password)
    return {"message": "密码修改成功"}


@router.post("/auth/logout")
async def logout(request: Request, _: str = Depends(require_auth)):
    """Revoke the current JWT so it can no longer be used."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        revoke_token(token)
    return {"message": "已注销"}


@router.post("/auth/revoke-all")
async def revoke_all_tokens(_: str = Depends(require_auth)):
    """Invalidate ALL existing tokens by rotating the JWT secret.

    The caller must re-authenticate after this operation.
    """
    import json, os, logging
    new_secret = _secrets.token_urlsafe(32)

    # Persist the new secret
    secret_path = os.path.join(settings.DATA_DIR, "jwt_secret.json")
    try:
        with open(secret_path, "w") as f:
            json.dump({"secret": new_secret}, f)
    except OSError as e:
        logging.getLogger(__name__).error("Failed to persist rotated JWT secret: %s", e)
        raise HTTPException(status_code=500, detail="无法保存新密钥")

    # Update the in-memory settings so new tokens use the new secret
    settings.JWT_SECRET_KEY = new_secret

    # 清除环境变量覆盖，确保重启后从文件读取新密钥
    for env_key in ("LEGAL_REDACTION_JWT_SECRET", "JWT_SECRET_KEY"):
        if env_key in os.environ:
            del os.environ[env_key]

    return {"message": "所有 Token 已失效，请重新登录"}
