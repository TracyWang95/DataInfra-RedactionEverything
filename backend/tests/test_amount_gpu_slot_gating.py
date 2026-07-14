"""Per-entity AMOUNT value narrowing runs under the shared GPU inference gate.

The narrowing re-queries HaS once per AMOUNT entity (the 数值 label on the entity
text alone). Those calls now go through shared_gpu_inference_slot so they串行化
behind the global gate like every other local GPU model call — no batching
(concatenated context returns shorter wrong substrings -> under-coverage), one
gate-held call per entity. Narrowing semantics (unambiguous substring -> narrow,
otherwise keep whole span) are unchanged.
"""
import asyncio
from contextlib import asynccontextmanager

from app.services.vision.has_text_analysis import _narrow_amount_entities


class _SlotAssertingClient:
    """ner() asserts it is running while the GPU slot is held."""

    def __init__(self, gate_state, answers):
        self.gate_state = gate_state
        self.answers = answers
        self.calls = 0

    def ner(self, text, entity_types=None, **_kw):
        self.calls += 1
        assert self.gate_state["held"] > 0, "AMOUNT ner must run inside the GPU slot"
        return {"数值": self.answers.get(text, [])}


def _run_with_tracked_gate(monkeypatch, entities, answers):
    gate_state = {"held": 0, "entries": 0}

    @asynccontextmanager
    async def fake_slot(label):
        gate_state["held"] += 1
        gate_state["entries"] += 1
        try:
            yield
        finally:
            gate_state["held"] -= 1

    monkeypatch.setattr(
        "app.core.gpu_inference_gate.shared_gpu_inference_slot", fake_slot
    )
    client = _SlotAssertingClient(gate_state, answers)
    asyncio.run(_narrow_amount_entities(entities, client))
    return entities, client, gate_state


def test_amount_narrowing_call_is_inside_gpu_slot(monkeypatch):
    entities, client, gate_state = _run_with_tracked_gate(
        monkeypatch,
        [{"type": "AMOUNT", "text": "人民币每亩每年100元"}],
        {"人民币每亩每年100元": ["100元"]},
    )
    assert client.calls == 1
    assert gate_state["entries"] == 1
    assert gate_state["held"] == 0  # slot released after the call
    assert entities[0]["text"] == "100元"


def test_amount_narrowing_gates_each_entity_separately(monkeypatch):
    # Per-entity, not batched: two AMOUNT entities -> two gate entries.
    entities, client, gate_state = _run_with_tracked_gate(
        monkeypatch,
        [
            {"type": "AMOUNT", "text": "人民币100元"},
            {"type": "AMOUNT", "text": "定金200元整"},
        ],
        {"人民币100元": ["100元"], "定金200元整": ["200元"]},
    )
    assert client.calls == 2
    assert gate_state["entries"] == 2
    assert sorted(e["text"] for e in entities) == ["100元", "200元"]


def test_amount_non_amount_entity_never_enters_gate(monkeypatch):
    entities, client, gate_state = _run_with_tracked_gate(
        monkeypatch,
        [{"type": "ADDRESS", "text": "河南新乡市100号"}],
        {},
    )
    assert client.calls == 0
    assert gate_state["entries"] == 0
    assert entities[0]["text"] == "河南新乡市100号"
