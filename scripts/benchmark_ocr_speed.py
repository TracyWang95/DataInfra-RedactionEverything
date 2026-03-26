"""
对 OCR 微服务 (8082) 测速：样例图 + 墙钟时间 + 服务端 elapsed。

用法:
  conda activate legal-redaction
  python scripts/benchmark_ocr_speed.py
  python scripts/benchmark_ocr_speed.py "D:\\path\\to\\image.png"

环境变量:
  OCR_URL  默认 http://127.0.0.1:8082
"""
from __future__ import annotations

import base64
import os
import sys
import time

import httpx

DEFAULT_IMAGE = r"testdata/ce.png"
OCR_URL = os.environ.get("OCR_URL", "http://127.0.0.1:8082").rstrip("/")


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IMAGE
    if not os.path.isfile(path):
        print(f"[err] 文件不存在: {path}")
        return 1

    size = os.path.getsize(path)
    print(f"[bench] 图片: {path}")
    print(f"[bench] 文件大小: {size / 1024:.1f} KB")

    with open(path, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode()
    print(f"[bench] Base64 长度: {len(b64) / 1024:.1f} KB")
    print(f"[bench] 目标: {OCR_URL}/ocr (max_new_tokens=512)")

    t0 = time.perf_counter()
    try:
        r = httpx.post(
            f"{OCR_URL}/ocr",
            json={"image": b64, "max_new_tokens": 512},
            timeout=600.0,
        )
    except httpx.ConnectError:
        print("[err] 无法连接 8082，请先启动 ocr_server.py")
        return 2
    except httpx.TimeoutException:
        print("[err] 请求超时 (600s)")
        return 3
    except Exception as e:
        print("[err]", e)
        return 1

    wall = time.perf_counter() - t0
    print(f"[bench] HTTP 状态: {r.status_code}")
    print(f"[bench] 墙钟时间: {wall:.2f} s")

    if r.status_code != 200:
        print(r.text[:800])
        return 1

    data = r.json()
    boxes = data.get("boxes") or []
    srv_elapsed = data.get("elapsed")
    model = data.get("model", "?")
    print(f"[bench] 服务端 elapsed: {srv_elapsed}")
    print(f"[bench] 模型: {model}")
    print(f"[bench] 检测框数量: {len(boxes)}")
    if boxes:
        print(f"[bench] 首框预览: {boxes[0].get('text', '')[:60]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
