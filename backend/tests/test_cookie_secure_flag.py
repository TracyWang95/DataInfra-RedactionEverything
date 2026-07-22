"""HTTP内网部署的cookie Secure开关 (19合同上传失败根因: Secure cookie over HTTP被丢).

生产DEBUG=False强制Secure cookie,但工具经SSH隧道走http://localhost访问,浏览器
丢弃Secure cookie→CSRF头缺失→上传POST 403(后端零应用日志)。COOKIE_SECURE=0时
cookie不带Secure,HTTP下正常;默认True保HTTPS安全。
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import settings


def _app_with_csrf():
    from app.core.csrf import CSRFMiddleware
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.get("/ping")
    async def ping(request: Request):
        return {"ok": True}
    return app


def test_csrf_cookie_secure_off_over_http(monkeypatch):
    monkeypatch.setattr(settings, "COOKIE_SECURE", False, raising=False)
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    client = TestClient(_app_with_csrf())
    r = client.get("/ping")
    setc = r.headers.get("set-cookie", "")
    assert "csrf_token=" in setc
    assert "Secure" not in setc  # HTTP deployment -> no Secure -> browser keeps it


def test_csrf_cookie_secure_on_by_default(monkeypatch):
    monkeypatch.setattr(settings, "COOKIE_SECURE", True, raising=False)
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    client = TestClient(_app_with_csrf())
    r = client.get("/ping")
    assert "Secure" in r.headers.get("set-cookie", "")
