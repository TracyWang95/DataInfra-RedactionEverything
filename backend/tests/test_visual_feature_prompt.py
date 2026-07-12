"""Checklist chat prompt = Targets + one short Query line per type.

The old prompt carried every Check/Exclude checklist row — verbose text the
official model card does not want as [CATEGORIES], measured to suppress faint
detections, and never read by the LA server after the Query-line switch. Per
owner decision those rows are purged outright (no "kept as context" residue):
the prompt is Schema header + Targets with type_id/name/Query only.
"""
from types import SimpleNamespace

from app.services.vision.locate_grounding import _checklist_prompt


def _item(id: str, name: str, checklist=None):
    return SimpleNamespace(
        id=id, name=name,
        description="Visible handwritten signing strokes.",
        checklist=checklist or [
            {
                "rule": "Handwritten signer name or signature strokes",
                "positive_prompt": "Tight box around visible ink strokes",
                "negative_prompt": "Printed labels, blank signing lines, table borders, or stamps",
            }
        ],
        negative_prompt_enabled=True,
        negative_prompt="Do not output blank signing areas.",
    )


def test_prompt_is_targets_plus_query_lines_only() -> None:
    prompt = _checklist_prompt([_item("signature", "Signature")])
    assert "Targets:" in prompt
    assert "type_id=signature" in prompt
    assert "  Query: Signature" in prompt
    assert '"type_id":"<allowed type_id>"' in prompt
    # verbose checklist rows are purged, not carried as context
    assert "Check:" not in prompt
    assert "Exclude:" not in prompt
    assert "Handwritten signer name or signature strokes" not in prompt
    assert "Do not output blank signing areas." not in prompt


def test_row_query_field_feeds_the_query_line() -> None:
    item = _item(
        "custom_visual_features_approval_note", "Approval note",
        checklist=[{"rule": "手写批注", "query": "handwritten approval note"}],
    )
    prompt = _checklist_prompt([item])
    assert "custom_visual_features_approval_note" in prompt
    assert "  Query: handwritten approval note" in prompt
    assert '"objects"' in prompt
    assert '"type_id":"signature"' not in prompt
