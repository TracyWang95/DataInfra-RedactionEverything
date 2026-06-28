import os, itertools, httpx
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

UPSTREAMS = [u.strip() for u in os.environ["LB_UPSTREAMS"].split(",") if u.strip()]
_rr = itertools.cycle(UPSTREAMS)
client = httpx.AsyncClient(timeout=httpx.Timeout(600.0))
HOP = {"host","content-length","transfer-encoding","connection","keep-alive"}

async def proxy(request):
    up = next(_rr)
    url = up + request.url.path + (("?" + request.url.query) if request.url.query else "")
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    try:
        r = await client.request(request.method, url, content=body, headers=headers)
    except Exception as e:
        return Response(("LB upstream error: %s" % e).encode(), status_code=502)
    out_headers = {k: v for k, v in r.headers.items() if k.lower() not in HOP}
    return Response(r.content, status_code=r.status_code, headers=out_headers)

app = Starlette(routes=[Route("/{path:path}", proxy,
    methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])])
