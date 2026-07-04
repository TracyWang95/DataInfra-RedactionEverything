import itertools
import os

import httpx
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

UPSTREAMS = [u.strip() for u in os.environ["LB_UPSTREAMS"].split(",") if u.strip()]
# least-inflight scheduling: long requests (OCR structure pass, LA detect) vary
# 10x in duration, so plain round-robin regularly stacks two slow requests on
# one instance while the other idles. Pick the upstream with the fewest
# in-flight requests; break ties round-robin so idle traffic still spreads.
_inflight = {u: 0 for u in UPSTREAMS}
_rr = itertools.cycle(UPSTREAMS)
client = httpx.AsyncClient(timeout=httpx.Timeout(600.0))
HOP = {"host","content-length","transfer-encoding","connection","keep-alive"}

def _pick():
    least = min(_inflight.values())
    for _ in range(len(UPSTREAMS)):
        up = next(_rr)
        if _inflight[up] == least:
            return up
    return next(_rr)  # unreachable; defensive

async def proxy(request):
    up = _pick()
    _inflight[up] += 1
    url = up + request.url.path + (("?" + request.url.query) if request.url.query else "")
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    try:
        r = await client.request(request.method, url, content=body, headers=headers)
    except Exception as e:
        return Response(("LB upstream error: %s" % e).encode(), status_code=502)
    finally:
        _inflight[up] -= 1
    out_headers = {k: v for k, v in r.headers.items() if k.lower() not in HOP}
    return Response(r.content, status_code=r.status_code, headers=out_headers)

app = Starlette(routes=[Route("/{path:path}", proxy,
    methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])])
