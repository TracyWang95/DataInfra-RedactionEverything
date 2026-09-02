"""Pixel PHI risk assessment and overlay cleaning.

This module does not claim that OCR alone proves anonymity.  Detector findings
may be masked by the Clean Pixel Data policy, while an empty result and
recognizable visual features remain conservative review gates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from pydicom.dataset import Dataset
from pydicom.pixels import set_pixel_data
from pydicom.uid import UID, ExplicitVRLittleEndian

from app.models.dicom_schemas import DICOMPixelStatus, DICOMRisk, DICOMRiskSeverity

from .errors import DicomPixelDecodeError


@dataclass(frozen=True)
class PixelRegion:
    frame_index: int
    x: int
    y: int
    width: int
    height: int
    text: str = ""
    confidence: float | None = None


@dataclass
class PixelDetectorResult:
    regions: list[PixelRegion] = field(default_factory=list)
    detector_name: str = ""
    detector_version: str = ""


class BurnedInPixelDetector(Protocol):
    """Plug-in contract for OCR/vision detectors.

    The core supplies decoded frames but never assumes that an empty detector
    result is by itself proof of anonymity.
    """

    def detect(self, dataset: Dataset, frames: list[np.ndarray]) -> PixelDetectorResult: ...


@dataclass
class PixelAssessment:
    status: DICOMPixelStatus
    risks: list[DICOMRisk] = field(default_factory=list)
    decoded: bool = False
    frame_count: int = 0
    detector_result: PixelDetectorResult | None = None


_APPROVED_DECISIONS = {
    DICOMPixelStatus.VERIFIED_CLEAR.value: DICOMPixelStatus.VERIFIED_CLEAR,
    DICOMPixelStatus.EXTERNALLY_REDACTED.value: DICOMPixelStatus.EXTERNALLY_REDACTED,
}


def decoded_frames(dataset: Dataset, *, source_path: str | Path = "") -> list[np.ndarray]:
    if "PixelData" not in dataset:
        return []
    transfer_syntax = str(getattr(dataset.file_meta, "TransferSyntaxUID", "") or "")
    try:
        pixel_array = np.asarray(dataset.pixel_array)
    except Exception as exc:
        raise DicomPixelDecodeError(
            "Pixel Data cannot be decoded safely",
            details={
                "path": str(source_path),
                "transfer_syntax_uid": transfer_syntax,
                "decoder_error": f"{type(exc).__name__}: {exc}",
            },
        ) from exc

    number_of_frames = max(1, int(dataset.get("NumberOfFrames", 1) or 1))
    samples_per_pixel = max(1, int(dataset.get("SamplesPerPixel", 1) or 1))
    if number_of_frames > 1:
        if pixel_array.ndim < 3 or pixel_array.shape[0] != number_of_frames:
            raise DicomPixelDecodeError(
                "Decoded Pixel Data shape does not match Number of Frames",
                details={
                    "path": str(source_path),
                    "number_of_frames": number_of_frames,
                    "decoded_shape": list(pixel_array.shape),
                },
            )
        return [np.asarray(pixel_array[index]) for index in range(number_of_frames)]
    if samples_per_pixel > 1 and pixel_array.ndim == 3:
        return [pixel_array]
    return [pixel_array]


def _overlay_count(dataset: Dataset) -> int:
    count = 0
    for element in dataset:
        if 0x6000 <= element.tag.group <= 0x60FF:
            count += 1
        if element.VR == "SQ":
            count += sum(_overlay_count(item) for item in element.value or [])
    return count


def remove_overlays(dataset: Dataset) -> int:
    """Remove all repeating 60xx overlay/graphics groups recursively."""

    removed = 0
    for element in list(dataset):
        if 0x6000 <= element.tag.group <= 0x60FF:
            del dataset[element.tag]
            removed += 1
            continue
        if element.VR == "SQ":
            removed += sum(remove_overlays(item) for item in element.value or [])
    return removed


def _normalise_redaction_array(dataset: Dataset, *, source_path: str | Path) -> tuple[np.ndarray, str, int]:
    """Return writable, little-endian pixels plus their output encoding.

    Encapsulated input is deliberately decompressed before mutation.  Pixel
    redaction never attempts to patch compressed fragments in place because a
    partially rewritten codestream could be unreadable while still appearing
    to have succeeded.  YBR input is normalised to interleaved RGB so that the
    bytes written by :func:`set_pixel_data` match the advertised photometric
    interpretation.
    """

    transfer_syntax = str(getattr(dataset.file_meta, "TransferSyntaxUID", "") or "")
    try:
        compressed = bool(transfer_syntax and UID(transfer_syntax).is_compressed)
    except ValueError:
        compressed = False

    try:
        if compressed:
            # `generate_instance_uid=False` is essential: the policy engine has
            # already produced a deterministic SOP UID that must not be replaced.
            dataset.decompress(as_rgb=True, generate_instance_uid=False)
        pixels = np.asarray(dataset.pixel_array)
    except Exception as exc:
        raise DicomPixelDecodeError(
            "Pixel Data cannot be decompressed for safe redaction",
            details={
                "path": str(source_path),
                "transfer_syntax_uid": transfer_syntax,
                "decoder_error": f"{type(exc).__name__}: {exc}",
            },
        ) from exc

    photometric = str(dataset.get("PhotometricInterpretation", "")).upper().strip()
    samples_per_pixel = max(1, int(dataset.get("SamplesPerPixel", 1) or 1))
    if samples_per_pixel == 1:
        if photometric not in {"MONOCHROME1", "MONOCHROME2"}:
            raise DicomPixelDecodeError(
                "The grayscale photometric interpretation is not supported for safe redaction",
                details={"path": str(source_path), "photometric_interpretation": photometric},
            )
        output_photometric = photometric
    elif samples_per_pixel == 3:
        if photometric != "RGB" and not photometric.startswith("YBR"):
            raise DicomPixelDecodeError(
                "The color photometric interpretation is not supported for safe redaction",
                details={"path": str(source_path), "photometric_interpretation": photometric},
            )
        # `Dataset.pixel_array` converts supported YBR encodings to RGB.  Keep
        # metadata and bytes aligned rather than writing RGB bytes as YBR.
        output_photometric = "RGB"
    else:
        raise DicomPixelDecodeError(
            "Only grayscale and three-channel color Pixel Data can be redacted safely",
            details={"path": str(source_path), "samples_per_pixel": samples_per_pixel},
        )

    if pixels.dtype.kind not in {"u", "i"} or pixels.dtype.itemsize not in {1, 2}:
        raise DicomPixelDecodeError(
            "The decoded pixel representation is not supported for safe redaction",
            details={"path": str(source_path), "dtype": str(pixels.dtype)},
        )

    bits_stored = int(dataset.get("BitsStored", pixels.dtype.itemsize * 8) or pixels.dtype.itemsize * 8)
    if bits_stored < 1 or bits_stored > pixels.dtype.itemsize * 8:
        raise DicomPixelDecodeError(
            "Bits Stored is inconsistent with the decoded pixel representation",
            details={
                "path": str(source_path),
                "bits_stored": bits_stored,
                "dtype": str(pixels.dtype),
            },
        )

    # set_pixel_data writes Explicit VR Little Endian.  Convert a big-endian
    # ndarray explicitly so the output bytes cannot be misinterpreted.
    output_dtype = pixels.dtype.newbyteorder("<") if pixels.dtype.itemsize > 1 else pixels.dtype
    writable = np.array(pixels, dtype=output_dtype, copy=True, order="C")
    return writable, output_photometric, bits_stored


def _redaction_fill(array: np.ndarray, *, photometric: str, bits_stored: int) -> int | np.ndarray:
    signed = array.dtype.kind == "i"
    minimum = -(2 ** (bits_stored - 1)) if signed else 0
    maximum = 2 ** (bits_stored - 1) - 1 if signed else 2**bits_stored - 1
    if photometric == "MONOCHROME1":
        # MONOCHROME1 displays the largest stored value as black.
        return maximum
    if photometric == "MONOCHROME2":
        return minimum
    if photometric == "RGB":
        return np.zeros(3, dtype=array.dtype)
    raise DicomPixelDecodeError(
        "No privacy-safe redaction fill is defined for the photometric interpretation",
        details={"photometric_interpretation": photometric},
    )


def redact_pixel_regions(
    dataset: Dataset,
    regions: list[PixelRegion],
    *,
    padding: int = 2,
    source_path: str | Path = "",
) -> int:
    """Black out detector regions and replace Pixel Data with a valid stream.

    Coordinates are detector-space pixel coordinates and are clipped to the
    image boundary after applying the configured padding.  Invalid frames or
    wholly out-of-bounds findings fail closed because silently ignoring a
    detector finding could publish PHI.
    """

    if not regions:
        return 0
    if isinstance(padding, bool) or not isinstance(padding, int) or not 0 <= padding <= 512:
        raise DicomPixelDecodeError(
            "Pixel redaction padding must be an integer between 0 and 512",
            details={"path": str(source_path), "padding": padding},
        )

    array, photometric, bits_stored = _normalise_redaction_array(dataset, source_path=source_path)
    number_of_frames = max(1, int(dataset.get("NumberOfFrames", 1) or 1))
    samples_per_pixel = max(1, int(dataset.get("SamplesPerPixel", 1) or 1))

    if number_of_frames > 1:
        if array.ndim not in ({3} if samples_per_pixel == 1 else {4}) or array.shape[0] != number_of_frames:
            raise DicomPixelDecodeError(
                "Decoded Pixel Data shape does not match the multi-frame image module",
                details={
                    "path": str(source_path),
                    "number_of_frames": number_of_frames,
                    "decoded_shape": list(array.shape),
                },
            )
        frame_arrays = [array[index] for index in range(number_of_frames)]
    else:
        expected_ndim = 2 if samples_per_pixel == 1 else 3
        if array.ndim != expected_ndim:
            raise DicomPixelDecodeError(
                "Decoded Pixel Data shape does not match the single-frame image module",
                details={"path": str(source_path), "decoded_shape": list(array.shape)},
            )
        frame_arrays = [array]

    fill = _redaction_fill(array, photometric=photometric, bits_stored=bits_stored)
    applied = 0
    for region in regions:
        try:
            frame_index = int(region.frame_index)
            x = float(region.x)
            y = float(region.y)
            width = float(region.width)
            height = float(region.height)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DicomPixelDecodeError(
                "A pixel detector returned invalid region coordinates",
                details={"path": str(source_path)},
            ) from exc
        if frame_index != region.frame_index or not 0 <= frame_index < number_of_frames:
            raise DicomPixelDecodeError(
                "A pixel detector returned a region for an invalid frame",
                details={
                    "path": str(source_path),
                    "frame_index": region.frame_index,
                    "number_of_frames": number_of_frames,
                },
            )
        if not all(math.isfinite(value) for value in (x, y, width, height)) or width <= 0 or height <= 0:
            raise DicomPixelDecodeError(
                "A pixel detector returned an empty or invalid region",
                details={"path": str(source_path), "frame_index": frame_index},
            )

        frame = frame_arrays[frame_index]
        rows, columns = int(frame.shape[0]), int(frame.shape[1])
        left = max(0, math.floor(x) - padding)
        top = max(0, math.floor(y) - padding)
        right = min(columns, math.ceil(x + width) + padding)
        bottom = min(rows, math.ceil(y + height) + padding)
        if left >= right or top >= bottom:
            raise DicomPixelDecodeError(
                "A pixel detector returned a region outside the image boundary",
                details={
                    "path": str(source_path),
                    "frame_index": frame_index,
                    "image_rows": rows,
                    "image_columns": columns,
                },
            )
        frame[top:bottom, left:right, ...] = fill
        applied += 1

    try:
        if not hasattr(dataset, "file_meta"):
            from pydicom.dataset import FileMetaDataset

            dataset.file_meta = FileMetaDataset()
        # Big-endian and encapsulated sources are normalised to a single safe,
        # interoperable output syntax after decoding.
        dataset.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        set_pixel_data(
            dataset,
            array,
            photometric_interpretation=photometric,
            bits_stored=bits_stored,
            generate_instance_uid=False,
        )
    except Exception as exc:
        raise DicomPixelDecodeError(
            "Redacted Pixel Data could not be written safely",
            details={"path": str(source_path), "writer_error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    return applied


def assess_pixel_data(
    dataset: Dataset,
    *,
    source_path: str | Path,
    supported_modalities: set[str],
    clean_overlays: bool,
    require_decodable: bool = True,
    detector: BurnedInPixelDetector | None = None,
    review_decision: str | None = None,
    require_detector: bool = False,
    redact_detector_findings: bool = False,
) -> PixelAssessment:
    study_uid = str(dataset.get("StudyInstanceUID", "")) or None
    series_uid = str(dataset.get("SeriesInstanceUID", "")) or None
    sop_uid = str(dataset.get("SOPInstanceUID", "")) or None
    base = {
        "path": str(source_path),
        "study_instance_uid": study_uid,
        "series_instance_uid": series_uid,
        "sop_instance_uid": sop_uid,
    }
    risks: list[DICOMRisk] = []
    modality = str(dataset.get("Modality", "")).upper().strip()
    if modality not in supported_modalities:
        risks.append(
            DICOMRisk(
                code="UNSUPPORTED_MODALITY",
                severity=DICOMRiskSeverity.BLOCKING,
                message="The modality is outside the validated DICOM core scope",
                details={"modality": modality, "supported_modalities": sorted(supported_modalities)},
                **base,
            )
        )

    if "PixelData" not in dataset:
        risks.append(
            DICOMRisk(
                code="PIXEL_DATA_MISSING",
                severity=DICOMRiskSeverity.BLOCKING,
                message="An image instance contains no Pixel Data",
                **base,
            )
        )
        return PixelAssessment(status=DICOMPixelStatus.BLOCKED, risks=risks)

    frames: list[np.ndarray] = []
    if require_decodable or detector is not None:
        try:
            frames = decoded_frames(dataset, source_path=source_path)
        except DicomPixelDecodeError as exc:
            risks.append(
                DICOMRisk(
                    code="PIXEL_DATA_UNDECODABLE",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="Pixel Data cannot be decoded; processing fails closed",
                    details=exc.details,
                    **base,
                )
            )
            return PixelAssessment(status=DICOMPixelStatus.BLOCKED, risks=risks)

    overlays = _overlay_count(dataset)
    overlay_needs_review = False
    if overlays and not clean_overlays:
        overlay_needs_review = True
        risks.append(
            DICOMRisk(
                code="OVERLAY_NOT_CLEANED",
                severity=DICOMRiskSeverity.HIGH,
                message="Overlay attributes exist but overlay cleaning is disabled",
                details={"element_count": overlays},
                **base,
            )
        )

    burned_in_needs_review = False
    burned_in_risk: DICOMRisk | None = None
    burned_in = str(dataset.get("BurnedInAnnotation", "")).upper().strip()
    if burned_in == "YES":
        burned_in_needs_review = True
        burned_in_risk = DICOMRisk(
            code="PIXEL_BURNED_IN_REVIEW_REQUIRED",
            severity=DICOMRiskSeverity.HIGH,
            message="Burned-in annotation is declared and needs pixel redaction or human verification",
            **base,
        )
        risks.append(burned_in_risk)
    elif burned_in != "NO":
        burned_in_needs_review = True
        burned_in_risk = DICOMRisk(
            code="PIXEL_BURNED_IN_STATUS_UNKNOWN",
            severity=DICOMRiskSeverity.HIGH,
            message="Burned-in annotation status is not explicitly NO",
            **base,
        )
        risks.append(burned_in_risk)

    recognizable_needs_review = False
    if str(dataset.get("RecognizableVisualFeatures", "")).upper().strip() == "YES":
        recognizable_needs_review = True
        risks.append(
            DICOMRisk(
                code="RECOGNIZABLE_VISUAL_FEATURES_REVIEW_REQUIRED",
                severity=DICOMRiskSeverity.HIGH,
                message="Recognizable visual features require an approved defacing/review workflow",
                **base,
            )
        )

    detector_result: PixelDetectorResult | None = None
    detector_needs_review = False
    auto_redaction_planned = False
    if detector is not None:
        try:
            detector_result = detector.detect(dataset, frames)
        except Exception as exc:
            risks.append(
                DICOMRisk(
                    code="PIXEL_DETECTOR_FAILED",
                    severity=DICOMRiskSeverity.BLOCKING,
                    message="The configured pixel PHI detector failed",
                    details={"error": f"{type(exc).__name__}: {exc}"},
                    **base,
                )
            )
            return PixelAssessment(
                status=DICOMPixelStatus.BLOCKED,
                risks=risks,
                decoded=bool(frames),
                frame_count=len(frames),
            )
        if detector_result.regions:
            auto_redaction_planned = bool(redact_detector_findings)
            detector_needs_review = not auto_redaction_planned
            if auto_redaction_planned and burned_in_risk is not None:
                burned_in_risk.severity = DICOMRiskSeverity.WARNING
                burned_in_risk.message = "Burned-in annotation will be removed by automatic pixel redaction"
                burned_in_risk.details = {
                    **burned_in_risk.details,
                    "auto_redaction_planned": True,
                    "region_count": len(detector_result.regions),
                }
            risks.append(
                DICOMRisk(
                    code="PIXEL_DETECTOR_FINDINGS",
                    severity=(DICOMRiskSeverity.WARNING if auto_redaction_planned else DICOMRiskSeverity.HIGH),
                    message=(
                        "The pixel detector found identifying regions scheduled for automatic redaction"
                        if auto_redaction_planned
                        else "The pixel detector found possible identifying regions"
                    ),
                    details={
                        "detector": detector_result.detector_name,
                        "version": detector_result.detector_version,
                        "region_count": len(detector_result.regions),
                        "auto_redaction_planned": auto_redaction_planned,
                    },
                    **base,
                )
            )
    elif require_detector:
        risks.append(
            DICOMRisk(
                code="PIXEL_DETECTOR_REQUIRED",
                severity=DICOMRiskSeverity.BLOCKING,
                message="The selected policy requires a pixel detector, but none is configured",
                **base,
            )
        )
        return PixelAssessment(
            status=DICOMPixelStatus.BLOCKED,
            risks=risks,
            decoded=bool(frames),
            frame_count=len(frames),
        )

    needs_review = (
        overlay_needs_review
        or recognizable_needs_review
        or detector_needs_review
        or (burned_in_needs_review and not auto_redaction_planned)
    )
    approved = _APPROVED_DECISIONS.get(str(review_decision or "").lower())
    if needs_review and approved is None:
        return PixelAssessment(
            status=DICOMPixelStatus.REVIEW_REQUIRED,
            risks=risks,
            decoded=bool(frames),
            frame_count=len(frames),
            detector_result=detector_result,
        )
    return PixelAssessment(
        status=(
            approved or (DICOMPixelStatus.EXTERNALLY_REDACTED if auto_redaction_planned else DICOMPixelStatus.CLEAR)
        ),
        risks=risks,
        decoded=bool(frames),
        frame_count=len(frames),
        detector_result=detector_result,
    )


__all__ = [
    "BurnedInPixelDetector",
    "PixelAssessment",
    "PixelDetectorResult",
    "PixelRegion",
    "assess_pixel_data",
    "decoded_frames",
    "redact_pixel_regions",
    "remove_overlays",
]
