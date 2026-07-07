# -*- coding: utf-8 -*-
"""Add the government/xinchuang industry preset (Phase 2, 4th vertical).

Aggregates (dataDomains/genericTargets/linkageGroups) are DERIVED from the
type catalog so the builtin-preset contract validation cannot drift. Idempotent.
Run from backend/: python scripts/add_gov_preset.py
"""
import json

GOV_TYPES = [
    "PERSON",
    "ID_CARD",
    "PASSPORT",
    "PHONE",
    "EMAIL",
    "ADDRESS",
    "INSTITUTION_NAME",
    "DATE",
    "SOCIAL_SECURITY",
    "DOCUMENT_NUMBER",
    "BANK_CARD",
]

catalog = json.load(open("config/preset_entity_types.json", encoding="utf-8"))
missing = [t for t in GOV_TYPES if t not in catalog]
assert not missing, f"catalog missing: {missing}"

preset = {
    "id": "industry_gov_document_release",
    "name": "Industry - Government document release",
    "kind": "full",
    "selectedEntityTypeIds": GOV_TYPES,
    "ocrHasTypes": GOV_TYPES,
    "visualFeatureTypes": ["face", "id_card", "passport", "official_seal", "signature", "fingerprint"],
    "replacementMode": "structured",
    "created_at": "2026-07-04T00:00:00+00:00",
    "updated_at": "2026-07-04T00:00:00+00:00",
    "dataDomains": sorted({catalog[t]["data_domain"] for t in GOV_TYPES}),
    "genericTargets": sorted({catalog[t]["generic_target"] for t in GOV_TYPES}),
    "linkageGroups": sorted({g for t in GOV_TYPES for g in catalog[t]["linkage_groups"]}),
}

path = "config/industry_presets.json"
presets = json.load(open(path, encoding="utf-8"))
presets = [p for p in presets if p.get("id") != preset["id"]]
presets.append(preset)
with open(path, "w", encoding="utf-8", newline="") as fh:
    json.dump(presets, fh, ensure_ascii=False, indent=2)
print("written:", preset["id"])

from app.services import preset_service  # noqa: E402  (validates contract on load)

result = preset_service.list_presets()
print("presets loaded OK:", [p.id for p in result.presets])
