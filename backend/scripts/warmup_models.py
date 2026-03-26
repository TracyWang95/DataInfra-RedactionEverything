"""
模型预热脚本 - 在服务启动时预热所有模型
避免首次推理时的冷启动延迟
"""
import httpx
import time
import sys

# 配置
HAS_URL = "http://127.0.0.1:8080/v1/chat/completions"
HAS_IMAGE_HEALTH = "http://127.0.0.1:8081/health"
HAS_IMAGE_DETECT = "http://127.0.0.1:8081/detect"
OCR_URL = "http://127.0.0.1:8082/ocr"
TIMEOUT = 180.0  # 首次推理可能需要较长时间

# 1x1 白色 PNG
_TEST_IMAGE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="


def warmup_has_model():
    """预热HaS NER模型"""
    print("[预热] 正在预热 HaS NER 模型...")

    test_text = "张三的身份证号是110101199003071234，电话13812345678。"

    try:
        start = time.perf_counter()
        resp = httpx.post(
            HAS_URL,
            json={
                "model": "has",
                "messages": [
                    {"role": "system", "content": "你是一个NER识别助手。"},
                    {"role": "user", "content": f"请识别以下文本中的实体：{test_text}"},
                ],
                "max_tokens": 256,
                "temperature": 0.1,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        elapsed = time.perf_counter() - start
        print(f"[预热] [OK] HaS 模型预热完成，耗时 {elapsed:.2f}s")
        return True
    except Exception as e:
        print(f"[预热] [FAIL] HaS 模型预热失败: {e}")
        return False


def warmup_has_image_model():
    """预热 HaS Image（YOLO）微服务"""
    print("[预热] 正在预热 HaS Image (YOLO) ...")
    try:
        start = time.perf_counter()
        resp = httpx.post(
            HAS_IMAGE_DETECT,
            json={"image_base64": _TEST_IMAGE_B64, "conf": 0.25},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        elapsed = time.perf_counter() - start
        print(f"[预热] [OK] HaS Image 预热完成，耗时 {elapsed:.2f}s")
        return True
    except Exception as e:
        print(f"[预热] [FAIL] HaS Image 预热失败: {e}")
        return False


def warmup_ocr():
    """预热PaddleOCR-VL微服务"""
    print("[warmup] PaddleOCR-VL ...")
    try:
        start = time.perf_counter()
        resp = httpx.post(
            OCR_URL, json={"image": _TEST_IMAGE_B64, "max_new_tokens": 64}, timeout=TIMEOUT
        )
        resp.raise_for_status()
        elapsed = time.perf_counter() - start
        print(f"[warmup] [OK] PaddleOCR-VL warmup done in {elapsed:.2f}s")
        return True
    except Exception as e:
        print(f"[warmup] [FAIL] PaddleOCR-VL warmup failed: {e}")
        return False


def check_service(url: str, name: str) -> bool:
    """检查 llama 类服务是否可用"""
    try:
        resp = httpx.get(url.replace("/v1/chat/completions", "/health"), timeout=5.0)
        return resp.status_code == 200
    except Exception:
        try:
            resp = httpx.get(url.replace("/v1/chat/completions", "/v1/models"), timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


def probe_has_image() -> tuple[str, bool]:
    """
    返回 ("ready" | "unavailable" | "down", loaded: bool)
    loaded 表示权重已加载可跑 /detect
    """
    try:
        resp = httpx.get(HAS_IMAGE_HEALTH, timeout=5.0)
        if resp.status_code != 200:
            return "down", False
        j = resp.json()
        if j.get("ready"):
            return "ready", True
        return "unavailable", False
    except Exception:
        return "down", False


def wait_for_services(max_wait: int = 90):
    """等待 HaS NER、OCR；8081 若已监听则探测一次 HaS Image，未启动则 15s 后不再阻塞"""
    print("[start] waiting for services...")

    has_ready = False
    ocr_ready = False

    for i in range(max_wait):
        if not has_ready:
            has_ready = check_service(HAS_URL, "HaS")
            if has_ready:
                print("[start] [OK] HaS ready")

        if not ocr_ready:
            try:
                resp = httpx.get("http://127.0.0.1:8082/health", timeout=3.0)
                if resp.status_code == 200 and resp.json().get("ready"):
                    ocr_ready = True
                    print("[start] [OK] OCR ready")
            except Exception:
                pass

        state, loaded = probe_has_image()
        if state == "ready" and loaded and i % 15 == 0:
            print("[start] [OK] HaS Image ready (weights loaded)")
        elif state == "unavailable" and i % 20 == 0:
            print("[start] [WARN] HaS Image 已启动但无权重 (ready=false)")

        # HaS + OCR 就绪后：8081 已响应或已等待足够时间即继续
        if has_ready and ocr_ready:
            if state != "down" or i >= 15:
                return True

        if i % 5 == 0:
            hi = "OK" if loaded else ("up" if state == "unavailable" else "...")
            status = f"HaS={'OK' if has_ready else '...'} HaS-Img={hi} OCR={'OK' if ocr_ready else '...'}"
            print(f"[start] waiting ({i}s) {status}")
        time.sleep(1)

    return has_ready and ocr_ready


def main():
    print("=" * 50)
    print("Model Warmup Script")
    print("=" * 50)

    if not wait_for_services():
        print("[ERROR] Services not ready in time")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("Warming up models...")
    print("=" * 50 + "\n")

    has_ok = warmup_has_model()
    print()
    _, img_loaded = probe_has_image()
    if img_loaded:
        img_ok = warmup_has_image_model()
    else:
        print("[预热] [SKIP] HaS Image 未加载权重，跳过 /detect 预热")
        img_ok = True
    print()
    ocr_ok = warmup_ocr()

    print("\n" + "=" * 50)
    all_ok = has_ok and img_ok and ocr_ok
    if all_ok:
        print("[OK] All models warmed up!")
    else:
        print("[WARN] Some models failed to warm up")
    print("=" * 50)


if __name__ == "__main__":
    main()
