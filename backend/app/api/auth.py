"""Auth API endpoints."""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.auth import (
    bump_user_auth_version,
    check_password,
    clear_login_attempts,
    create_token,
    create_user,
    get_optional_subject,
    get_user,
    is_login_locked,
    is_password_set,
    list_users,
    normalize_username,
    register_failed_login,
    require_auth,
    require_super_admin,
    revoke_token,
    set_password,
    validate_password_strength,
)
from app.core.config import settings
from app.core.rate_limit import RateLimiter, get_client_ip
from app.models.schemas import (
    AuthStatusResponse,
    ChangePasswordRequest,
    ConcurrencySettingsRequest,
    ConcurrencySettingsResponse,
    PasswordRequest,
    TokenResponse,
    UserCreateRequest,
)

router = APIRouter(tags=["auth"])

_auth_limiter = RateLimiter(max_requests=5, window_seconds=60)


async def _check_auth_rate_limit(request: Request) -> None:
    client_ip = get_client_ip(request)
    if not _auth_limiter.check(f"auth:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many authentication requests. Try again later.")


def _login_attempt_key(request: Request, username: str | None = None) -> str:
    client_ip = get_client_ip(request)
    user_agent = (request.headers.get("user-agent") or "").strip()
    user_part = (username or "").strip().lower()
    base = f"{client_ip}:{user_part}" if user_part else client_ip
    if not user_agent:
        return base
    user_agent_hash = hashlib.sha256(user_agent.encode("utf-8")).hexdigest()[:16]
    return f"{base}:{user_agent_hash}"


def _build_token_response(token: str) -> JSONResponse:
    expires_seconds = settings.JWT_EXPIRE_MINUTES * 60
    response = JSONResponse(
        content={
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_seconds,
        }
    )
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="strict",
        secure=not settings.DEBUG,
        max_age=expires_seconds,
        path="/",
    )
    return response


@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status(subject: str | None = Depends(get_optional_subject)):
    user = get_user(subject) if subject else None
    role = (user or {}).get("role")
    return {
        "auth_enabled": settings.AUTH_ENABLED,
        "password_set": is_password_set() if settings.AUTH_ENABLED else None,
        "authenticated": bool(subject) if settings.AUTH_ENABLED else True,
        "username": subject,
        "role": role,
        "is_super_admin": role == "super_admin",
        "multi_user": True,
    }


@router.post("/auth/setup", response_model=TokenResponse, dependencies=[Depends(_check_auth_rate_limit)])
async def setup_password(req: PasswordRequest):
    if is_password_set():
        raise HTTPException(status_code=400, detail="Password is already set. Use the login endpoint instead.")
    errors = validate_password_strength(req.password)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    subject = normalize_username(req.username, default="local_user")
    set_password(req.password, username=subject)
    token = create_token(subject)
    return _build_token_response(token)


@router.post("/auth/login", response_model=TokenResponse, dependencies=[Depends(_check_auth_rate_limit)])
async def login(req: PasswordRequest, request: Request):
    client_key = _login_attempt_key(request, req.username)
    if not is_password_set():
        raise HTTPException(status_code=400, detail="Set a password before logging in.")
    if is_login_locked(client_key):
        raise HTTPException(status_code=429, detail="Login is temporarily locked after repeated failures.")
    subject = check_password(req.password, username=req.username)
    if not subject:
        if register_failed_login(client_key):
            raise HTTPException(status_code=429, detail="Login is temporarily locked after repeated failures.")
        raise HTTPException(status_code=401, detail="Incorrect password.")
    clear_login_attempts(client_key)
    token = create_token(subject)
    return _build_token_response(token)


@router.post("/auth/register", response_model=TokenResponse, dependencies=[Depends(_check_auth_rate_limit)])
async def register(req: PasswordRequest):
    if not is_password_set():
        raise HTTPException(status_code=400, detail="Create the first administrator before registering users.")
    errors = validate_password_strength(req.password)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    subject = create_user(req.username, req.password, role="user")
    token = create_token(subject)
    return _build_token_response(token)


@router.post(
    "/auth/change-password",
    response_model=TokenResponse,
    dependencies=[Depends(_check_auth_rate_limit)],
)
async def change_password(req: ChangePasswordRequest, subject: str = Depends(require_auth)):
    """Change password after verifying the current password."""
    if not check_password(req.old_password, username=subject):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    errors = validate_password_strength(req.new_password)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    set_password(req.new_password, username=subject, invalidate_existing_tokens=True)
    token = create_token(subject)
    return _build_token_response(token)


@router.post("/auth/users", response_model=dict)
async def create_auth_user(req: UserCreateRequest, _: str = Depends(require_super_admin)):
    errors = validate_password_strength(req.password)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    subject = create_user(req.username, req.password, role=req.role)
    user = get_user(subject) or {}
    return {"username": subject, "role": user.get("role") or "user"}


@router.get("/auth/users", response_model=list[dict])
async def list_auth_users(_: str = Depends(require_super_admin)):
    return list_users()


@router.get("/auth/concurrency", response_model=ConcurrencySettingsResponse)
async def get_concurrency_settings(_: str = Depends(require_super_admin)):
    from app.services.task_queue import get_task_queue

    queue = get_task_queue()
    current = queue.concurrency
    return {
        "job_concurrency": current,
        "default_job_concurrency": settings.JOB_CONCURRENCY,
        "min_job_concurrency": 1,
        "max_job_concurrency": 16,
    }


@router.put("/auth/concurrency", response_model=ConcurrencySettingsResponse)
async def update_concurrency_settings(
    req: ConcurrencySettingsRequest,
    _: str = Depends(require_super_admin),
):
    from app.services.task_queue import get_task_queue

    queue = get_task_queue()
    current = queue.set_concurrency(req.job_concurrency)
    return {
        "job_concurrency": current,
        "default_job_concurrency": settings.JOB_CONCURRENCY,
        "min_job_concurrency": 1,
        "max_job_concurrency": 16,
    }


@router.post("/auth/logout")
async def logout(request: Request, _: str = Depends(require_auth)):
    """Revoke the current token and clear the auth cookie."""
    token: str | None = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif request.cookies.get("access_token"):
        token = request.cookies["access_token"]

    if token:
        revoke_token(token)

    response = JSONResponse(content={"message": "Logged out."})
    response.delete_cookie(key="access_token", path="/")
    return response


@router.post("/auth/revoke-all")
async def revoke_all_tokens(subject: str = Depends(require_auth)):
    """Invalidate all of the caller's existing tokens and clear the auth cookie."""
    bump_user_auth_version(subject)
    response = JSONResponse(content={"message": "All existing tokens have been invalidated."})
    response.delete_cookie(key="access_token", path="/")
    return response
