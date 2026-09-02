"""Explicit failure modes for the DICOM core."""

from __future__ import annotations

from typing import Any


class DicomError(RuntimeError):
    code = "dicom_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class DicomConfigurationError(DicomError):
    code = "dicom_configuration_error"


class DicomReadError(DicomError):
    code = "dicom_read_error"


class DicomPixelDecodeError(DicomError):
    code = "dicom_pixel_decode_error"


class DicomUnsafeOperationError(DicomError):
    code = "dicom_unsafe_operation"


class DicomValidationError(DicomError):
    code = "dicom_validation_error"


__all__ = [
    "DicomConfigurationError",
    "DicomError",
    "DicomPixelDecodeError",
    "DicomReadError",
    "DicomUnsafeOperationError",
    "DicomValidationError",
]
