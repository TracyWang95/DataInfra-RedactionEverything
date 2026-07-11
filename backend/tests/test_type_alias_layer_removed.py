"""The historical alias/cn_terms translation layer is deleted (owner decision).

Guards two things the deletion changed:
1. 案号(LEGAL_CASE_ID)/健康信息(HEALTH_INFO) were legitimate preset entries the
   alias filter silently suppressed — they are first-class checklist items now,
   so the factory legal industry preset's direct LEGAL_CASE_ID reference
   resolves without any alias folding.
2. Every entity-type id referenced by every factory industry preset resolves
   to a real config — a preset referencing an unknown id would silently skip
   that whole type (a missed redaction); this turns it into a red test.
"""
import json
import os

from app.services.entity_type_service import PRESET_ENTITY_TYPES

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


def test_alias_translation_layer_is_gone() -> None:
    import app.models.type_mapping as tm

    assert not hasattr(tm, "TYPE_ID_ALIASES")
    assert not hasattr(tm, "TYPE_CN_TO_ID")
    assert not hasattr(tm, "cn_to_id")
    # pure string hygiene only — no remapping
    assert tm.canonical_type_id("legal-case id") == "LEGAL_CASE_ID"
    assert tm.canonical_type_id("LEGAL_CASE_ID") == "LEGAL_CASE_ID"


def test_suppressed_preset_entries_are_first_class_now() -> None:
    assert "LEGAL_CASE_ID" in PRESET_ENTITY_TYPES
    assert "HEALTH_INFO" in PRESET_ENTITY_TYPES
    assert PRESET_ENTITY_TYPES["LEGAL_CASE_ID"].name  # 案号 carries a real name


def test_every_industry_preset_type_id_resolves() -> None:
    path = os.path.join(_CONFIG_DIR, "industry_presets.json")
    with open(path, encoding="utf-8") as fh:
        presets = json.load(fh)
    entries = presets if isinstance(presets, list) else presets.get("presets", [])
    checked = 0
    for preset in entries:
        for key in ("selectedEntityTypeIds", "ocrHasTypes"):
            for type_id in preset.get(key) or []:
                if str(type_id).startswith("custom_"):
                    continue
                assert type_id in PRESET_ENTITY_TYPES, (
                    f"industry preset {preset.get('id')} references unknown type "
                    f"{type_id!r} — it would be silently skipped (missed redaction)"
                )
                checked += 1
    assert checked > 0, "no ids checked — preset file shape changed?"
