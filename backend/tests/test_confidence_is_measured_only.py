# Copyright 2026 DataInfra-RedactionEverything Contributors

"""A confidence must be something a model measured, or absent.

Tracy's rule: 不能有编的置信度. A number rendered as "87%" tells the user the
model weighed this box and landed there. Stamping a constant when nothing was
measured makes an unchecked guess look checked, which is worse than a blank.

HaS token logprobs were probed as a source for text entities and rejected:
correct extractions (李建国, 周明) scored 0.75/0.87 while an empty answer scored
0.99 — the number tracks how predictable the next character was, not whether
the span is really PII. So NER entities carry no confidence at all.
"""

import pytest

from app.models.entity_schemas import BoundingBox, Entity


def test_entity_without_a_measurement_has_no_confidence():
    entity = Entity(id="e1", text="李建国", type="person_name", start=0, end=3)
    assert entity.confidence is None


def test_box_without_a_measurement_has_no_confidence():
    box = BoundingBox(id="b1", x=0.1, y=0.1, width=0.2, height=0.05, type="signature")
    assert box.confidence is None


def test_measured_confidence_is_kept_verbatim():
    box = BoundingBox(
        id="b2", x=0.1, y=0.1, width=0.2, height=0.05, type="signature", confidence=0.3049
    )
    assert box.confidence == pytest.approx(0.3049)


def test_consensus_picks_a_representative_when_no_box_was_scored():
    """la_consensus ranks a cluster by confidence; unscored boxes must not crash it."""
    from app.services.vision.la_consensus import consensus_boxes

    def run(idx: int) -> list[BoundingBox]:
        return [
            BoundingBox(
                id=f"b{idx}", x=0.1, y=0.1, width=0.2, height=0.05, type="signature"
            )
        ]

    assert consensus_boxes([run(0), run(1)], min_votes=2)


def test_hybrid_ner_merge_survives_unscored_entities():
    """_cross_validate compares confidences when merging duplicate mentions."""
    from app.services.hybrid_ner_service import HybridNERService

    text = "李建国到场"
    same = dict(text="李建国", type="person_name", start=0, end=3)
    kept = HybridNERService()._cross_validate(
        [Entity(id="a", source="has", **same), Entity(id="b", source="regex", **same)],
        text,
    )
    assert len(kept) == 1
