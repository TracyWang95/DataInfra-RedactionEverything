#!/bin/bash
~/anaconda3/envs/dataInfra/bin/python - <<'PYEOF'
import pathlib
p=pathlib.Path("~/redaction-deploy/backend/app/main.py").expanduser(); s=p.read_text(); orig=s

# 1) imports
s=s.replace("from starlette.responses import JSONResponse",
            "from starlette.responses import FileResponse, JSONResponse",1)
s=s.replace("from fastapi.middleware.cors import CORSMiddleware\n",
            "from fastapi.middleware.cors import CORSMiddleware\nfrom fastapi.middleware.gzip import GZipMiddleware\nfrom fastapi.staticfiles import StaticFiles\n",1)

# 2) GZip middleware (outermost -> compresses final responses incl. static assets)
s=s.replace("app.add_middleware(RequestIdMiddleware)\n",
            "app.add_middleware(RequestIdMiddleware)\napp.add_middleware(GZipMiddleware, minimum_size=1024)\n",1)

# 3) frontend dist setup + /assets mount, right after the presets logger.info line
anchor='logger.info("presets API: GET/POST %s/presets (若前端仍 404，请重启本进程以加载最新路由", settings.API_PREFIX)'
block=anchor+'''

# ---- Serve the built frontend from this process (single origin: browser -> uvicorn for UI + API) ----
_FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
_FRONTEND_INDEX = (
    os.path.join(_FRONTEND_DIST, "index.html")
    if os.path.isfile(os.path.join(_FRONTEND_DIST, "index.html"))
    else None
)
if _FRONTEND_INDEX is not None and os.path.isdir(os.path.join(_FRONTEND_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(_FRONTEND_DIST, "assets")), name="assets")
    logger.info("Serving built frontend from %s", _FRONTEND_DIST)
else:
    logger.warning("Frontend dist not found at %s; API-only mode", _FRONTEND_DIST)'''
s=s.replace(anchor, block, 1)

# 4) root route -> index.html when SPA present
old_root='''@app.get("/", tags=["root"])
async def root():
    """API root."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs" if settings.DEBUG else None,
    }'''
new_root='''@app.get("/", tags=["root"], include_in_schema=False)
async def root():
    """Serve the built SPA when present, else API info."""
    if _FRONTEND_INDEX is not None:
        return FileResponse(_FRONTEND_INDEX)
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs" if settings.DEBUG else None,
    }'''
s=s.replace(old_root, new_root, 1)

# 5) SPA deep-link catch-all, registered LAST (before __main__)
cat='''

@app.get("/{full_path:path}", include_in_schema=False)
async def _spa_fallback(full_path: str):
    """SPA deep-link fallback: real static file if present, else index.html.
    Reserved prefixes 404 so API/docs/health are never masked (they also match
    their own routes first, registered before this catch-all)."""
    if _FRONTEND_INDEX is None:
        raise StarletteHTTPException(status_code=404)
    if full_path.startswith(("api/", "api", "health", "metrics", "docs", "openapi", "redoc")):
        raise StarletteHTTPException(status_code=404)
    candidate = os.path.normpath(os.path.join(_FRONTEND_DIST, full_path))
    if full_path and candidate.startswith(_FRONTEND_DIST) and os.path.isfile(candidate):
        return FileResponse(candidate)
    return FileResponse(_FRONTEND_INDEX)


if __name__ == "__main__":'''
s=s.replace("\nif __name__ == \"__main__\":", cat, 1)

changed = s!=orig and "_spa_fallback" in s and "GZipMiddleware" in s and "_FRONTEND_INDEX" in s
p.write_text(s)
print("main.py edits applied:", changed)
PYEOF
~/anaconda3/envs/dataInfra/bin/python -c "import ast; ast.parse(open('/home/adminroot/redaction-deploy/backend/app/main.py').read()); print('AST OK')"
echo "=== restart backend ==="
pidb=$(ss -ltnp 2>/dev/null|grep ':8000 '|grep -oE 'pid=[0-9]+'|cut -d= -f2|head -1); [ -n "$pidb" ] && kill "$pidb"; sleep 3
setsid nohup bash ~/backend_g0.sh > ~/logs/backend.log 2>&1 &
for i in $(seq 1 40); do c=$(curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health 2>/dev/null); [ "$c" = "200" ] && { echo "backend UP ~$((i*2))s"; break; }; sleep 2; done
echo "=== self-check (server localhost) ==="
echo "  GET / content-type:"; curl -s -m 5 -o /dev/null -w "    status=%{http_code} type=%{content_type} size=%{size_download}\n" http://127.0.0.1:8000/
echo "  GET /api/v1/presets (expect 401):"; curl -s -m 5 -o /dev/null -w "    %{http_code}\n" http://127.0.0.1:8000/api/v1/presets
asset=$(curl -s -m 5 http://127.0.0.1:8000/ | grep -oE '/assets/[A-Za-z0-9_.-]+\.js' | head -1)
echo "  first asset $asset:"; curl -s -m 5 -H "Accept-Encoding: gzip" -o /dev/null -w "    status=%{http_code} encoding=%{header_json}\n" "http://127.0.0.1:8000$asset" 2>/dev/null || curl -s -m 5 -H "Accept-Encoding: gzip" -D - -o /dev/null "http://127.0.0.1:8000$asset" | grep -iE "content-encoding|content-type|^HTTP"
echo "  SPA deep link /single (expect HTML):"; curl -s -m 5 -o /dev/null -w "    status=%{http_code} type=%{content_type}\n" http://127.0.0.1:8000/single
echo "=== backend log: frontend served? ==="; grep -iE "Serving built frontend|Frontend dist not found" ~/logs/backend.log | tail -2
echo "=== DONE ==="
