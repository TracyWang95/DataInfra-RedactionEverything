"""Read-only DICOM discovery, parsing and Study/Series/Instance grouping."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (
    UID,
    ExplicitVRBigEndian,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    MediaStorageDirectoryStorage,
)

from app.models.dicom_schemas import (
    DICOMInspection,
    DICOMInstanceIndex,
    DICOMRisk,
    DICOMRiskSeverity,
    DICOMSeriesIndex,
    DICOMStudyIndex,
)

from .errors import DicomReadError

_DIRECT_IDENTIFIER_KEYWORDS = {
    "PatientName",
    "PatientID",
    "OtherPatientNames",
    "PatientBirthName",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientTelecomInformation",
    "AccessionNumber",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "InstitutionName",
    "InstitutionAddress",
}


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def patient_source_key(dataset: Dataset) -> str:
    patient_id = str(dataset.get("PatientID", "")).strip()
    if patient_id:
        return f"PatientID:{patient_id}"
    combined = "|".join(
        str(dataset.get(keyword, "")).strip() for keyword in ("PatientName", "PatientBirthDate", "PatientSex")
    ).strip("|")
    if combined:
        return f"Demographics:{combined}"
    study_uid = str(dataset.get("StudyInstanceUID", "")).strip()
    return f"StudyInstanceUID:{study_uid or 'UNKNOWN'}"


def patient_reference(dataset: Dataset) -> str:
    raw = patient_source_key(dataset).encode("utf-8", errors="replace")
    return "source-patient-" + hashlib.sha256(b"dicom-inspection-v1\x00" + raw).hexdigest()[:16]


def _normalise_file_id(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # Some writers use a backslash-delimited CS instead of a MultiValue.
        return [part for part in value.replace("/", "\\").split("\\") if part]
    try:
        return [str(part) for part in value]
    except TypeError:
        return [str(value)]


def _expand_dicomdir(path: Path) -> list[Path]:
    try:
        dataset = pydicom.dcmread(path, stop_before_pixels=True, force=False)
    except Exception as exc:
        raise DicomReadError(f"Unable to read DICOMDIR: {path}", details={"path": str(path)}) from exc
    base = path.parent.resolve()
    discovered: list[Path] = []
    for record in dataset.get("DirectoryRecordSequence", []):
        parts = _normalise_file_id(record.get("ReferencedFileID"))
        if not parts:
            continue
        candidate = base.joinpath(*parts).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise DicomReadError(
                "DICOMDIR contains a path outside its directory",
                details={"dicomdir": str(path), "referenced_file_id": parts},
            ) from exc
        if candidate.is_file():
            discovered.append(candidate)
    return discovered


def discover_dicom_paths(
    sources: Iterable[str | Path], *, recursive: bool = True
) -> tuple[list[Path], list[dict[str, str]]]:
    """Resolve input files without ever modifying them.

    DICOMDIR references are expanded.  Directory traversal is deterministic,
    and duplicate resolved paths are removed.
    """

    candidates: list[Path] = []
    skipped: list[dict[str, str]] = []
    for source in sources:
        path = Path(source).expanduser()
        if not path.exists():
            skipped.append({"path": str(path), "reason": "not_found"})
            continue
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            candidates.extend(item for item in iterator if item.is_file())
        elif path.is_file():
            candidates.append(path)
        else:
            skipped.append({"path": str(path), "reason": "not_a_regular_file"})

    expanded: list[Path] = []
    for candidate in sorted(candidates, key=lambda item: str(item).lower()):
        if candidate.name.upper() == "DICOMDIR":
            try:
                expanded.extend(_expand_dicomdir(candidate))
            except DicomReadError as exc:
                skipped.append({"path": str(candidate), "reason": str(exc)})
            continue
        expanded.append(candidate.resolve())

    seen: set[Path] = set()
    unique = [path for path in expanded if not (path in seen or seen.add(path))]
    return unique, skipped


def read_dataset(path: str | Path, *, stop_before_pixels: bool = False, force: bool = False) -> Dataset:
    resolved = Path(path).resolve()
    try:
        dataset = pydicom.dcmread(resolved, stop_before_pixels=stop_before_pixels, force=force)
    except Exception as exc:
        raise DicomReadError(
            f"Unable to parse DICOM file: {resolved}",
            details={"path": str(resolved), "error": type(exc).__name__},
        ) from exc
    sop_class_uid = str(dataset.get("SOPClassUID", "") or getattr(dataset.file_meta, "MediaStorageSOPClassUID", ""))
    if not sop_class_uid:
        raise DicomReadError(
            f"Dataset has no SOP Class UID: {resolved}",
            details={"path": str(resolved)},
        )
    if not getattr(dataset, "file_meta", None):
        dataset.file_meta = FileMetaDataset()
    if not getattr(dataset.file_meta, "TransferSyntaxUID", None) and force:
        implicit_vr, little_endian = dataset.original_encoding[:2]
        if little_endian is False:
            transfer_syntax = ExplicitVRBigEndian
        elif implicit_vr is False:
            transfer_syntax = ExplicitVRLittleEndian
        else:
            transfer_syntax = ImplicitVRLittleEndian
        dataset.file_meta.TransferSyntaxUID = transfer_syntax
        dataset._dicom_inferred_transfer_syntax = True
    return dataset


def _transfer_syntax(dataset: Dataset) -> str:
    return str(getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", "") or "")


def _is_compressed(transfer_syntax_uid: str) -> bool:
    if not transfer_syntax_uid:
        return False
    try:
        return bool(UID(transfer_syntax_uid).is_compressed)
    except ValueError:
        return False


def _iter_elements(dataset: Dataset) -> Iterable[Any]:
    for element in dataset:
        yield element
        if element.VR == "SQ":
            for item in element.value or []:
                yield from _iter_elements(item)


def _has_overlay(dataset: Dataset) -> bool:
    return any(0x6000 <= element.tag.group <= 0x60FF for element in _iter_elements(dataset))


def _header_risks(dataset: Dataset, path: Path) -> list[DICOMRisk]:
    study_uid = str(dataset.get("StudyInstanceUID", "")) or None
    series_uid = str(dataset.get("SeriesInstanceUID", "")) or None
    sop_uid = str(dataset.get("SOPInstanceUID", "")) or None
    base = {
        "path": str(path),
        "study_instance_uid": study_uid,
        "series_instance_uid": series_uid,
        "sop_instance_uid": sop_uid,
    }
    risks: list[DICOMRisk] = []
    if getattr(dataset, "_dicom_inferred_transfer_syntax", False):
        risks.append(
            DICOMRisk(
                code="TRANSFER_SYNTAX_INFERRED",
                severity=DICOMRiskSeverity.WARNING,
                message="Transfer Syntax was inferred during controlled force-read",
                details={"transfer_syntax_uid": _transfer_syntax(dataset)},
                **base,
            )
        )
    present_identifiers = sorted(
        element.keyword
        for element in _iter_elements(dataset)
        if element.keyword in _DIRECT_IDENTIFIER_KEYWORDS and str(element.value or "").strip()
    )
    if present_identifiers:
        risks.append(
            DICOMRisk(
                code="IDENTIFYING_ATTRIBUTES_PRESENT",
                severity=DICOMRiskSeverity.INFO,
                message="Identifying DICOM attributes require policy processing",
                details={"keywords": present_identifiers},
                **base,
            )
        )
    private_count = sum(1 for element in _iter_elements(dataset) if element.tag.is_private)
    if private_count:
        risks.append(
            DICOMRisk(
                code="PRIVATE_TAGS_PRESENT",
                severity=DICOMRiskSeverity.WARNING,
                message="Private DICOM attributes require removal or an approved safe list",
                details={"count": private_count},
                **base,
            )
        )
    if _has_overlay(dataset):
        risks.append(
            DICOMRisk(
                code="OVERLAY_PRESENT",
                severity=DICOMRiskSeverity.WARNING,
                message="Overlay/graphics attributes may contain identifying content",
                **base,
            )
        )
    burned_in = str(dataset.get("BurnedInAnnotation", "")).upper().strip()
    if burned_in == "YES":
        risks.append(
            DICOMRisk(
                code="BURNED_IN_ANNOTATION_DECLARED",
                severity=DICOMRiskSeverity.HIGH,
                message="The object declares burned-in annotation in Pixel Data",
                **base,
            )
        )
    elif "Rows" in dataset and "Columns" in dataset and burned_in != "NO":
        risks.append(
            DICOMRisk(
                code="BURNED_IN_ANNOTATION_UNKNOWN",
                severity=DICOMRiskSeverity.HIGH,
                message="Burned-in annotation status is missing or unknown",
                **base,
            )
        )
    if str(dataset.get("RecognizableVisualFeatures", "")).upper().strip() == "YES":
        risks.append(
            DICOMRisk(
                code="RECOGNIZABLE_VISUAL_FEATURES",
                severity=DICOMRiskSeverity.HIGH,
                message="Pixel Data may contain recognizable visual features",
                **base,
            )
        )
    return risks


def inspect_paths(sources: Iterable[str | Path], *, recursive: bool = True, force: bool = False) -> DICOMInspection:
    paths, skipped = discover_dicom_paths(sources, recursive=recursive)
    instances: list[DICOMInstanceIndex] = []
    risks: list[DICOMRisk] = []

    for path in paths:
        try:
            dataset = read_dataset(path, stop_before_pixels=True, force=force)
            sop_class_uid = str(dataset.get("SOPClassUID", "") or dataset.file_meta.get("MediaStorageSOPClassUID", ""))
            if sop_class_uid == str(MediaStorageDirectoryStorage):
                continue
            study_uid = str(dataset.get("StudyInstanceUID", ""))
            series_uid = str(dataset.get("SeriesInstanceUID", ""))
            sop_uid = str(dataset.get("SOPInstanceUID", ""))
            missing = [
                name
                for name, value in {
                    "StudyInstanceUID": study_uid,
                    "SeriesInstanceUID": series_uid,
                    "SOPInstanceUID": sop_uid,
                }.items()
                if not value
            ]
            if missing:
                skipped.append({"path": str(path), "reason": "missing:" + ",".join(missing)})
                risks.append(
                    DICOMRisk(
                        code="MISSING_HIERARCHY_UID",
                        severity=DICOMRiskSeverity.BLOCKING,
                        message="Image instance lacks required hierarchy identifiers",
                        path=str(path),
                        details={"missing": missing},
                    )
                )
                continue
            transfer_syntax_uid = _transfer_syntax(dataset)
            item_risks = _header_risks(dataset, path)
            risks.extend(item_risks)
            instances.append(
                DICOMInstanceIndex(
                    path=str(path),
                    study_instance_uid=study_uid,
                    series_instance_uid=series_uid,
                    sop_instance_uid=sop_uid,
                    sop_class_uid=sop_class_uid,
                    modality=str(dataset.get("Modality", "")),
                    transfer_syntax_uid=transfer_syntax_uid,
                    number_of_frames=max(1, int(dataset.get("NumberOfFrames", 1) or 1)),
                    rows=int(dataset.Rows) if "Rows" in dataset else None,
                    columns=int(dataset.Columns) if "Columns" in dataset else None,
                    # stop_before_pixels intentionally avoids loading a potentially
                    # huge payload; image module attributes establish that Pixel
                    # Data is expected and preflight verifies its actual presence.
                    has_pixel_data="Rows" in dataset and "Columns" in dataset,
                    is_compressed=_is_compressed(transfer_syntax_uid),
                    patient_reference=patient_reference(dataset),
                    source_sha256=sha256_file(path),
                    metadata_summary={
                        "tag_count": sum(1 for _ in _iter_elements(dataset)),
                        "sequence_count": sum(1 for element in _iter_elements(dataset) if element.VR == "SQ"),
                        "private_tag_count": sum(1 for element in _iter_elements(dataset) if element.tag.is_private),
                    },
                    risks=item_risks,
                )
            )
        except DicomReadError as exc:
            skipped.append({"path": str(path), "reason": str(exc)})

    for item in skipped:
        risks.append(
            DICOMRisk(
                code="INPUT_NOT_PROCESSED",
                severity=DICOMRiskSeverity.BLOCKING,
                message="An input path could not be processed as a DICOM instance",
                path=item.get("path"),
                details={"reason": item.get("reason", "unknown")},
            )
        )

    by_sop: dict[str, list[DICOMInstanceIndex]] = defaultdict(list)
    for instance in instances:
        by_sop[instance.sop_instance_uid].append(instance)
    for sop_uid, duplicates in by_sop.items():
        if len(duplicates) > 1:
            risks.append(
                DICOMRisk(
                    code="DUPLICATE_SOP_INSTANCE_UID",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="Multiple source files share one SOP Instance UID",
                    sop_instance_uid=sop_uid,
                    details={"paths": [item.path for item in duplicates]},
                )
            )

    studies: list[DICOMStudyIndex] = []
    by_study: dict[str, list[DICOMInstanceIndex]] = defaultdict(list)
    for instance in instances:
        by_study[instance.study_instance_uid].append(instance)
    for study_uid, study_instances in sorted(by_study.items()):
        patient_refs = sorted({item.patient_reference for item in study_instances})
        if len(patient_refs) > 1:
            risks.append(
                DICOMRisk(
                    code="INCONSISTENT_PATIENT_WITHIN_STUDY",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="Instances in one Study UID contain inconsistent patient identifiers",
                    study_instance_uid=study_uid,
                    details={"patient_references": patient_refs},
                )
            )
        by_series: dict[str, list[DICOMInstanceIndex]] = defaultdict(list)
        for instance in study_instances:
            by_series[instance.series_instance_uid].append(instance)
        series_models: list[DICOMSeriesIndex] = []
        study_date = ""
        study_description = ""
        for series_uid, series_instances in sorted(by_series.items()):
            first_ds = read_dataset(series_instances[0].path, stop_before_pixels=True, force=force)
            study_date = study_date or str(first_ds.get("StudyDate", ""))
            study_description = study_description or str(first_ds.get("StudyDescription", ""))
            series_models.append(
                DICOMSeriesIndex(
                    series_instance_uid=series_uid,
                    study_instance_uid=study_uid,
                    modality=series_instances[0].modality,
                    series_number=str(first_ds.get("SeriesNumber", "")),
                    description=str(first_ds.get("SeriesDescription", "")),
                    instances=sorted(series_instances, key=lambda item: item.sop_instance_uid),
                )
            )
        studies.append(
            DICOMStudyIndex(
                study_instance_uid=study_uid,
                patient_reference=patient_refs[0] if patient_refs else "",
                study_date=study_date,
                description=study_description,
                modalities=sorted({item.modality for item in study_instances if item.modality}),
                series=series_models,
            )
        )

    status = "ready" if not any(risk.severity == DICOMRiskSeverity.BLOCKING for risk in risks) else "blocked"
    return DICOMInspection(
        status=status,
        sources_scanned=len(paths),
        dicom_count=len(instances),
        skipped=skipped,
        studies=studies,
        instances=instances,
        risks=risks,
    )


__all__ = [
    "discover_dicom_paths",
    "inspect_paths",
    "patient_reference",
    "patient_source_key",
    "read_dataset",
    "sha256_file",
]
