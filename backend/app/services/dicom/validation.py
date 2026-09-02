"""Post-write DICOM structural and confidentiality validation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydicom.dataset import Dataset

from app.models.dicom_schemas import (
    DICOMPolicy,
    DICOMRiskSeverity,
    DICOMValidationIssue,
    DICOMValidationReport,
)

from .pixel import decoded_frames
from .reader import read_dataset

_LEAK_SCAN_KEYWORDS = {
    "PatientName",
    "PatientID",
    "IssuerOfPatientID",
    "OtherPatientNames",
    "PatientBirthName",
    "PatientBirthDate",
    "PatientAddress",
    "PatientMotherBirthName",
    "PatientTelephoneNumbers",
    "PatientTelecomInformation",
    "MedicalRecordLocator",
    "AccessionNumber",
    "AdmissionID",
    "ServiceEpisodeID",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "RequestingPhysician",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "StudyDescription",
    "StudyComments",
    "SeriesDescription",
    "ProtocolName",
    "RequestedProcedureDescription",
    "ImageComments",
}


@dataclass
class ExpectedOutput:
    study_instance_uid: str
    series_instance_uid: str
    sop_instance_uid: str
    pixel_sha256: str
    pixel_modified: bool = False
    pixel_frame_shapes: tuple[tuple[int, ...], ...] = ()
    frame_count: int = 0
    redacted_region_count: int = 0
    original_sensitive_values: set[str] = field(default_factory=set)


def pixel_data_sha256(dataset: Dataset) -> str:
    value = dataset.get("PixelData")
    if value is None:
        return ""
    raw = value.value if hasattr(value, "value") else value
    return hashlib.sha256(bytes(raw)).hexdigest()


def _iter_elements(dataset: Dataset) -> Iterable[Any]:
    for element in dataset:
        yield element
        if element.VR == "SQ":
            for item in element.value or []:
                yield from _iter_elements(item)


def _string_values(element: Any) -> list[str]:
    if element.VR in {"OB", "OW", "OF", "OD", "OL", "OV", "UN", "SQ"}:
        return []
    value = element.value
    if isinstance(value, str | int | float):
        return [str(value)]
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def _private_allowed(element: Any, policy: DICOMPolicy) -> bool:
    allowed = {
        item.replace("(", "").replace(")", "").replace(",", "").replace(" ", "").upper()
        for item in policy.safe_private_tags
    }
    for tag in tuple(allowed):
        if len(tag) == 8 and int(tag[:4], 16) % 2 and int(tag[4:], 16) >= 0x1000:
            allowed.add(f"{tag[:4]}{int(tag[4:], 16) >> 8:04X}")
    tag = f"{element.tag.group:04X}{element.tag.element:04X}"
    return tag in allowed or (element.keyword or "") in policy.safe_private_tags


def validate_output_paths(
    paths: Iterable[str | Path],
    *,
    policy: DICOMPolicy,
    expected: dict[str, ExpectedOutput] | None = None,
    original_uid_mapping: dict[str, str] | None = None,
) -> DICOMValidationReport:
    issues: list[DICOMValidationIssue] = []
    checked = 0
    study_uids: set[str] = set()
    series_uids: set[str] = set()
    sop_uids: set[str] = set()
    expected = expected or {}
    uid_mapping = original_uid_mapping or {}

    for raw_path in paths:
        path = Path(raw_path).resolve()
        try:
            dataset = read_dataset(path, stop_before_pixels=False)
        except Exception as exc:
            issues.append(
                DICOMValidationIssue(
                    code="OUTPUT_PARSE_FAILED",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message=f"Output is not a readable DICOM file: {type(exc).__name__}",
                    path=str(path),
                )
            )
            continue
        checked += 1
        study_uid = str(dataset.get("StudyInstanceUID", ""))
        series_uid = str(dataset.get("SeriesInstanceUID", ""))
        sop_uid = str(dataset.get("SOPInstanceUID", ""))
        study_uids.add(study_uid)
        series_uids.add(series_uid)
        if not sop_uid or sop_uid in sop_uids:
            issues.append(
                DICOMValidationIssue(
                    code="OUTPUT_SOP_UID_DUPLICATE_OR_MISSING",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="Output SOP Instance UID is missing or duplicated",
                    path=str(path),
                )
            )
        sop_uids.add(sop_uid)

        if str(dataset.get("PatientIdentityRemoved", "")).upper() != "YES":
            issues.append(
                DICOMValidationIssue(
                    code="PATIENT_IDENTITY_REMOVED_FLAG_MISSING",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="Patient Identity Removed (0012,0062) must be YES",
                    path=str(path),
                    tag="0012,0062",
                )
            )
        if not str(dataset.get("DeidentificationMethod", "")).strip():
            issues.append(
                DICOMValidationIssue(
                    code="DEIDENTIFICATION_METHOD_MISSING",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="De-identification Method (0012,0063) is required",
                    path=str(path),
                    tag="0012,0063",
                )
            )
        method_codes = dataset.get("DeidentificationMethodCodeSequence", []) or []
        if not any(str(item.get("CodeValue", "")) == "113100" for item in method_codes):
            issues.append(
                DICOMValidationIssue(
                    code="BASIC_PROFILE_CODE_MISSING",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="The Basic Application Confidentiality Profile code is missing",
                    path=str(path),
                    tag="0012,0064",
                )
            )

        if policy.clean_preamble and dataset.preamble and any(dataset.preamble):
            issues.append(
                DICOMValidationIssue(
                    code="NONZERO_PREAMBLE",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="Output DICOM preamble contains non-zero bytes",
                    path=str(path),
                )
            )

        for element in _iter_elements(dataset):
            tag_text = f"{element.tag.group:04X},{element.tag.element:04X}"
            if element.tag.is_private and policy.remove_private_tags and not _private_allowed(element, policy):
                issues.append(
                    DICOMValidationIssue(
                        code="PRIVATE_TAG_REMAINS",
                        severity=DICOMRiskSeverity.BLOCKING,
                        message="A non-approved private attribute remains in the output",
                        path=str(path),
                        tag=tag_text,
                    )
                )
            if element.VR == "UI" and not policy.retain_uids:
                for value in _string_values(element):
                    mapped = uid_mapping.get(value)
                    if mapped and mapped != value:
                        issues.append(
                            DICOMValidationIssue(
                                code="ORIGINAL_UID_REMAINS",
                                severity=DICOMRiskSeverity.BLOCKING,
                                message="An original identity/reference UID remains in output",
                                path=str(path),
                                tag=tag_text,
                            )
                        )

        context = expected.get(str(path))
        output_frames = None
        if policy.require_decodable_pixel_data or (context is not None and context.pixel_frame_shapes):
            try:
                output_frames = decoded_frames(dataset, source_path=path)
            except Exception as exc:
                issues.append(
                    DICOMValidationIssue(
                        code="OUTPUT_PIXEL_DECODE_FAILED",
                        severity=DICOMRiskSeverity.BLOCKING,
                        message="Output Pixel Data cannot be decoded",
                        path=str(path),
                        details={"error": f"{type(exc).__name__}: {exc}"},
                    )
                )
        if context is not None:
            actual = (study_uid, series_uid, sop_uid)
            wanted = (context.study_instance_uid, context.series_instance_uid, context.sop_instance_uid)
            if actual != wanted:
                issues.append(
                    DICOMValidationIssue(
                        code="HIERARCHY_UID_MISMATCH",
                        severity=DICOMRiskSeverity.BLOCKING,
                        message="Written hierarchy UIDs do not match the deterministic mapping",
                        path=str(path),
                        details={"expected": list(wanted), "actual": list(actual)},
                    )
                )
            actual_pixel_hash = pixel_data_sha256(dataset)
            if context.pixel_modified and actual_pixel_hash == context.pixel_sha256:
                issues.append(
                    DICOMValidationIssue(
                        code="PIXEL_DATA_NOT_CHANGED_AFTER_REDACTION",
                        severity=DICOMRiskSeverity.BLOCKING,
                        message="Pixel Data is unchanged even though detector regions were scheduled for redaction",
                        path=str(path),
                    )
                )
            elif not context.pixel_modified and actual_pixel_hash != context.pixel_sha256:
                issues.append(
                    DICOMValidationIssue(
                        code="PIXEL_DATA_CHANGED_UNEXPECTEDLY",
                        severity=DICOMRiskSeverity.BLOCKING,
                        message="Pixel Data changed even though no pixel-redaction writer was invoked",
                        path=str(path),
                    )
                )
            if context.pixel_modified:
                if context.redacted_region_count < 1:
                    issues.append(
                        DICOMValidationIssue(
                            code="PIXEL_REDACTION_EVIDENCE_MISSING",
                            severity=DICOMRiskSeverity.BLOCKING,
                            message="Pixel redaction was expected but has no applied detector-region count",
                            path=str(path),
                        )
                    )
                if str(dataset.get("BurnedInAnnotation", "")).upper().strip() != "NO":
                    issues.append(
                        DICOMValidationIssue(
                            code="BURNED_IN_ANNOTATION_NOT_CLEARED",
                            severity=DICOMRiskSeverity.BLOCKING,
                            message="Burned In Annotation must be NO after automatic pixel redaction",
                            path=str(path),
                            tag="0028,0301",
                        )
                    )
                if not any(str(item.get("CodeValue", "")) == "113101" for item in method_codes):
                    issues.append(
                        DICOMValidationIssue(
                            code="CLEAN_PIXEL_DATA_CODE_MISSING",
                            severity=DICOMRiskSeverity.BLOCKING,
                            message="The Clean Pixel Data Option code is missing after automatic redaction",
                            path=str(path),
                            tag="0012,0064",
                        )
                    )
            if output_frames is not None:
                actual_shapes = tuple(tuple(int(dimension) for dimension in frame.shape) for frame in output_frames)
                if context.frame_count and len(output_frames) != context.frame_count:
                    issues.append(
                        DICOMValidationIssue(
                            code="PIXEL_FRAME_COUNT_CHANGED",
                            severity=DICOMRiskSeverity.BLOCKING,
                            message="Pixel frame count changed during de-identification",
                            path=str(path),
                            details={"expected": context.frame_count, "actual": len(output_frames)},
                        )
                    )
                if context.pixel_frame_shapes and actual_shapes != context.pixel_frame_shapes:
                    issues.append(
                        DICOMValidationIssue(
                            code="PIXEL_FRAME_SHAPE_CHANGED",
                            severity=DICOMRiskSeverity.BLOCKING,
                            message="Pixel frame geometry or sample shape changed during de-identification",
                            path=str(path),
                            details={
                                "expected": [list(shape) for shape in context.pixel_frame_shapes],
                                "actual": [list(shape) for shape in actual_shapes],
                            },
                        )
                    )
            if context.original_sensitive_values:
                for element in _iter_elements(dataset):
                    if element.keyword not in _LEAK_SCAN_KEYWORDS and element.VR != "PN":
                        continue
                    for value in _string_values(element):
                        value_folded = value.casefold()
                        leaked = next(
                            (
                                source
                                for source in context.original_sensitive_values
                                if len(source) >= 3 and source.casefold() == value_folded
                            ),
                            None,
                        )
                        if leaked:
                            issues.append(
                                DICOMValidationIssue(
                                    code="SOURCE_IDENTIFIER_VALUE_REMAINS",
                                    severity=DICOMRiskSeverity.BLOCKING,
                                    message="A source identifying value remains in a textual attribute",
                                    path=str(path),
                                    tag=f"{element.tag.group:04X},{element.tag.element:04X}",
                                    details={"source_value_sha256": hashlib.sha256(leaked.encode()).hexdigest()},
                                )
                            )
                            break

        if policy.clean_file_meta and "SourceApplicationEntityTitle" in dataset.file_meta:
            issues.append(
                DICOMValidationIssue(
                    code="SOURCE_AE_TITLE_REMAINS",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="Source Application Entity Title remains in file meta information",
                    path=str(path),
                    tag="0002,0016",
                )
            )
        if str(dataset.file_meta.get("MediaStorageSOPInstanceUID", "")) != sop_uid:
            issues.append(
                DICOMValidationIssue(
                    code="FILE_META_SOP_UID_MISMATCH",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="File meta and dataset SOP Instance UIDs differ",
                    path=str(path),
                )
            )

    return DICOMValidationReport(
        ok=not any(issue.severity == DICOMRiskSeverity.BLOCKING for issue in issues),
        checked_instances=checked,
        issues=issues,
        study_count=len(study_uids - {""}),
        series_count=len(series_uids - {""}),
        instance_count=len(sop_uids - {""}),
    )


__all__ = ["ExpectedOutput", "pixel_data_sha256", "validate_output_paths"]
