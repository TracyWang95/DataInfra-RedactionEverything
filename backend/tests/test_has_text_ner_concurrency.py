"""HaS 文本 NER 并发语义（拆掉过时的进程级串行锁后的行为钉住）。

1. 视觉链路 run_has_text_analysis：不同 payload 的并发度由全局闸门控制
   （HAS_NER_GLOBAL_MAX_INFLIGHT），相同 payload 仍被 inflight 去重合并。
2. born-digital 文本链路：chunk 有界并行，单 chunk 异常不丢其余实体。
"""

import asyncio
import threading
import time

from app.core.config import settings
from app.models.schemas import Entity
from app.services.hybrid_ner_service import HybridNERService
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.ocr_pipeline import run_has_text_analysis


class _CountingHaSClient:
    """记录 ner() 并发峰值与调用次数的替身。"""

    base_url = "http://stub:0"

    def __init__(self, hold_sec: float = 0.05):
        self.hold_sec = hold_sec
        self.calls = 0
        self.peak = 0
        self._current = 0
        self._lock = threading.Lock()

    def ner(self, text, entity_types=None, **kwargs):
        with self._lock:
            self.calls += 1
            self._current += 1
            self.peak = max(self.peak, self._current)
        try:
            time.sleep(self.hold_sec)
            return {"姓名": ["张三"]}
        finally:
            with self._lock:
                self._current -= 1


def _blocks(seed: str) -> list[OCRTextBlock]:
    lines = [f"{seed} 张三 联系电话 13800000000 第{i}行文字内容足够长" for i in range(6)]
    return [
        OCRTextBlock(text=line, polygon=[[0, 40 * i], [500, 40 * i], [500, 40 * i + 30], [0, 40 * i + 30]])
        for i, line in enumerate(lines)
    ]


class _NameType:
    id = "PERSON"
    name = "姓名"


def test_distinct_payloads_respect_gate(monkeypatch):
    monkeypatch.setattr(settings, "SERIALIZE_SHARED_GPU_MODELS", True)
    monkeypatch.setattr(settings, "HAS_NER_GLOBAL_MAX_INFLIGHT", 2, raising=False)
    client = _CountingHaSClient()

    async def run():
        await asyncio.gather(*(
            run_has_text_analysis(_blocks(f"payload{i}"), client, vision_types=[_NameType()])
            for i in range(4)
        ))

    asyncio.run(run())
    assert client.calls >= 4  # 4 个不同 payload 各至少一次模型调用（含 bridge 可能更多）
    assert client.peak == 2, f"gate=2 时并发峰值应为 2，实际 {client.peak}"


def test_identical_payloads_deduplicated(monkeypatch):
    monkeypatch.setattr(settings, "SERIALIZE_SHARED_GPU_MODELS", True)
    monkeypatch.setattr(settings, "HAS_NER_GLOBAL_MAX_INFLIGHT", 4, raising=False)
    client = _CountingHaSClient(hold_sec=0.1)
    shared_blocks_a = _blocks("same-payload")
    shared_blocks_b = _blocks("same-payload")

    async def run():
        await asyncio.gather(
            run_has_text_analysis(shared_blocks_a, client, vision_types=[_NameType()]),
            run_has_text_analysis(shared_blocks_b, client, vision_types=[_NameType()]),
        )

    asyncio.run(run())
    # 主 NER + bridge NER 各 1 次；两个并发相同 payload 被 inflight 去重共享
    assert client.calls <= 2, f"相同 payload 应去重共享，实际调用 {client.calls} 次"


class _ChunkCountingService(HybridNERService):
    def __init__(self):
        super().__init__()
        self.peak = 0
        self._current = 0
        self._glock = asyncio.Lock()
        self.failed_chunk = None

    async def _extract_has_chunk_entities(self, chunk, text, semantic_entity_types, enabled_type_ids):
        async with self._glock:
            self._current += 1
            self.peak = max(self.peak, self._current)
        try:
            await asyncio.sleep(0.03)
            if chunk == self.failed_chunk:
                raise RuntimeError("boom")
            return [Entity(
                id=f"e_{chunk}", text="张三", type="PERSON",
                start=0, end=2, page=1, confidence=0.9, source="has",
            )]
        finally:
            async with self._glock:
                self._current -= 1


def _patch_common(monkeypatch, service):
    monkeypatch.setattr(service, "_build_has_candidate_chunks", lambda text: [f"c{i}" for i in range(6)])
    monkeypatch.setattr(service, "_select_has_semantic_types", lambda types: types)
    monkeypatch.setattr(service, "_cross_validate", lambda entities, text, ids: entities)
    monkeypatch.setattr(service.has_service, "is_available", lambda: True)


def test_borndigital_chunks_run_bounded_parallel(monkeypatch):
    monkeypatch.setattr(settings, "HAS_NER_MAX_PARALLEL_REQUESTS", 3)
    service = _ChunkCountingService()
    _patch_common(monkeypatch, service)

    entities = asyncio.run(service.extract("x" * 100, [_NameType()]))
    assert service.peak == 3, f"chunk 并发应为 min(6,3)=3，实际 {service.peak}"
    assert len(entities) == 6


def test_borndigital_single_chunk_failure_keeps_others(monkeypatch):
    monkeypatch.setattr(settings, "HAS_NER_MAX_PARALLEL_REQUESTS", 3)
    service = _ChunkCountingService()
    service.failed_chunk = "c2"
    _patch_common(monkeypatch, service)

    entities = asyncio.run(service.extract("x" * 100, [_NameType()]))
    assert len(entities) == 5, f"1 个 chunk 失败应保留其余 5 个实体，实际 {len(entities)}"
