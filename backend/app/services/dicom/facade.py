"""Stable JSON-compatible adapter used by jobs and HTTP layers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .diff import diff_dicom_tags
from .ocr_detector import get_dicom_ocr_pixel_detector
from .policy import build_policy, summarize_policy_actions
from .processor import _run_preflight, anonymize_paths, normalise_core_options, normalise_profile
from .reader import inspect_paths, read_dataset
from .render import render_instance_preview
from .validation import validate_output_paths


def inspect_dicom_paths(
    paths: list[str],
    profile: str = "basic",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = normalise_core_options(options)
    resolved_profile = normalise_profile(profile)
    policy = build_policy(resolved_profile, options)
    inspection = inspect_paths(
        paths,
        recursive=bool(options.get("recursive", True)),
        force=bool(options.get("force_dicom_read", False)),
    )
    for instance in inspection.instances:
        dataset = read_dataset(
            instance.path,
            stop_before_pixels=True,
            force=bool(options.get("force_dicom_read", False)),
        )
        instance.metadata_summary.update(summarize_policy_actions(dataset, policy))
    payload = inspection.model_dump(mode="json")
    payload["profile"] = profile
    payload["resolved_profile"] = resolved_profile
    return payload


def preflight_study(
    paths: list[str],
    profile: str = "basic",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = normalise_core_options(options)
    detector = get_dicom_ocr_pixel_detector() if options.get("pixel_ocr_required") else None
    preflight, assessments, _ = _run_preflight(
        paths,
        profile=profile,
        options=options,
        detector=detector,
    )
    payload = preflight.model_dump(mode="json")
    payload["pixel_statuses"] = {
        path: {
            "status": assessment.status.value,
            "decoded": assessment.decoded,
            "frame_count": assessment.frame_count,
            "detector": assessment.detector_result.detector_name if assessment.detector_result else None,
            "detector_findings": len(assessment.detector_result.regions) if assessment.detector_result else 0,
        }
        for path, assessment in assessments.items()
    }
    return payload


def anonymize_study(
    instance_paths: list[str],
    output_dir: str,
    profile: str = "basic",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = normalise_core_options(options)
    detector = get_dicom_ocr_pixel_detector() if options.get("pixel_ocr_required") else None
    report = anonymize_paths(
        instance_paths,
        output_dir,
        profile=profile,
        options=options,
        detector=detector,
    )
    return report.model_dump(mode="json")


def validate_dicom_outputs(
    paths: list[str],
    profile: str = "basic",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = build_policy(normalise_profile(profile), normalise_core_options(options))
    report = validate_output_paths([Path(path) for path in paths], policy=policy)
    return report.model_dump(mode="json")


__all__ = [
    "anonymize_study",
    "diff_dicom_tags",
    "inspect_dicom_paths",
    "preflight_study",
    "render_instance_preview",
    "validate_dicom_outputs",
]
