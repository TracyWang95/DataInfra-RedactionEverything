"""对指定图片压测 8082 /ocr（与 Playground 同图时可对照）"""
import base64
import sys
import time

import httpx

IMG = r"testdata/ce.png"


def main() -> int:
    with open(IMG, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    print(f"[bench] image={IMG} bytes={len(b64)} b64_len={len(b64)}")

    t0 = time.perf_counter()
    try:
        r = httpx.post(
            "http://127.0.0.1:8082/ocr",
            json={"image": b64, "max_new_tokens": 512},
            timeout=400.0,
        )
    except Exception as e:
        print("[bench] ERROR", e)
        return 1
    dt = time.perf_counter() - t0
    print(f"[bench] HTTP {r.status_code} total_wall={dt:.2f}s")
    if r.status_code != 200:
        print(r.text[:500])
        return 1
    data = r.json()
    boxes = data.get("boxes") or []
    print(f"[bench] boxes={len(boxes)} server_elapsed={data.get('elapsed')} model={data.get('model')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
