import itertools
import os
import time

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

UPSTREAMS = [u.strip() for u in os.environ["LB_UPSTREAMS"].split(",") if u.strip()]
# Cooldown (s) an upstream is skipped after a connection-class failure before a
# half-open re-probe. Operational knob, env-overridable — not an algorithm
# threshold. Default keeps a crashed/restarting vLLM out of rotation ~long
# enough to matter but short enough to auto-recover once it is back.
COOLDOWN_SEC = float(os.environ.get("LB_COOLDOWN_SEC", "5"))
# least-inflight scheduling: long requests (OCR structure pass, LA detect) vary
# 10x in duration, so plain round-robin regularly stacks two slow requests on
# one instance while the other idles. Pick the upstream with the fewest
# in-flight requests; break ties round-robin so idle traffic still spreads.
_inflight = {u: 0 for u in UPSTREAMS}
# Monotonic time until which an upstream is considered down (0 = healthy).
_cooldown_until = {u: 0.0 for u in UPSTREAMS}
_rr = itertools.cycle(UPSTREAMS)
client = httpx.AsyncClient(timeout=httpx.Timeout(600.0))
HOP = {"host", "content-length", "transfer-encoding", "connection", "keep-alive"}
# Connection-class failures mean the upstream is unreachable (dead/restarting),
# so it should leave rotation. A ReadTimeout means it accepted but is slow —
# that is not "down", so it is deliberately excluded.
DOWN_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def _live(now):
    return [u for u in UPSTREAMS if _cooldown_until[u] <= now]


def _pick():
    now = time.monotonic()
    # Prefer live upstreams; if every upstream is cooling down, fall back to the
    # full set so one request per cycle half-open probes for recovery.
    pool = _live(now) or UPSTREAMS
    least = min(_inflight[u] for u in pool)
    for _ in range(len(UPSTREAMS)):
        up = next(_rr)
        if up in pool and _inflight[up] == least:
            return up
    return pool[0]


async def _forward(up, method, path, query, body, headers):
    url = up + path + (("?" + query) if query else "")
    _inflight[up] += 1
    try:
        r = await client.request(method, url, content=body, headers=headers)
        _cooldown_until[up] = 0.0  # a completed response clears any prior mark
        return r
    finally:
        _inflight[up] -= 1


async def proxy(request):
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    tried = set()
    last_err = None
    # At most one retry on a *different* upstream: inference calls are
    # effectively idempotent, so a dead upstream mid-request should not surface
    # as a 502 while a healthy instance is idle.
    for _ in range(min(2, len(UPSTREAMS))):
        up = _pick()
        if up in tried:
            break
        tried.add(up)
        try:
            r = await _forward(up, request.method, request.url.path, request.url.query, body, headers)
        except DOWN_ERRORS as e:
            _cooldown_until[up] = time.monotonic() + COOLDOWN_SEC
            last_err = e
            continue
        except Exception as e:  # non-connection error: report, do not penalize
            return Response(("LB upstream error: %s" % e).encode(), status_code=502)
        out_headers = {k: v for k, v in r.headers.items() if k.lower() not in HOP}
        return Response(r.content, status_code=r.status_code, headers=out_headers)
    return Response(("LB: no healthy upstream (%s)" % last_err).encode(), status_code=503)


async def lb_status(request):
    now = time.monotonic()
    return JSONResponse({
        "upstreams": [
            {
                "url": u,
                "healthy": _cooldown_until[u] <= now,
                "inflight": _inflight[u],
                "cooldown_remaining_s": round(max(0.0, _cooldown_until[u] - now), 1),
            }
            for u in UPSTREAMS
        ]
    })


app = Starlette(routes=[
    Route("/__lb_status", lb_status, methods=["GET"]),
    Route("/{path:path}", proxy,
          methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]),
])
