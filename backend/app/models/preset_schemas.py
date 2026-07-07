"""
Preset (batch-wizard configuration template) schemas.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "PresetKind",
    "PresetPayload",
    "PresetCreate",
    "PresetUpdate",
    "PresetOut",
    "PresetsListResponse",
    "PresetImportItem",
    "PresetImportRequest",
]

PresetKind = Literal["text", "vision", "full"]


class PresetPayload(BaseModel):
    """Reusable batch recognition configuration shared by the wizard and API."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Display name shown in the batch preset picker.",
        examples=["Industry - Contract and legal disclosure"],
    )
    kind: PresetKind = Field(
        default="full",
        description=(
            "Recognition scope for the preset: text uses text/OCR entities only, "
            "vision uses visual categories only, and full enables both pipelines."
        ),
        examples=["full"],
    )
    selectedEntityTypeIds: list[str] = Field(
        default_factory=list,
        description="Entity type ids selected for text recognition and redaction.",
        examples=[["PERSON", "EMAIL", "ORG", "CASE_NUMBER"]],
    )
    ocrHasTypes: list[str] = Field(
        default_factory=list,
        description="OCR/HaS text type ids enabled for paged documents.",
        examples=[["PERSON", "EMAIL", "ORG", "CASE_NUMBER"]],
    )
    visualFeatureTypes: list[str] = Field(
        default_factory=list,
        description="Visual feature ids enabled for LocateAnything recognition.",
        examples=[["face", "official_seal", "qr_code"]],
    )
    dataDomains: list[str] = Field(
        default_factory=list,
        description="L1 data domains covered by the preset.",
        examples=[["pii", "organization_subject"]],
    )
    genericTargets: list[str] = Field(
        default_factory=list,
        description="L2 generic targets covered by the preset.",
        examples=[["GEN_NAME", "GEN_NUMBER_CODE"]],
    )
    linkageGroups: list[str] = Field(
        default_factory=list,
        description="Coreference/linkage groups covered by the preset.",
        examples=[["organization_like", "person_like"]],
    )
    replacementMode: Literal["structured", "smart", "mask"] = Field(
        default="structured",
        description="How detected content is replaced in redacted output.",
        examples=["structured"],
    )


class PresetCreate(PresetPayload):
    pass


class PresetUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="New display name for a user-owned preset.",
        examples=["Partner data-room review"],
    )
    kind: PresetKind | None = Field(
        default=None,
        description="New recognition scope for a user-owned preset.",
        examples=["text"],
    )
    selectedEntityTypeIds: list[str] | None = Field(
        default=None,
        description="Replacement entity type ids. Omit to keep the current value.",
        examples=[["PERSON", "PHONE", "EMAIL"]],
    )
    ocrHasTypes: list[str] | None = Field(
        default=None,
        description="Replacement OCR/HaS text type ids. Omit to keep the current value.",
        examples=[["PERSON", "PHONE", "EMAIL"]],
    )
    visualFeatureTypes: list[str] | None = Field(
        default=None,
        description="Replacement visual feature ids. Omit to keep the current value.",
        examples=[["face", "official_seal"]],
    )
    dataDomains: list[str] | None = Field(
        default=None,
        description="Replacement L1 data domains. Omit to keep the current value.",
        examples=[["pii", "organization_subject"]],
    )
    genericTargets: list[str] | None = Field(
        default=None,
        description="Replacement L2 generic targets. Omit to keep the current value.",
        examples=[["GEN_NAME", "GEN_NUMBER_CODE"]],
    )
    linkageGroups: list[str] | None = Field(
        default=None,
        description="Replacement linkage groups. Omit to keep the current value.",
        examples=[["organization_like", "person_like"]],
    )
    replacementMode: Literal["structured", "smart", "mask"] | None = Field(
        default=None,
        description="Replacement strategy for future redaction runs. Omit to keep the current value.",
        examples=["mask"],
    )


class PresetOut(PresetPayload):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "industry_contract_legal_disclosure",
                    "name": "Industry - Contract and legal disclosure",
                    "kind": "full",
                    "selectedEntityTypeIds": ["PERSON", "ORG", "CASE_NUMBER", "AMOUNT"],
                    "ocrHasTypes": ["PERSON", "ORG", "CASE_NUMBER", "AMOUNT"],
                    "visualFeatureTypes": ["official_seal", "qr_code"],
                    "replacementMode": "structured",
                    "created_at": "2026-05-05T00:00:00+00:00",
                    "updated_at": "2026-05-05T00:00:00+00:00",
                    "readonly": True,
                }
            ]
        }
    )

    id: str = Field(
        description="Stable preset id used by API clients.",
        examples=["industry_contract_legal_disclosure"],
    )
    created_at: str = Field(
        description="ISO timestamp when the preset was created.",
        examples=["2026-05-05T00:00:00+00:00"],
    )
    updated_at: str = Field(
        description="ISO timestamp when the preset was last updated.",
        examples=["2026-05-05T00:00:00+00:00"],
    )
    readonly: bool = Field(
        default=False,
        description=(
            "True for built-in industry presets. Read-only presets are safe defaults for users to copy, "
            "but update, delete, and import override operations are rejected."
        ),
        examples=[True],
    )


class PresetsListResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "presets": [
                        {
                            "id": "industry_contract_legal_disclosure",
                            "name": "Industry - Contract and legal disclosure",
                            "kind": "full",
                            "selectedEntityTypeIds": ["PERSON", "ORG", "CASE_NUMBER", "AMOUNT"],
                            "ocrHasTypes": ["PERSON", "ORG", "CASE_NUMBER", "AMOUNT"],
                            "visualFeatureTypes": ["official_seal", "qr_code"],
                            "replacementMode": "structured",
                            "created_at": "2026-05-05T00:00:00+00:00",
                            "updated_at": "2026-05-05T00:00:00+00:00",
                            "readonly": True,
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 1,
                }
            ]
        }
    )

    presets: list[PresetOut] = Field(
        description="Built-in read-only presets followed by user-owned presets."
    )
    total: int = Field(description="Total number of presets before pagination.", examples=[8])
    page: int = Field(default=1, description="1-based page number.", examples=[1])
    page_size: int = Field(
        default=50,
        description="Returned page size; 0 in the request means return all.",
        examples=[50],
    )


class PresetImportItem(PresetPayload):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Imported user preset id. Built-in read-only ids are ignored and cannot be overridden.",
        examples=["partner_data_room_review"],
    )
    created_at: str | None = Field(
        default=None,
        description="Optional original creation timestamp. The server fills this when omitted.",
        examples=["2026-05-05T00:00:00+00:00"],
    )
    updated_at: str | None = Field(
        default=None,
        description="Optional original update timestamp. The server fills this when omitted.",
        examples=["2026-05-05T00:00:00+00:00"],
    )
    readonly: bool = Field(
        default=False,
        description="Ignored on import for user presets; built-in read-only presets remain protected by id.",
        examples=[False],
    )


class PresetImportRequest(BaseModel):
    presets: list[PresetImportItem] = Field(
        description="User presets to import. Rows using built-in read-only ids are skipped."
    )
    merge: bool = Field(
        default=False,
        description="True merges new user presets with existing ones; false replaces the user preset store.",
        examples=[False],
    )


