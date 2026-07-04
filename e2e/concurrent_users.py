# Copyright 2026 DataInfra-RedactionEverything Contributors
"""F1-3 多用户并发实测：两账号同时跑完整处理链，断言租户隔离与双双成功。

说明：本项验证后端多租户并发正确性，走 API 级并发（两线程真并发）；
UI 流的正确性由 golden_* 有头 Chrome 路径另行覆盖。
"""
from __future__ import annotations

import io
import threading
import time

import httpx

BASE = "http://localhost:8000"
USERS = [
    ("e2e_user", "E2eUser!2026"),
    ("e2e_user2", "E2eUser2!2026"),
]
FILES_PER_USER = 3

results: dict[str, dict] = {}


def ensure_account(username: str, password: str) -> None:
    with httpx.Client(base_url=BASE, timeout=60.0, trust_env=False) as h:
        r = h.post("/api/v1/auth/login", json={"username": username, "password": password})
        if r.status_code == 429:
            time.sleep(65)
            r = h.post("/api/v1/auth/login", json={"username": username, "password": password})
        if r.status_code == 200:
            return
        r = h.post("/api/v1/auth/register", json={"username": username, "password": password})
        assert r.status_code == 200, f"cannot register {username}: {r.status_code} {r.text[:200]}"


def run_user(username: str, password: str, tag: str) -> None:
    out: dict = {"uploaded": [], "redacted": 0, "errors": []}
    results[username] = out
    try:
        with httpx.Client(base_url=BASE, timeout=180.0, trust_env=False) as h:
            r = h.post("/api/v1/auth/login", json={"username": username, "password": password})
            if r.status_code == 429:
                time.sleep(65)
                r = h.post("/api/v1/auth/login", json={"username": username, "password": password})
            assert r.status_code == 200, f"login {r.status_code}"
            h.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

            for i in range(FILES_PER_USER):
                name = f"cc_{tag}_{i}.txt"
                body = f"合同编号 HT-{tag}-{i}，甲方张三，电话 1380000{i:04d}，身份证 11010119900101{i:04d}。"
                up = h.post(
                    "/api/v1/files/upload",
                    files={"file": (name, io.BytesIO(body.encode("utf-8")), "text/plain")},
                )
                assert up.status_code == 200, f"upload {up.status_code} {up.text[:150]}"
                out["uploaded"].append((up.json()["file_id"], name))

            # 隔离断言：列表只见自己的并发标记文件
            lst = h.get("/api/v1/files?page=1&page_size=100").json()["files"]
            own = {n for _, n in out["uploaded"]}
            seen_cc = {f["original_filename"] for f in lst if str(f.get("original_filename", "")).startswith("cc_")}
            foreign = seen_cc - own
            assert not foreign, f"tenant leak: {username} sees {foreign}"

            for fid, _ in out["uploaded"]:
                pr = h.get(f"/api/v1/files/{fid}/parse")
                assert pr.status_code == 200, f"parse {pr.status_code}"
                ner = h.post(f"/api/v1/files/{fid}/ner/hybrid", json={"entity_types": []})
                assert ner.status_code == 200, f"ner {ner.status_code} {ner.text[:150]}"
                entities = ner.json().get("entities", [])
                ex = h.post(
                    "/api/v1/redaction/execute",
                    json={
                        "file_id": fid,
                        "entities": [{**e, "selected": True} for e in entities],
                        "bounding_boxes": [],
                        "config": {
                            "replacement_mode": "structured",
                            "entity_types": [],
                            "custom_replacements": {},
                        },
                    },
                )
                assert ex.status_code == 200, f"redact {ex.status_code} {ex.text[:200]}"
                out["redacted"] += 1

            # 清理（软删即可，进回收站由 sweep 清）
            for fid, _ in out["uploaded"]:
                h.delete(f"/api/v1/files/{fid}?purge=true")
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(str(exc)[:300])


def main() -> None:
    for u, p in USERS:
        ensure_account(u, p)
        time.sleep(2)

    threads = [
        threading.Thread(target=run_user, args=(u, p, u[-1] if u[-1].isdigit() else "1"))
        for u, p in USERS
    ]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0

    ok = True
    for username, out in results.items():
        status = "OK" if not out["errors"] and out["redacted"] == FILES_PER_USER else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"  [{status}] {username}: uploaded={len(out['uploaded'])} redacted={out['redacted']} errors={out['errors']}")
    print(f"  wall={wall:.1f}s (two users fully concurrent)")
    if not ok:
        raise SystemExit("CONCURRENT_FAIL")
    print("E2E_PASS concurrent_users")


if __name__ == "__main__":
    main()
