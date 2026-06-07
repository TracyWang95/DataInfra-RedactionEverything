from app.models.type_mapping import canonical_type_id, id_to_cn
from app.services.entity_type_service import get_default_generic_types, resolve_requested_entity_types
from app.core.visual_feature_categories import VISUAL_FEATURE_CLASS_COUNT
from app.services.pipeline_service import get_pipeline_types_for_mode, merge_pipeline_disk_snapshot
from app.services.preset_service import _load_builtin_presets


def test_bank_name_is_first_class_type():
    assert canonical_type_id("BANK_NAME") == "BANK_NAME"
    assert id_to_cn("BANK_NAME") == "开户行"
    assert [item.id for item in resolve_requested_entity_types(["BANK_NAME"])] == ["BANK_NAME"]


def test_bank_name_is_in_default_text_and_ocr_configs():
    default_ids = {item.id for item in get_default_generic_types()}
    assert "GEN_NUMBER_CODE" not in default_ids
    assert "GEN_ACCOUNT_TRANSACTION" not in default_ids
    assert "PERSON" in default_ids
    assert "BANK_NAME" in default_ids
    assert "BANK_NAME" in {item.id for item in get_pipeline_types_for_mode("ocr_has", enabled_only=True)}


def test_l2_generic_target_is_not_a_ner_entity():
    resolved = [item.id for item in resolve_requested_entity_types(["GEN_NUMBER_CODE"])]
    assert resolved == []


def test_builtin_presets_include_bank_name_where_bank_account_is_enabled():
    for preset in _load_builtin_presets():
        selected = set(preset.get("selectedEntityTypeIds") or [])
        ocr_has = set(preset.get("ocrHasTypes") or [])
        if "BANK_ACCOUNT" in selected:
            assert "BANK_NAME" in selected
        if "BANK_ACCOUNT" in ocr_has:
            assert "BANK_NAME" in ocr_has


def test_visual_elements_fixed_preset_has_paper_and_signature_enabled():
    assert VISUAL_FEATURE_CLASS_COUNT == 22
    enabled_ids = {item.id for item in get_pipeline_types_for_mode("visual_features", enabled_only=True)}
    assert "paper" in enabled_ids
    assert "signature" in enabled_ids


def test_visual_feature_snapshot_merges_fixed_and_custom_visual_elements():
    raw = {
        "visual_features": {
            "mode": "visual_features",
            "name": "visual features",
            "description": "visual features",
            "enabled": True,
            "types": [
                {"id": "paper", "name": "paper", "enabled": False},
                {"id": "signature", "name": "signature", "enabled": True},
                {"id": "custom_visual_features_note", "name": "custom note", "enabled": True},
            ],
        },
    }
    merged = merge_pipeline_disk_snapshot(raw)
    visual_enabled = {item.id for item in merged["visual_features"].types if item.enabled}
    visual_ids = {item.id for item in merged["visual_features"].types}
    assert "signature" in visual_enabled
    assert "custom_visual_features_note" in visual_ids
