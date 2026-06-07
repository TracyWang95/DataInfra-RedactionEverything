from types import SimpleNamespace

from app.services.vision.locate_grounding import _checklist_prompt


def test_visual_feature_prompt_includes_configured_checklist_rows() -> None:
    prompt = _checklist_prompt(
        [
            SimpleNamespace(
                id="signature",
                name="Signature",
                description="Visible handwritten signing strokes.",
                checklist=[
                    {
                        "rule": "Handwritten signer name or signature strokes",
                        "positive_prompt": "Tight box around visible ink strokes",
                        "negative_prompt": "Printed labels, blank signing lines, table borders, or stamps",
                    }
                ],
                negative_prompt_enabled=True,
                negative_prompt="Do not output blank signing areas.",
            )
        ]
    )

    assert "Configured visual checklist:" in prompt
    assert "type_id=signature" in prompt
    assert "Handwritten signer name or signature strokes" in prompt
    assert "Tight box around visible ink strokes" in prompt
    assert "Do not output blank signing areas." in prompt
    assert '"type_id":"<allowed type_id>"' in prompt


def test_custom_visual_feature_prompt_keeps_generic_output_contract() -> None:
    prompt = _checklist_prompt(
        [
            SimpleNamespace(
                id="custom_visual_features_approval_note",
                name="Approval note",
                description="Handwritten approval notes in margins or blank areas.",
                checklist=[
                    {
                        "rule": "Detect visible handwritten approval comments",
                        "positive_prompt": "Handwritten notes outside printed body text",
                        "negative_prompt": "Printed paragraph text and table borders",
                    }
                ],
                negative_prompt_enabled=True,
                negative_prompt="Do not output signatures or stamps.",
            )
        ]
    )

    assert "custom_visual_features_approval_note" in prompt
    assert "Detect visible handwritten approval comments" in prompt
    assert "Do not output signatures or stamps." in prompt
    assert '"objects"' in prompt
    assert '"type_id":"signature"' not in prompt
