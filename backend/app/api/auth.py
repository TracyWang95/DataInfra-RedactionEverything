"""Auth API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import (
    check_password,
    create_token,
    is_password_set,
    require_auth,
    set_password,
)
from app.core.config import settings

router = APIRouter(tags=["auth"])


class PasswordRequest(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthStatusResponse(BaseModel):
    auth_enabled: bool
    password_set: bool


@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status():
    return AuthStatusResponse(
        auth_enabled=settings.AUTH_ENABLED,
        password_set=is_password_set(),
    )


@router.post("/auth/setup", response_model=TokenResponse)
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


@router.post("/auth/login", response_model=TokenResponse)
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


@router.post("/auth/change-password")
async def change_password(req: PasswordRequest, _: str = Depends(require_auth)):
    """Change password (requires current auth - enforced by middleware)."""
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")
    set_password(req.password)
    return {"message": "密码修改成功"}
