"""DICOM Study/Series/Instance de-identification core."""

from .diff import diff_dicom_tags
from .errors import (
    DicomConfigurationError,
    DicomError,
    DicomPixelDecodeError,
    DicomReadError,
    DicomUnsafeOperationError,
    DicomValidationError,
)
from .facade import (
    anonymize_study,
    inspect_dicom_paths,
    preflight_study,
    render_instance_preview,
    validate_dicom_outputs,
)
from .mapping import StableDICOMMapper
from .pixel import BurnedInPixelDetector, PixelDetectorResult, PixelRegion
from .policy import DICOMPolicyEngine, build_policy
from .processor import anonymize_paths, preflight_paths
from .reader import inspect_paths

__all__ = [
    "BurnedInPixelDetector",
    "DICOMPolicyEngine",
    "DicomConfigurationError",
    "DicomError",
    "DicomPixelDecodeError",
    "DicomReadError",
    "DicomUnsafeOperationError",
    "DicomValidationError",
    "PixelDetectorResult",
    "PixelRegion",
    "StableDICOMMapper",
    "anonymize_paths",
    "anonymize_study",
    "build_policy",
    "diff_dicom_tags",
    "inspect_dicom_paths",
    "inspect_paths",
    "preflight_paths",
    "preflight_study",
    "render_instance_preview",
    "validate_dicom_outputs",
]
