"""Public request models for the DICOM de-identification API.

The response payloads intentionally remain dictionaries.  DICOM metadata is
extensible and vendor objects routinely contain attributes that are not known
to this API layer.  Inputs, however, are closed schemas so callers cannot pass
arbitrary processing switches into the core engine.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DicomProfile(str, Enum):
    BASIC = "basic"
    RESEARCH_STRICT = "research_strict"
    LONGITUDINAL = "longitudinal"
    LONGITUDINAL_RESEARCH = "longitudinal_research"
    INTERNAL_PSEUDONYMIZED = "internal_pseudonymized"
    AI_TRAINING = "ai_training"


class DicomPolicyOptions(BaseModel):
    """Supported DICOM PS3.15 policy switches.

    Defaults are deliberately conservative.  Profile-specific defaults are
    ultimately resolved by the DICOM core; an explicit value here overrides a
    profile default.
    """

    model_config = ConfigDict(extra="forbid")

    clean_pixel_data: bool | None = None
    clean_graphics: bool | None = None
    clean_structured_content: bool | None = None
    clean_descriptors: bool | None = None
    clean_recognizable_visual_features: bool | None = None
    retain_longitudinal_temporal_info: bool | None = None
    retain_patient_characteristics: bool | None = None
    retain_device_identity: bool | None = None
    retain_uids: bool | None = None
    retain_safe_private: bool | None = None
    retain_institution_identity: bool | None = None
    date_mode: Literal["remove", "shift", "retain"] | None = None
    uid_mode: Literal["remap", "retain"] | None = None
    private_tag_policy: Literal["remove", "safe_allowlist"] | None = None
    reversible_pseudonymization: bool | None = None
    fail_on_pixel_decode_error: bool = True

    def core_options(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class DicomPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: DicomProfile = DicomProfile.BASIC
    options: DicomPolicyOptions = Field(default_factory=DicomPolicyOptions)


class DicomRiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(min_length=1, max_length=128)
    resolution: Literal["resolved", "false_positive", "accepted"]
    note: str = Field(default="", max_length=2000)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str) -> str:
        return value.strip()


class DicomReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[DicomRiskDecision] = Field(min_length=1, max_length=1000)

    @field_validator("decisions")
    @classmethod
    def _unique_risks(cls, value: list[DicomRiskDecision]) -> list[DicomRiskDecision]:
        risk_ids = [item.risk_id for item in value]
        if len(risk_ids) != len(set(risk_ids)):
            raise ValueError("risk_id must be unique within a review request")
        return value


class DicomAnonymizeRequest(DicomPreflightRequest):
    expected_preflight_version: int = Field(ge=1)


class DicomBatchAnonymizeRequest(DicomPreflightRequest):
    study_ids: list[str] = Field(min_length=1, max_length=1000)
    expected_preflight_versions: dict[str, int]

    @field_validator("study_ids")
    @classmethod
    def _unique_studies(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("study_ids must not contain empty values")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("study_ids must be unique")
        return cleaned

    @field_validator("expected_preflight_versions")
    @classmethod
    def _positive_versions(cls, value: dict[str, int]) -> dict[str, int]:
        if any(version < 1 for version in value.values()):
            raise ValueError("expected preflight versions must be positive")
        return value

    @model_validator(mode="after")
    def _versions_cover_studies(self) -> DicomBatchAnonymizeRequest:
        expected = set(self.study_ids)
        supplied = set(self.expected_preflight_versions)
        if supplied != expected:
            missing = sorted(expected - supplied)
            unexpected = sorted(supplied - expected)
            raise ValueError(
                f"expected_preflight_versions must match study_ids; missing={missing}, "
                f"unexpected={unexpected}"
            )
        return self


class DicomReviewResolution(str, Enum):
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"
    ACCEPTED = "accepted"
