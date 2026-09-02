from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import (
    DigitalXRayImageStorageForPresentation,
    ExplicitVRLittleEndian,
    RLELossless,
    generate_uid,
)

from app.models.dicom_schemas import DICOMPixelStatus
from app.services.dicom.pixel import PixelDetectorResult, PixelRegion
from app.services.dicom.processor import anonymize_paths

_SECRET = "deterministic-redaction-test-secret-32-bytes"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base_dataset(
    path: Path,
    *,
    study_uid: str,
    series_uid: str,
    sop_uid: str,
    pixels: np.ndarray,
    burned_in: str,
) -> FileDataset:
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = DigitalXRayImageStorageForPresentation
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()
    file_meta.SourceApplicationEntityTitle = "SYNTH_AE"

    dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"SYNTHETIC PREAMBLE PHI".ljust(128, b"\x00"))
    dataset.SOPClassUID = DigitalXRayImageStorageForPresentation
    dataset.SOPInstanceUID = sop_uid
    dataset.StudyInstanceUID = study_uid
    dataset.SeriesInstanceUID = series_uid
    dataset.FrameOfReferenceUID = generate_uid()
    dataset.Modality = "DX"
    dataset.PatientName = "SYNTHETIC^PERSON"
    dataset.PatientID = "FAKE-MRN-0001"
    dataset.PatientBirthDate = "19700101"
    dataset.AccessionNumber = "FAKE-ACC-0001"
    dataset.StudyID = "FAKE-STUDY-01"
    dataset.ReferringPhysicianName = "SYNTHETIC^DOCTOR"
    dataset.InstitutionName = "SYNTHETIC TEST HOSPITAL"
    dataset.StationName = "FAKE-SCANNER-1"
    dataset.StudyDescription = "SYNTHETIC PERSON HEAD"
    dataset.SeriesDescription = "SYNTHETIC PERSON SERIES"
    dataset.StudyDate = "20260115"
    dataset.SeriesDate = "20260115"
    dataset.BurnedInAnnotation = burned_in
    dataset.RecognizableVisualFeatures = "NO"

    frames = pixels if pixels.ndim >= 3 else pixels[np.newaxis, ...]
    dataset.Rows = int(frames.shape[-2])
    dataset.Columns = int(frames.shape[-1])
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = int(frames.dtype.itemsize * 8)
    dataset.BitsStored = dataset.BitsAllocated
    dataset.HighBit = dataset.BitsStored - 1
    dataset.PixelRepresentation = 0
    if len(frames) > 1:
        dataset.NumberOfFrames = len(frames)
    dataset.PixelSpacing = ["0.35", "0.35"]
    dataset.PixelData = np.ascontiguousarray(frames).tobytes()

    dataset.add_new((0x0011, 0x0010), "LO", "SYNTHETIC_CREATOR")
    dataset.add_new((0x0011, 0x1010), "LO", "FAKE PRIVATE PATIENT NOTE")
    return dataset


def _iter_elements(dataset: Dataset) -> Iterable[Any]:
    for element in dataset:
        yield element
        if element.VR == "SQ":
            for item in element.value or []:
                yield from _iter_elements(item)


def _all_non_binary_text(dataset: Dataset) -> str:
    values: list[str] = []
    for element in _iter_elements(dataset):
        if element.VR not in {"OB", "OW", "OF", "OD", "OL", "OV", "UN", "SQ"}:
            values.append(str(element.value))
    return "\n".join(values)


def _write_structured_pair(source_dir: Path) -> tuple[Path, Path, dict[str, str]]:
    source_dir.mkdir()
    study_uid = generate_uid()
    series_uid = generate_uid()
    first_uid = generate_uid()
    second_uid = generate_uid()
    tracking_uid = generate_uid()
    pixels = np.arange(64, dtype=np.uint8).reshape(8, 8)
    first_path = source_dir / "first.dcm"
    second_path = source_dir / "second.dcm"
    first = _base_dataset(
        first_path,
        study_uid=study_uid,
        series_uid=series_uid,
        sop_uid=first_uid,
        pixels=pixels,
        burned_in="NO",
    )
    second = _base_dataset(
        second_path,
        study_uid=study_uid,
        series_uid=series_uid,
        sop_uid=second_uid,
        pixels=pixels + 1,
        burned_in="NO",
    )

    reference = Dataset()
    reference.ReferencedSOPClassUID = DigitalXRayImageStorageForPresentation
    reference.ReferencedSOPInstanceUID = second_uid
    request = Dataset()
    request.PatientName = "NESTED^SYNTHETIC"
    request.RequestedProcedureID = "FAKE-RP-0001"
    request.ScheduledProcedureStepDescription = "SYNTHETIC PERSON FOLLOWUP"
    request.TrackingUID = tracking_uid
    request.ReferencedImageSequence = Sequence([reference])
    request.add_new((0x0013, 0x0010), "LO", "NESTED_CREATOR")
    request.add_new((0x0013, 0x1010), "LO", "NESTED PRIVATE PHI")
    first.RequestAttributesSequence = Sequence([request])

    first.save_as(first_path, enforce_file_format=True)
    second.save_as(second_path, enforce_file_format=True)
    return first_path, second_path, {
        "study_uid": study_uid,
        "series_uid": series_uid,
        "first_uid": first_uid,
        "second_uid": second_uid,
        "tracking_uid": tracking_uid,
    }


def test_structured_phi_is_removed_recursively_and_uid_references_stay_consistent(tmp_path: Path) -> None:
    source_dir = tmp_path / "structured-source"
    first_path, second_path, original = _write_structured_pair(source_dir)
    source_hashes = {path: _sha256(path) for path in (first_path, second_path)}

    report = anonymize_paths(
        [first_path, second_path],
        tmp_path / "structured-output",
        profile="strict",
        options={"mapping_secret": _SECRET, "mapping_namespace": "tenant-structured"},
    )

    assert report.status == "completed"
    assert report.validation.ok is True
    assert report.validation.checked_instances == 2
    assert not report.validation.issues
    assert {path: _sha256(path) for path in (first_path, second_path)} == source_hashes

    outputs = {
        item.original_sop_instance_uid: pydicom.dcmread(item.output_path) for item in report.instances
    }
    first = outputs[original["first_uid"]]
    second = outputs[original["second_uid"]]
    nested = first.RequestAttributesSequence[0]

    assert first.PatientIdentityRemoved == "YES"
    assert str(first.PatientName) == ""
    assert first.PatientID.startswith("P-") and first.PatientID != "FAKE-MRN-0001"
    assert str(first.InstitutionName) == ""
    assert str(nested.PatientName) == ""
    assert nested.RequestedProcedureID != "FAKE-RP-0001"
    assert str(nested.ScheduledProcedureStepDescription) == ""
    assert nested.TrackingUID != original["tracking_uid"]
    assert first.StudyInstanceUID == second.StudyInstanceUID != original["study_uid"]
    assert first.SeriesInstanceUID == second.SeriesInstanceUID != original["series_uid"]
    assert first.SOPInstanceUID != original["first_uid"]
    assert second.SOPInstanceUID != original["second_uid"]
    assert nested.ReferencedImageSequence[0].ReferencedSOPInstanceUID == second.SOPInstanceUID
    assert not any(element.tag.is_private for element in _iter_elements(first))
    assert first.preamble == b"\x00" * 128
    assert "SourceApplicationEntityTitle" not in first.file_meta

    output_text = _all_non_binary_text(first)
    for source_phi in (
        "SYNTHETIC^PERSON",
        "FAKE-MRN-0001",
        "FAKE-ACC-0001",
        "SYNTHETIC^DOCTOR",
        "SYNTHETIC TEST HOSPITAL",
        "NESTED^SYNTHETIC",
        "FAKE-RP-0001",
        "SYNTHETIC PERSON FOLLOWUP",
        "FAKE PRIVATE PATIENT NOTE",
        "NESTED PRIVATE PHI",
    ):
        assert source_phi not in output_text

    change_paths = {change.path for item in report.instances for change in item.changes}
    assert any("[0]" in path for path in change_paths), "nested sequence de-identification must be reported"


class _DeterministicPixelDetector:
    regions = (
        PixelRegion(frame_index=0, x=8, y=4, width=24, height=9, text="SYNTHETIC PERSON", confidence=1.0),
        PixelRegion(frame_index=1, x=50, y=6, width=30, height=10, text="FAKE-MRN-0001", confidence=1.0),
    )

    def detect(self, dataset: Dataset, frames: list[np.ndarray]) -> PixelDetectorResult:
        assert int(dataset.NumberOfFrames) == len(frames) == 2
        assert all(frame.shape == (64, 96) for frame in frames)
        return PixelDetectorResult(
            regions=list(self.regions),
            detector_name="deterministic-test-detector",
            detector_version="1.0",
        )


def _write_rle_burned_in(path: Path) -> np.ndarray:
    pixels = np.empty((2, 64, 96), dtype=np.uint8)
    for frame_index in range(2):
        pixels[frame_index] = np.arange(96, dtype=np.uint8)[None, :] + 32 + frame_index
    pixels[0, 4:13, 8:32] = 245
    pixels[1, 6:16, 50:80] = 230
    dataset = _base_dataset(
        path,
        study_uid=generate_uid(),
        series_uid=generate_uid(),
        sop_uid=generate_uid(),
        pixels=pixels,
        burned_in="YES",
    )
    dataset.compress(RLELossless)
    dataset.save_as(path, enforce_file_format=True)
    return pixels


def test_burned_in_phi_is_redacted_per_frame_and_rle_output_remains_valid(tmp_path: Path) -> None:
    source_path = tmp_path / "burned-in-rle.dcm"
    original_pixels = _write_rle_burned_in(source_path)
    source_hash = _sha256(source_path)
    source_before = pydicom.dcmread(source_path)
    assert source_before.file_meta.TransferSyntaxUID == RLELossless
    np.testing.assert_array_equal(source_before.pixel_array, original_pixels)

    report = anonymize_paths(
        [source_path],
        tmp_path / "pixel-output",
        profile="strict",
        options={
            "mapping_secret": _SECRET,
            "mapping_namespace": "tenant-pixel",
            "clean_pixel_data": True,
            "pixel_ocr_required": True,
            "pixel_redaction_padding": 0,
        },
        detector=_DeterministicPixelDetector(),
    )

    assert report.status == "completed"
    assert report.validation.ok is True
    assert report.validation.checked_instances == 1
    assert not report.validation.issues
    assert _sha256(source_path) == source_hash
    result = report.instances[0]
    assert result.pixel_status == DICOMPixelStatus.EXTERNALLY_REDACTED
    assert result.pixel_regions_redacted == 2
    assert result.validation_ok is True

    output = pydicom.dcmread(result.output_path)
    output_pixels = np.asarray(output.pixel_array)
    assert output.BurnedInAnnotation == "NO"
    method_codes = {str(item.CodeValue) for item in output.DeidentificationMethodCodeSequence}
    assert {"113100", "113101"}.issubset(method_codes)
    assert int(output.NumberOfFrames) == 2
    assert (int(output.Rows), int(output.Columns), int(output.SamplesPerPixel)) == (64, 96, 1)
    assert [float(value) for value in output.PixelSpacing] == [0.35, 0.35]
    assert output_pixels.shape == original_pixels.shape
    assert output_pixels.dtype == original_pixels.dtype

    redacted_mask = np.zeros(original_pixels.shape, dtype=bool)
    for region in _DeterministicPixelDetector.regions:
        y_stop = region.y + region.height
        x_stop = region.x + region.width
        redacted_mask[region.frame_index, region.y:y_stop, region.x:x_stop] = True
    assert np.all(output_pixels[redacted_mask] == 0)
    np.testing.assert_array_equal(output_pixels[~redacted_mask], original_pixels[~redacted_mask])
    assert hashlib.sha256(output.PixelData).hexdigest() != hashlib.sha256(source_before.PixelData).hexdigest()

    # A compressed source may be safely normalized to an uncompressed transfer
    # syntax after masking.  The invariant is an internally consistent, fully
    # decodable output rather than retaining the original compression wrapper.
    assert output.file_meta.TransferSyntaxUID.is_compressed is False
    assert output.file_meta.MediaStorageSOPInstanceUID == output.SOPInstanceUID
    assert output.SOPInstanceUID != source_before.SOPInstanceUID
    assert output.PatientID != source_before.PatientID
    assert "SYNTHETIC PERSON" not in report.model_dump_json()
    assert "FAKE-MRN-0001" not in report.model_dump_json()
