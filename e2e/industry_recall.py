# Copyright 2026 DataInfra-RedactionEverything Contributors
"""行业包召回率评测（Phase 2 验收轨）：黄金语料 → 真实 NER 管线 → 记分卡。

用法：python industry_recall.py [legal]
门槛：identity 类（姓名/证号/电话/卡号）漏检不可接受 → 召回必须 = 100%；
standard 类（邮箱/地址/机构等）总召回 >= 85%。类型标注正确率单独报告，
不计入门槛（打码只要框住文本就安全，类型错只是展示问题）。
产出 e2e/.artifacts/{pack}_recall.md 记分卡，供技术评审/白皮书引用。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

from common import BASE_URL, PASSWORD, USERNAME

PACK = sys.argv[1] if len(sys.argv) > 1 else "legal"
CORPUS = Path(__file__).resolve().parent / "corpus" / PACK
ART = Path(__file__).resolve().parent / ".artifacts"

IDENTITY_MIN_RECALL = 1.0
STANDARD_MIN_RECALL = 0.85


def _client() -> httpx.Client:
    c = httpx.Client(base_url=BASE_URL, timeout=120.0, trust_env=False)
    for attempt in range(2):
        r = c.post("/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD})
        if r.status_code == 429 and attempt == 0:
            print("  [wait] auth rate limit, sleeping 65s")
            time.sleep(65)
            continue
        assert r.status_code == 200, f"login failed: {r.status_code}"
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        return c
    raise AssertionError("unreachable")


def _matched(gt_text: str, entities: list[dict]) -> dict | None:
    for entity in entities:
        text = str(entity.get("text") or "")
        if gt_text in text or (len(text) >= 2 and text in gt_text):
            return entity
    return None


def main() -> None:
    expected = json.loads((CORPUS / "expected.json").read_text(encoding="utf-8"))
    ART.mkdir(exist_ok=True)

    rows: list[tuple[str, str, str, str, str]] = []
    misses: list[str] = []
    stats = {"identity": [0, 0], "standard": [0, 0]}  # [recalled, total]
    type_ok = [0, 0]

    c = _client()
    try:
        for name, groups in expected.items():
            if name.startswith("_"):
                continue
            path = CORPUS / name
            with open(path, "rb") as fh:
                up = c.post(
                    "/api/v1/files/upload",
                    files={"file": (name, fh, "text/plain")},
                    data={"upload_source": "playground"},
                    headers={"X-Idempotency-Key": f"recall:{PACK}:{name}:v1"},
                )
            assert up.status_code == 200, f"{name} upload: {up.status_code} {up.text[:150]}"
            file_id = up.json()["file_id"]
            parse = c.get(f"/api/v1/files/{file_id}/parse")
            assert parse.status_code == 200, f"{name} parse: {parse.status_code}"
            ner = c.post(f"/api/v1/files/{file_id}/ner/hybrid", json={})
            assert ner.status_code == 200, f"{name} ner: {ner.status_code} {ner.text[:150]}"
            entities = ner.json().get("entities") or []

            for category in ("identity", "standard"):
                for gt in groups.get(category, []):
                    stats[category][1] += 1
                    hit = _matched(gt["text"], entities)
                    status = "✅" if hit else "❌"
                    got_type = str(hit.get("type")) if hit else "-"
                    if hit:
                        stats[category][0] += 1
                        type_ok[1] += 1
                        if got_type == gt["type"]:
                            type_ok[0] += 1
                    else:
                        misses.append(f"{name}: [{category}] {gt['type']} {gt['text']}")
                    rows.append((name, category, gt["type"], gt["text"], f"{status} {got_type}"))
            print(f"  [ok] {name}: {len(entities)} entities returned")
    finally:
        c.close()

    id_recall = stats["identity"][0] / max(1, stats["identity"][1])
    std_recall = stats["standard"][0] / max(1, stats["standard"][1])
    type_acc = type_ok[0] / max(1, type_ok[1])

    lines = [
        f"# 行业包召回记分卡 — {PACK}",
        "",
        f"- identity 召回: **{stats['identity'][0]}/{stats['identity'][1]} = {id_recall:.1%}**（门槛 100%）",
        f"- standard 召回: **{stats['standard'][0]}/{stats['standard'][1]} = {std_recall:.1%}**（门槛 85%）",
        f"- 类型标注正确率: {type_acc:.1%}（信息项，不计门槛）",
        "",
        "| 文件 | 类别 | 期望类型 | 真值 | 命中/实际类型 |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {a} | {b} | {c_} | {d} | {e} |" for a, b, c_, d, e in rows]
    report = "\n".join(lines) + "\n"
    (ART / f"{PACK}_recall.md").write_text(report, encoding="utf-8")
    print(f"\nidentity={id_recall:.1%} standard={std_recall:.1%} type_acc={type_acc:.1%}")
    print(f"scorecard -> e2e/.artifacts/{PACK}_recall.md")
    if misses:
        print("misses:")
        for m in misses:
            print("  " + m)

    assert id_recall >= IDENTITY_MIN_RECALL, f"identity recall {id_recall:.1%} < 100%"
    assert std_recall >= STANDARD_MIN_RECALL, f"standard recall {std_recall:.1%} < 85%"
    print(f"RECALL_PASS {PACK}")


if __name__ == "__main__":
    main()
