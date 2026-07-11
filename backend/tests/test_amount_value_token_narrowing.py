"""Model-driven AMOUNT value narrowing（人民币每亩每年100元 → 100元）.

The value span comes from the MODEL, not from a token grammar: each AMOUNT
entity is re-queried against HaS with the 数值 label
(settings.AMOUNT_VALUE_QUERY_LABEL) and the model's answer replaces the span
only when it is unambiguous — exactly one value, a proper substring. The old
hand-written scanners (percent '%' tokens from the 2026-05-10 initial release,
the short-lived currency grammar) are deleted: lexical grammars are magic
rules; their gaps became leaks (1,000,000元 narrowed to 000元).

5090-verified model behavior (5 cases x2 runs, stable): 人民币每亩每年100元
→ 100元; 保底十万元/每年左右 → 十万元; 合同金额的40% → 40%; 定金1,000元整
→ 1,000元整; multi-value spans return every value (→ no narrowing).

Also: HaS INPUT text is stripped of VL math markup（$ \\underline{...} $）—
the wrapper noise made HaS tag the 保底十万元 fill only intermittently.
"""
import asyncio

from app.services.vision.has_text_payload import _iter_payload_texts
from app.services.vision.has_text_analysis import _narrow_amount_entities


class _FakeHasClient:
    def __init__(self, answers: dict[str, list[str]]):
        self.answers = answers
        self.queries: list[tuple[str, list[str]]] = []

    def ner(self, text: str, entity_types=None, **_kw):
        self.queries.append((text, list(entity_types or [])))
        if isinstance(self.answers.get(text), Exception):
            raise self.answers[text]
        return {"数值": self.answers.get(text, [])}


def _narrow(entities, answers):
    client = _FakeHasClient(answers)
    asyncio.run(_narrow_amount_entities(entities, client))
    return entities, client


def test_unambiguous_model_answer_narrows_span() -> None:
    entities, client = _narrow(
        [{"type": "AMOUNT", "text": "人民币每亩每年100元"}],
        {"人民币每亩每年100元": ["100元"]},
    )
    assert entities[0]["text"] == "100元"
    assert client.queries == [("人民币每亩每年100元", ["数值"])]


def test_multi_value_answer_keeps_whole_span() -> None:
    entities, _ = _narrow(
        [{"type": "AMOUNT", "text": "人民币壹佰万元及利息100元"}],
        {"人民币壹佰万元及利息100元": ["壹佰万元", "100元"]},
    )
    assert entities[0]["text"] == "人民币壹佰万元及利息100元"


def test_non_substring_answer_keeps_whole_span() -> None:
    # a hallucinated value that is not inside the entity must never replace it
    entities, _ = _narrow(
        [{"type": "AMOUNT", "text": "保底十万元/每年左右"}],
        {"保底十万元/每年左右": ["100000元"]},
    )
    assert entities[0]["text"] == "保底十万元/每年左右"


def test_model_failure_keeps_whole_span() -> None:
    entities, _ = _narrow(
        [{"type": "AMOUNT", "text": "定金1,000元整"}],
        {"定金1,000元整": RuntimeError("HaS down")},
    )
    assert entities[0]["text"] == "定金1,000元整"


def test_non_amount_entities_never_requeried() -> None:
    entities, client = _narrow(
        [{"type": "ADDRESS", "text": "河南新乡市100号"}],
        {},
    )
    assert entities[0]["text"] == "河南新乡市100号"
    assert client.queries == []


def test_empty_label_disables_narrowing(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "AMOUNT_VALUE_QUERY_LABEL", "", raising=False)
    entities, client = _narrow(
        [{"type": "AMOUNT", "text": "人民币每亩每年100元"}],
        {"人民币每亩每年100元": ["100元"]},
    )
    assert entities[0]["text"] == "人民币每亩每年100元"
    assert client.queries == []


def test_has_input_text_is_markup_free() -> None:
    texts = _iter_payload_texts(
        "甲方保证以销售完成的 $ \\underline{\\text{保底十万元/每年左右}} $给予乙方分红。"
    )
    joined = "".join(texts)
    assert "underline" not in joined and "$" not in joined
    assert "保底十万元/每年左右" in joined
