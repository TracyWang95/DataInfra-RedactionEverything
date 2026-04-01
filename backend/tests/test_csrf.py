"""Tests for app.core.csrf -- CSRF double-submit cookie middleware."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.csrf import CSRFMiddleware


def _make_app() -> Starlette:
    """Build a minimal Starlette app with CSRF middleware for testing."""

    async def homepage(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def create_thing(request: Request) -> JSONResponse:
        return JSONResponse({"created": True}, status_code=201)

    async def auth_login(request: Request) -> JSONResponse:
        return JSONResponse({"token": "abc"})

    app = Starlette(
        routes=[
            Route("/", homepage),
            Route("/things", create_thing, methods=["POST"]),
            Route("/api/v1/auth/login", auth_login, methods=["POST"]),
        ],
    )
    app.add_middleware(CSRFMiddleware)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


def test_get_request_sets_csrf_cookie(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "csrf_token" in resp.cookies


def test_post_without_csrf_rejected(client: TestClient) -> None:
    resp = client.post("/things")
    assert resp.status_code == 403


def test_post_with_valid_csrf_accepted(client: TestClient) -> None:
    # First GET to obtain the cookie
    get_resp = client.get("/")
    csrf_token = get_resp.cookies["csrf_token"]

    # POST with matching cookie + header
    resp = client.post(
        "/things",
        headers={"x-csrf-token": csrf_token},
        cookies={"csrf_token": csrf_token},
    )
    assert resp.status_code == 201


def test_auth_endpoints_exempt(client: TestClient) -> None:
    # Auth endpoints should not require CSRF token
    resp = client.post("/api/v1/auth/login")
    assert resp.status_code == 200
