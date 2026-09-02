"""Preflight and transactional DICOM de-identification orchestration."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from app.models.dicom_schemas import (
    DICOMDeidentificationReport,
    DICOMInstanceResult,
    DICOMPixelStatus,
    DICOMPolicy,
    DICOMPreflight,
    DICOMRisk,
    DICOMRiskSeverity,
    DICOMTagAction,
    DICOMTagChange,
)

from .errors import DicomConfigurationError, DicomUnsafeOperationError, DicomValidationError
from .mapping import StableDICOMMapper
from .pixel import (
    BurnedInPixelDetector,
    PixelAssessment,
    assess_pixel_data,
    decoded_frames,
    redact_pixel_regions,
    remove_overlays,
)
from .policy import DICOMPolicyEngine, build_policy
from .reader import inspect_paths, patient_source_key, read_dataset, sha256_file
from .validation import ExpectedOutput, pixel_data_sha256, validate_output_paths

_SENSITIVE_VALUE_KEYWORDS = {
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

_PROFILE_ALIASES = {
    "basic": "basic",
    "research": "research",
    "research_strict": "strict",
    "strict": "strict",
    "longitudinal": "longitudinal",
    "longitudinal_research": "longitudinal",
    "internal_pseudonymized": "longitudinal",
    "ai_training": "strict",
}


def normalise_profile(profile: str) -> str:
    value = str(profile or "basic").strip().lower()
    try:
        return _PROFILE_ALIASES[value]
    except KeyError as exc:
        raise ValueError(f"Unsupported DICOM profile: {profile}") from exc


def normalise_core_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """Translate the public API option vocabulary to core policy fields.

    Unsafe or unimplemented relaxations fail explicitly instead of being
    silently ignored by the Pydantic policy model.
    """

    source = dict(options or {})
    output = dict(source)
    aliases = {
        "clean_graphics": "clean_overlays",
        "clean_pixel_data": "clean_pixel_data",
        "clean_structured_content": "clean_structured_content",
        "clean_descriptors": "clean_descriptors",
        "clean_recognizable_visual_features": "clean_recognizable_visual_features",
    }
    for public_name, core_name in aliases.items():
        if public_name in source and source[public_name] is not None:
            output[core_name] = source[public_name]

    if source.get("retain_longitudinal_temporal_info") is not None and "date_mode" not in source:
        output["date_mode"] = "shift" if source["retain_longitudinal_temporal_info"] else "remove"
    if source.get("date_mode") is not None:
        output["date_mode"] = source["date_mode"]
    if "date_mode" in output:
        output["retain_longitudinal_dates"] = output["date_mode"] != "remove"

    if source.get("uid_mode") is not None:
        output["retain_uids"] = source["uid_mode"] == "retain"
    if source.get("private_tag_policy") is not None:
        output["remove_private_tags"] = True
    if source.get("retain_safe_private"):
        if not source.get("safe_private_tags"):
            raise DicomConfigurationError(
                "retain_safe_private requires an explicit, reviewed safe_private_tags allow-list"
            )
        output["remove_private_tags"] = True
    if source.get("fail_on_pixel_decode_error") is False:
        raise DicomConfigurationError("DICOM Pixel Data decode failures cannot be configured to fail open")
    output["require_decodable_pixel_data"] = True
    if source.get("reversible_pseudonymization"):
        raise DicomConfigurationError("Reversible DICOM pseudonymization requires a configured encrypted mapping vault")
    return output


def _risk_key(risk: DICOMRisk) -> tuple[Any, ...]:
    return risk.code, risk.path, risk.study_instance_uid, risk.series_instance_uid, risk.sop_instance_uid


def _deduplicate_risks(risks: Iterable[DICOMRisk]) -> list[DICOMRisk]:
    output: list[DICOMRisk] = []
    seen: set[tuple[Any, ...]] = set()
    for risk in risks:
        key = _risk_key(risk)
        if key not in seen:
            output.append(risk)
            seen.add(key)
    return output


def _decision_for(options: dict[str, Any], dataset: Dataset, path: str) -> str | None:
    decisions = options.get("pixel_review_decisions") or {}
    if not isinstance(decisions, dict):
        return None
    sop_uid = str(dataset.get("SOPInstanceUID", ""))
    return decisions.get(sop_uid) or decisions.get(path) or decisions.get(str(Path(path).resolve()))


def _run_preflight(
    sources: Iterable[str | Path],
    *,
    profile: str,
    options: dict[str, Any] | None,
    detector: BurnedInPixelDetector | None = None,
) -> tuple[DICOMPreflight, dict[str, PixelAssessment], DICOMPolicy]:
    options = normalise_core_options(options)
    resolved_profile = normalise_profile(profile)
    policy = build_policy(resolved_profile, options)
    inspection = inspect_paths(
        sources,
        recursive=bool(options.get("recursive", True)),
        force=bool(options.get("force_dicom_read", False)),
    )
    all_risks = list(inspection.risks)
    assessments: dict[str, PixelAssessment] = {}
    for instance in inspection.instances:
        dataset = read_dataset(
            instance.path,
            stop_before_pixels=False,
            force=bool(options.get("force_dicom_read", False)),
        )
        assessment = assess_pixel_data(
            dataset,
            source_path=instance.path,
            supported_modalities={value.upper() for value in policy.supported_modalities},
            clean_overlays=policy.clean_overlays,
            require_decodable=policy.require_decodable_pixel_data,
            detector=detector,
            review_decision=_decision_for(options, dataset, instance.path),
            require_detector=bool(options.get("pixel_ocr_required", False)),
            redact_detector_findings=policy.clean_pixel_data,
        )
        assessments[instance.path] = assessment
        all_risks.extend(assessment.risks)

        detector_regions = assessment.detector_result.regions if assessment.detector_result else []
        if policy.clean_pixel_data and detector_regions:
            # Header inspection runs before the detector.  Once there is a
            # concrete, automatically redacted region plan, the burned-in
            # header warning is no longer an unresolved manual-review gate.
            # RecognizableVisualFeatures remains HIGH: text-box redaction is
            # not a defacing implementation.
            seen_risks: set[int] = set()
            for risk in [*inspection.risks, *instance.risks]:
                if id(risk) in seen_risks:
                    continue
                seen_risks.add(id(risk))
                if risk.code not in {"BURNED_IN_ANNOTATION_DECLARED", "BURNED_IN_ANNOTATION_UNKNOWN"}:
                    continue
                if risk.sop_instance_uid and risk.sop_instance_uid != instance.sop_instance_uid:
                    continue
                if risk.path and risk.path != instance.path:
                    continue
                risk.severity = DICOMRiskSeverity.WARNING
                risk.message = "Burned-in annotation will be removed by automatic pixel redaction"
                risk.details = {
                    **risk.details,
                    "auto_redaction_planned": True,
                    "region_count": len(detector_regions),
                }

    all_risks = _deduplicate_risks(all_risks)
    blocking = [risk for risk in all_risks if risk.severity == DICOMRiskSeverity.BLOCKING]
    review = [risk for risk in all_risks if risk.severity == DICOMRiskSeverity.HIGH]
    unresolved_review = any(item.status == DICOMPixelStatus.REVIEW_REQUIRED for item in assessments.values())
    can_execute = bool(inspection.instances) and not blocking and not unresolved_review
    if blocking:
        status = "blocked"
    elif unresolved_review:
        status = "review_required"
    elif not inspection.instances:
        status = "blocked"
    else:
        status = "ready"
    return (
        DICOMPreflight(
            status=status,
            can_execute=can_execute,
            profile=profile,
            inspection=inspection,
            risks=all_risks,
            blocking_risks=blocking,
            review_required=review,
        ),
        assessments,
        policy,
    )


def preflight_paths(
    sources: Iterable[str | Path],
    *,
    profile: str = "basic",
    options: dict[str, Any] | None = None,
    detector: BurnedInPixelDetector | None = None,
) -> DICOMPreflight:
    preflight, _, _ = _run_preflight(sources, profile=profile, options=options, detector=detector)
    return preflight


def _resolve_mapping_secret(options: dict[str, Any]) -> bytes | str:
    explicit = options.get("mapping_secret")
    if explicit:
        return explicit
    environment = os.environ.get("DICOM_PSEUDONYM_SECRET", "").strip()
    if environment:
        return environment
    # The application already persists this secret across restarts.  HMAC
    # domain separation in StableDICOMMapper prevents token reuse with JWTs.
    try:
        from app.core.config import get_settings

        fallback = get_settings().JWT_SECRET_KEY
    except Exception as exc:  # pragma: no cover - exercised in stripped deployments
        raise DicomConfigurationError(
            "Set DICOM_PSEUDONYM_SECRET or pass mapping_secret before de-identification"
        ) from exc
    if not fallback:
        raise DicomConfigurationError("No stable DICOM pseudonym secret is configured")
    return fallback


def _iter_elements(dataset: Dataset) -> Iterable[Any]:
    for element in dataset:
        yield element
        if element.VR == "SQ":
            for item in element.value or []:
                yield from _iter_elements(item)


def _sensitive_values(dataset: Dataset, *, policy: DICOMPolicy) -> set[str]:
    output: set[str] = set()
    for element in _iter_elements(dataset):
        if element.keyword not in _SENSITIVE_VALUE_KEYWORDS:
            continue
        if policy.date_mode == "retain" and element.VR in {"DA", "DT"}:
            continue
        value = element.value
        values = [value] if isinstance(value, str | int | float) else list(value or [])
        for item in values:
            text = str(item).strip()
            if len(text) >= 3:
                output.add(text)
    return output


def _code_item(code_value: str, meaning: str) -> Dataset:
    item = Dataset()
    item.CodeValue = code_value
    item.CodingSchemeDesignator = "DCM"
    item.CodeMeaning = meaning
    return item


def _set_deidentification_method(
    dataset: Dataset,
    *,
    policy: DICOMPolicy,
    overlays_removed: int,
    pixel_status: DICOMPixelStatus,
    pixel_regions_redacted: int = 0,
) -> None:
    methods = ["PS3.15 Basic Application Confidentiality Profile"]
    codes = [_code_item("113100", "Basic Application Confidentiality Profile")]
    if policy.date_mode == "shift":
        methods.append("longitudinal dates modified")
        codes.append(_code_item("113107", "Retain Longitudinal Temporal Information Modified Dates Option"))
        dataset.LongitudinalTemporalInformationModified = "MODIFIED"
    elif policy.date_mode == "retain":
        methods.append("longitudinal dates retained")
        codes.append(_code_item("113106", "Retain Longitudinal Temporal Information Full Dates Option"))
        dataset.LongitudinalTemporalInformationModified = "UNMODIFIED"
    else:
        dataset.LongitudinalTemporalInformationModified = "REMOVED"
    if overlays_removed:
        methods.append("graphics cleaned")
        codes.append(_code_item("113103", "Clean Graphics Option"))
    if pixel_status == DICOMPixelStatus.EXTERNALLY_REDACTED:
        methods.append(
            "pixel data automatically cleaned" if pixel_regions_redacted else "pixel data externally cleaned"
        )
        codes.append(_code_item("113101", "Clean Pixel Data Option"))
        dataset.BurnedInAnnotation = "NO"
    elif pixel_status == DICOMPixelStatus.VERIFIED_CLEAR:
        methods.append("pixel data manually verified clear")
        dataset.BurnedInAnnotation = "NO"
    elif policy.clean_pixel_data and pixel_status == DICOMPixelStatus.CLEAR:
        codes.append(_code_item("113101", "Clean Pixel Data Option"))
    if policy.clean_recognizable_visual_features and (
        pixel_status == DICOMPixelStatus.VERIFIED_CLEAR
        or (pixel_status == DICOMPixelStatus.EXTERNALLY_REDACTED and not pixel_regions_redacted)
    ):
        codes.append(_code_item("113102", "Clean Recognizable Visual Features Option"))
    if policy.retain_patient_characteristics:
        codes.append(_code_item("113108", "Retain Patient Characteristics Option"))
    if policy.retain_device_identity:
        codes.append(_code_item("113109", "Retain Device Identity Option"))
    if policy.retain_uids:
        codes.append(_code_item("113110", "Retain UIDs Option"))
    if policy.safe_private_tags:
        codes.append(_code_item("113111", "Retain Safe Private Option"))
    if policy.retain_institution_identity:
        codes.append(_code_item("113112", "Retain Institution Identity Option"))
    dataset.PatientIdentityRemoved = "YES"
    # LO is limited to 64 characters; keep the textual method concise while
    # retaining full coded detail in (0012,0064).
    dataset.DeidentificationMethod = "; ".join(methods)[:64]
    dataset.DeidentificationMethodCodeSequence = Sequence(codes)


def _clean_file_meta(dataset: Dataset, *, policy: DICOMPolicy) -> int:
    changes = 0
    if policy.clean_preamble:
        if dataset.preamble != b"\x00" * 128:
            changes += 1
        dataset.preamble = b"\x00" * 128
    if not hasattr(dataset, "file_meta"):
        return changes
    if policy.clean_file_meta:
        for element in list(dataset.file_meta):
            if element.tag.is_private or element.keyword == "SourceApplicationEntityTitle":
                del dataset.file_meta[element.tag]
                changes += 1
    if "SOPClassUID" in dataset:
        dataset.file_meta.MediaStorageSOPClassUID = dataset.SOPClassUID
    if "SOPInstanceUID" in dataset:
        dataset.file_meta.MediaStorageSOPInstanceUID = dataset.SOPInstanceUID
    return changes


def _pixel_redaction_padding(options: dict[str, Any]) -> int:
    value = options.get("pixel_redaction_padding", 2)
    if isinstance(value, bool):
        raise DicomConfigurationError("pixel_redaction_padding must be an integer between 0 and 512")
    try:
        padding = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DicomConfigurationError("pixel_redaction_padding must be an integer between 0 and 512") from exc
    if padding != value or not 0 <= padding <= 512:
        raise DicomConfigurationError("pixel_redaction_padding must be an integer between 0 and 512")
    return padding


def _output_relative_path(dataset: Dataset) -> Path:
    return Path(str(dataset.StudyInstanceUID)) / str(dataset.SeriesInstanceUID) / f"{dataset.SOPInstanceUID}.dcm"


def anonymize_paths(
    sources: Iterable[str | Path],
    output_dir: str | Path,
    *,
    profile: str = "basic",
    options: dict[str, Any] | None = None,
    detector: BurnedInPixelDetector | None = None,
) -> DICOMDeidentificationReport:
    """De-identify inputs transactionally, leaving every source byte untouched."""

    started_at = datetime.now(UTC).isoformat()
    options = normalise_core_options(options)
    preflight, assessments, policy = _run_preflight(
        sources,
        profile=profile,
        options=options,
        detector=detector,
    )
    if not preflight.can_execute:
        raise DicomUnsafeOperationError(
            "DICOM preflight has unresolved blocking or pixel-review risks",
            details={"preflight": preflight.model_dump(mode="json")},
        )

    mapper = StableDICOMMapper(
        secret=_resolve_mapping_secret(options),
        namespace=str(options.get("mapping_namespace") or options.get("tenant_id") or "default"),
        date_shift_range_days=policy.date_shift_range_days,
    )
    engine = DICOMPolicyEngine(policy, mapper)
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=".dicom-stage-", dir=output_root))
    overwrite = bool(options.get("overwrite", False))
    if overwrite:
        # Replacing a pre-existing clinical export cannot be rolled back safely
        # without a durable backup/restore transaction.  Keep this core
        # fail-closed until such a store is configured.
        shutil.rmtree(stage_root, ignore_errors=True)
        raise DicomConfigurationError("overwrite=True is not supported for transactional DICOM publication")
    staged_pairs: list[tuple[Path, Path]] = []
    expected: dict[str, ExpectedOutput] = {}
    result_contexts: list[dict[str, Any]] = []
    aggregate_actions: Counter[str] = Counter()
    redaction_padding = _pixel_redaction_padding(options)

    try:
        for instance in preflight.inspection.instances:
            source = Path(instance.path).resolve()
            source_hash_before = sha256_file(source)
            if source_hash_before != instance.source_sha256:
                raise DicomUnsafeOperationError(
                    "A DICOM source changed after inspection",
                    details={"path": str(source)},
                )
            dataset = read_dataset(source, stop_before_pixels=False, force=bool(options.get("force_dicom_read", False)))
            original_study_uid = str(dataset.StudyInstanceUID)
            original_series_uid = str(dataset.SeriesInstanceUID)
            original_sop_uid = str(dataset.SOPInstanceUID)
            original_sensitive = _sensitive_values(dataset, policy=policy)
            original_pixel_hash = pixel_data_sha256(dataset)
            source_frames = decoded_frames(dataset, source_path=source)
            original_frame_shapes = tuple(tuple(int(dimension) for dimension in frame.shape) for frame in source_frames)
            patient_key = patient_source_key(dataset)

            application = engine.apply(dataset, patient_key=patient_key)
            assessment = assessments[instance.path]
            overlays_removed = remove_overlays(dataset) if policy.clean_overlays else 0
            detector_regions = assessment.detector_result.regions if assessment.detector_result else []
            pixel_regions_redacted = 0
            pixel_status = assessment.status
            if policy.clean_pixel_data and detector_regions:
                pixel_regions_redacted = redact_pixel_regions(
                    dataset,
                    detector_regions,
                    padding=redaction_padding,
                    source_path=source,
                )
                pixel_status = DICOMPixelStatus.EXTERNALLY_REDACTED
                application.changes.append(
                    DICOMTagChange(
                        path="PixelData",
                        tag="7FE0,0010",
                        keyword="PixelData",
                        vr=str(dataset["PixelData"].VR),
                        action=DICOMTagAction.CLEAN,
                        reason="Automatic detector-guided Clean Pixel Data Option",
                    )
                )
                application.action_counts[DICOMTagAction.CLEAN.value] = (
                    application.action_counts.get(DICOMTagAction.CLEAN.value, 0) + pixel_regions_redacted
                )
            _set_deidentification_method(
                dataset,
                policy=policy,
                overlays_removed=overlays_removed,
                pixel_status=pixel_status,
                pixel_regions_redacted=pixel_regions_redacted,
            )
            file_meta_changes = _clean_file_meta(dataset, policy=policy)
            if overlays_removed:
                application.changes.append(
                    DICOMTagChange(
                        path="60xx overlays",
                        tag="60XX,XXXX",
                        keyword="Overlay",
                        vr="",
                        action=DICOMTagAction.REMOVE,
                        reason="Clean Graphics Option",
                    )
                )
                application.action_counts[DICOMTagAction.REMOVE.value] = (
                    application.action_counts.get(DICOMTagAction.REMOVE.value, 0) + overlays_removed
                )
            if file_meta_changes:
                application.action_counts[DICOMTagAction.CLEAN.value] = (
                    application.action_counts.get(DICOMTagAction.CLEAN.value, 0) + file_meta_changes
                )

            relative = _output_relative_path(dataset)
            staged = (stage_root / relative).resolve()
            final = (output_root / relative).resolve()
            try:
                final.relative_to(output_root)
                staged.relative_to(stage_root)
            except ValueError as exc:  # defensive: UIDs should only contain digits/dots
                raise DicomUnsafeOperationError("Mapped UID produced an unsafe output path") from exc
            if final == source:
                raise DicomUnsafeOperationError("Output path would overwrite the source", details={"path": str(source)})
            if final.exists() and not overwrite:
                raise DicomUnsafeOperationError(
                    "DICOM output already exists; overwrite was not requested",
                    details={"path": str(final)},
                )
            staged.parent.mkdir(parents=True, exist_ok=True)
            dataset.save_as(staged, enforce_file_format=True)

            expected[str(staged)] = ExpectedOutput(
                study_instance_uid=str(dataset.StudyInstanceUID),
                series_instance_uid=str(dataset.SeriesInstanceUID),
                sop_instance_uid=str(dataset.SOPInstanceUID),
                pixel_sha256=original_pixel_hash,
                pixel_modified=bool(pixel_regions_redacted),
                pixel_frame_shapes=original_frame_shapes,
                frame_count=len(source_frames),
                redacted_region_count=pixel_regions_redacted,
                original_sensitive_values=original_sensitive,
            )
            staged_pairs.append((staged, final))
            result_contexts.append(
                {
                    "source": source,
                    "staged": staged,
                    "final": final,
                    "source_hash": source_hash_before,
                    "original_study_uid": original_study_uid,
                    "original_series_uid": original_series_uid,
                    "original_sop_uid": original_sop_uid,
                    "study_uid": str(dataset.StudyInstanceUID),
                    "series_uid": str(dataset.SeriesInstanceUID),
                    "sop_uid": str(dataset.SOPInstanceUID),
                    "pixel_status": pixel_status,
                    "changes": application.changes,
                    "overlays_removed": overlays_removed,
                    "pixel_regions_redacted": pixel_regions_redacted,
                }
            )
            aggregate_actions.update(application.action_counts)

        validation = validate_output_paths(
            [staged for staged, _ in staged_pairs],
            policy=policy,
            expected=expected,
            original_uid_mapping=mapper.uid_mapping,
        )
        if not validation.ok:
            raise DicomValidationError(
                "DICOM output validation failed; no output was published",
                details={"validation": validation.model_dump(mode="json")},
            )

        # Recheck all inputs immediately before publication to uphold the
        # read-only/concurrent-modification guarantee.
        for context in result_contexts:
            if sha256_file(context["source"]) != context["source_hash"]:
                raise DicomUnsafeOperationError(
                    "A DICOM source changed during processing",
                    details={"path": str(context["source"])},
                )

        published: list[Path] = []
        try:
            for staged, final in staged_pairs:
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, final)
                published.append(final)
        except Exception as exc:
            rollback_failures: list[str] = []
            for published_path in reversed(published):
                try:
                    published_path.unlink(missing_ok=True)
                except OSError:
                    rollback_failures.append(str(published_path))
            raise DicomUnsafeOperationError(
                "DICOM batch publication failed and was rolled back",
                details={
                    "published_before_failure": len(published),
                    "rollback_failures": rollback_failures,
                    "cause": f"{type(exc).__name__}: {exc}",
                },
            ) from exc

        instance_results: list[DICOMInstanceResult] = []
        for context in result_contexts:
            instance_results.append(
                DICOMInstanceResult(
                    source_path=str(context["source"]),
                    output_path=str(context["final"]),
                    source_sha256=context["source_hash"],
                    output_sha256=sha256_file(context["final"]),
                    original_study_instance_uid=context["original_study_uid"],
                    original_series_instance_uid=context["original_series_uid"],
                    original_sop_instance_uid=context["original_sop_uid"],
                    study_instance_uid=context["study_uid"],
                    series_instance_uid=context["series_uid"],
                    sop_instance_uid=context["sop_uid"],
                    pixel_status=context["pixel_status"],
                    changes=context["changes"],
                    overlays_removed=context["overlays_removed"],
                    pixel_regions_redacted=context["pixel_regions_redacted"],
                    validation_ok=True,
                )
            )

        return DICOMDeidentificationReport(
            status="completed",
            profile=profile,
            started_at=started_at,
            completed_at=datetime.now(UTC).isoformat(),
            output_dir=str(output_root),
            instances=instance_results,
            output_paths=[item.output_path for item in instance_results],
            risks=preflight.risks,
            action_counts=dict(sorted(aggregate_actions.items())),
            validation=validation,
            mapping_namespace=mapper.namespace,
            reversible_mapping_stored=False,
        )
    finally:
        # The staging path is created by this function and never contains source
        # data outside this invocation, so cleanup is safe and bounded.
        shutil.rmtree(stage_root, ignore_errors=True)


__all__ = ["anonymize_paths", "normalise_core_options", "normalise_profile", "preflight_paths"]
