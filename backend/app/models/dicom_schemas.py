"""Framework-independent models for DICOM inspection and de-identification.

The models intentionally contain no FastAPI types.  They are shared by the
core DICOM service, background jobs and (eventually) the HTTP adapter.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DICOMTagAction(str, Enum):
    """DICOM PS3.15-style attribute confidentiality actions.

    The values match the action letters used by the Basic Application Level
    Confidentiality Profile: remove (X), zero length (Z), dummy (D), UID
    replacement (U), keep (K), and clean (C).
    """

    REMOVE = "X"
    EMPTY = "Z"
    DUMMY = "D"
    UID = "U"
    KEEP = "K"
    CLEAN = "C"


class DICOMRiskSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    BLOCKING = "blocking"


class DICOMPixelStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    CLEAR = "clear"
    REVIEW_REQUIRED = "review_required"
    VERIFIED_CLEAR = "verified_clear"
    EXTERNALLY_REDACTED = "externally_redacted"
    BLOCKED = "blocked"


class DICOMTagRule(BaseModel):
    """A rule addressed by DICOM keyword or hexadecimal tag."""

    selector: str
    action: DICOMTagAction
    value: Any | None = None
    reason: str = ""


class DICOMPolicy(BaseModel):
    profile: str = "basic"
    rules: list[DICOMTagRule] = Field(default_factory=list)
    clean_preamble: bool = True
    clean_file_meta: bool = True
    clean_overlays: bool = True
    clean_pixel_data: bool = False
    clean_structured_content: bool = False
    clean_descriptors: bool = True
    clean_recognizable_visual_features: bool = False
    remove_private_tags: bool = True
    safe_private_tags: list[str] = Field(default_factory=list)
    retain_longitudinal_dates: bool = True
    date_mode: Literal["remove", "shift", "retain"] = "shift"
    date_shift_range_days: int = Field(default=3650, ge=1, le=36500)
    retain_patient_characteristics: bool = False
    retain_device_identity: bool = False
    retain_institution_identity: bool = False
    retain_uids: bool = False
    supported_modalities: list[str] = Field(default_factory=lambda: ["CT", "MR", "CR", "DX"])
    require_decodable_pixel_data: bool = True


class DICOMRisk(BaseModel):
    code: str
    severity: DICOMRiskSeverity
    message: str
    path: str | None = None
    study_instance_uid: str | None = None
    series_instance_uid: str | None = None
    sop_instance_uid: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DICOMInstanceIndex(BaseModel):
    path: str
    study_instance_uid: str
    series_instance_uid: str
    sop_instance_uid: str
    sop_class_uid: str
    modality: str = ""
    transfer_syntax_uid: str = ""
    number_of_frames: int = 1
    rows: int | None = None
    columns: int | None = None
    has_pixel_data: bool = False
    is_compressed: bool = False
    patient_reference: str = ""
    source_sha256: str = ""
    metadata_summary: dict[str, Any] = Field(default_factory=dict)
    risks: list[DICOMRisk] = Field(default_factory=list)


class DICOMSeriesIndex(BaseModel):
    series_instance_uid: str
    study_instance_uid: str
    modality: str = ""
    series_number: str = ""
    description: str = ""
    instances: list[DICOMInstanceIndex] = Field(default_factory=list)


class DICOMStudyIndex(BaseModel):
    study_instance_uid: str
    patient_reference: str
    study_date: str = ""
    description: str = ""
    modalities: list[str] = Field(default_factory=list)
    series: list[DICOMSeriesIndex] = Field(default_factory=list)


class DICOMInspection(BaseModel):
    status: str = "ready"
    sources_scanned: int = 0
    dicom_count: int = 0
    skipped: list[dict[str, str]] = Field(default_factory=list)
    studies: list[DICOMStudyIndex] = Field(default_factory=list)
    instances: list[DICOMInstanceIndex] = Field(default_factory=list)
    risks: list[DICOMRisk] = Field(default_factory=list)


class DICOMPreflight(BaseModel):
    status: str
    can_execute: bool
    profile: str
    inspection: DICOMInspection
    risks: list[DICOMRisk] = Field(default_factory=list)
    blocking_risks: list[DICOMRisk] = Field(default_factory=list)
    review_required: list[DICOMRisk] = Field(default_factory=list)


class DICOMTagChange(BaseModel):
    path: str
    tag: str
    keyword: str = ""
    vr: str = ""
    action: DICOMTagAction
    reason: str = ""


class DICOMInstanceResult(BaseModel):
    source_path: str
    output_path: str
    source_sha256: str
    output_sha256: str
    original_study_instance_uid: str
    original_series_instance_uid: str
    original_sop_instance_uid: str
    study_instance_uid: str
    series_instance_uid: str
    sop_instance_uid: str
    pixel_status: DICOMPixelStatus
    changes: list[DICOMTagChange] = Field(default_factory=list)
    overlays_removed: int = 0
    pixel_regions_redacted: int = Field(default=0, ge=0)
    validation_ok: bool = False


class DICOMValidationIssue(BaseModel):
    code: str
    severity: DICOMRiskSeverity
    message: str
    path: str | None = None
    tag: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DICOMValidationReport(BaseModel):
    ok: bool
    checked_instances: int = 0
    issues: list[DICOMValidationIssue] = Field(default_factory=list)
    study_count: int = 0
    series_count: int = 0
    instance_count: int = 0


class DICOMDeidentificationReport(BaseModel):
    status: str
    profile: str
    patient_identity_removed: Literal["YES"] = "YES"
    started_at: str
    completed_at: str
    output_dir: str
    instances: list[DICOMInstanceResult] = Field(default_factory=list)
    output_paths: list[str] = Field(default_factory=list)
    risks: list[DICOMRisk] = Field(default_factory=list)
    action_counts: dict[str, int] = Field(default_factory=dict)
    validation: DICOMValidationReport
    mapping_namespace: str = "default"
    reversible_mapping_stored: bool = False


__all__ = [
    "DICOMDeidentificationReport",
    "DICOMInspection",
    "DICOMInstanceIndex",
    "DICOMInstanceResult",
    "DICOMPixelStatus",
    "DICOMPolicy",
    "DICOMPreflight",
    "DICOMRisk",
    "DICOMRiskSeverity",
    "DICOMSeriesIndex",
    "DICOMStudyIndex",
    "DICOMTagAction",
    "DICOMTagChange",
    "DICOMTagRule",
    "DICOMValidationIssue",
    "DICOMValidationReport",
]
