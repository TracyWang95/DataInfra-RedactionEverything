from __future__ import annotations

from app.core.config import settings
from app.models.schemas import PresetCreate
from app.services import entity_type_service, pipeline_service, preset_service
from app.services.entity_type_service import CreateEntityTypeRequest
from app.services.pipeline_service import PipelineTypeConfig


def _scope_runtime_config(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ENTITY_TYPES_STORE_PATH", str(tmp_path / "entity_types.json"))
    monkeypatch.setattr(settings, "PRESET_STORE_PATH", str(tmp_path / "presets.json"))
    monkeypatch.setattr(settings, "PIPELINE_STORE_PATH", str(tmp_path / "pipelines.json"))


def test_tenant_entity_types_are_isolated(monkeypatch, tmp_path):
    _scope_runtime_config(monkeypatch, tmp_path)

    created = entity_type_service.create_type(
        CreateEntityTypeRequest(
            name="Alice Secret Code",
            data_domain="custom_extension",
            generic_target="GEN_NUMBER_CODE",
            description="Alice-only code",
        ),
        owner_id="alice",
    )

    alice_ids = {item.id for item in entity_type_service.list_types(owner_id="alice").custom_types}
    bob_ids = {item.id for item in entity_type_service.list_types(owner_id="bob").custom_types}

    assert created.id in alice_ids
    assert created.id not in bob_ids
    assert entity_type_service.resolve_requested_entity_types([created.id], owner_id="alice")
    assert entity_type_service.resolve_requested_entity_types([created.id], owner_id="bob") == []


def test_tenant_presets_are_isolated(monkeypatch, tmp_path):
    _scope_runtime_config(monkeypatch, tmp_path)

    created = preset_service.create(
        PresetCreate(
            name="Alice Data Room",
            kind="text",
            selectedEntityTypeIds=["GEN_NAME"],
            replacementMode="structured",
        ),
        owner_id="alice",
    )

    alice_ids = {preset.id for preset in preset_service.list_presets(owner_id="alice").presets}
    bob_ids = {preset.id for preset in preset_service.list_presets(owner_id="bob").presets}
    bob_export_ids = {preset["id"] for preset in preset_service.export_all(owner_id="bob")["presets"]}

    assert created.id in alice_ids
    assert created.id not in bob_ids
    assert created.id not in bob_export_ids


def test_tenant_vision_pipeline_types_are_isolated(monkeypatch, tmp_path):
    _scope_runtime_config(monkeypatch, tmp_path)

    custom = PipelineTypeConfig(
        id="custom_alice_signature",
        name="Alice Signature",
        description="Alice-only signature prompt",
        color="#6B7280",
        enabled=True,
        order=100,
    )
    created, error = pipeline_service.add_pipeline_type("vlm", custom, owner_id="alice")

    assert error == ""
    assert created is not None
    assert "custom_alice_signature" in {
        item.id for item in pipeline_service.get_pipeline_types("vlm", False, owner_id="alice") or []
    }
    assert "custom_alice_signature" not in {
        item.id for item in pipeline_service.get_pipeline_types("vlm", False, owner_id="bob") or []
    }


def test_tenant_reset_only_resets_current_owner(monkeypatch, tmp_path):
    _scope_runtime_config(monkeypatch, tmp_path)

    alice = entity_type_service.create_type(
        CreateEntityTypeRequest(
            name="Alice Reset Target",
            data_domain="custom_extension",
            generic_target="GEN_NAME",
        ),
        owner_id="alice",
    )
    bob = entity_type_service.create_type(
        CreateEntityTypeRequest(
            name="Bob Survives Reset",
            data_domain="custom_extension",
            generic_target="GEN_NAME",
        ),
        owner_id="bob",
    )

    entity_type_service.reset_types(owner_id="alice")

    assert entity_type_service.get_type(alice.id, owner_id="alice") is None
    assert entity_type_service.get_type(bob.id, owner_id="bob") is not None
