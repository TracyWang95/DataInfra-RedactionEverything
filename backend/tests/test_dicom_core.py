from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pydicom
import pytest
from PIL import Image
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.sequence import Sequence
from pydicom.uid import (
    CTImageStorage,
    DigitalXRayImageStorageForPresentation,
    ExplicitVRLittleEndian,
    JPEGBaseline8Bit,
    MRImageStorage,
    generate_uid,
)

from app.services.dicom import (
    DicomConfigurationError,
    DicomPixelDecodeError,
    DicomUnsafeOperationError,
    anonymize_study,
    diff_dicom_tags,
    inspect_dicom_paths,
    preflight_study,
    render_instance_preview,
)
from app.services.dicom import processor as dicom_processor

_SECRET = "unit-test-dicom-pseudonym-secret-32-bytes"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_dicom(
    path: Path,
    *,
    modality: str = "CT",
    study_uid: str | None = None,
    series_uid: str | None = None,
    sop_uid: str | None = None,
    patient_id: str = "PAT-001",
    study_date: str = "20250314",
    burned_in: str | None = "NO",
    frames: int = 1,
    compressed: bool = False,
    add_overlay: bool = False,
) -> FileDataset:
    sop_classes = {
        "CT": CTImageStorage,
        "MR": MRImageStorage,
        "CR": DigitalXRayImageStorageForPresentation,
        "DX": DigitalXRayImageStorageForPresentation,
    }
    sop_class = sop_classes.get(modality, CTImageStorage)
    study_uid = study_uid or generate_uid()
    series_uid = series_uid or generate_uid()
    sop_uid = sop_uid or generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = JPEGBaseline8Bit if compressed else ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()
    file_meta.SourceApplicationEntityTitle = "HOSPITAL_AE"
    preamble = b"PATIENT PREAMBLE PHI".ljust(128, b"\x00")
    dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=preamble)
    dataset.SOPClassUID = sop_class
    dataset.SOPInstanceUID = sop_uid
    dataset.StudyInstanceUID = study_uid
    dataset.SeriesInstanceUID = series_uid
    dataset.FrameOfReferenceUID = generate_uid()
    dataset.Modality = modality
    dataset.PatientName = "DOE^JANE"
    dataset.PatientID = patient_id
    dataset.PatientBirthDate = "19800102"
    dataset.PatientSex = "F"
    dataset.StudyDate = study_date
    dataset.SeriesDate = study_date
    dataset.AcquisitionDateTime = f"{study_date}121314.123+0800"
    dataset.AccessionNumber = "ACC-SECRET-001"
    dataset.StudyID = "STUDY-SECRET"
    dataset.InstitutionName = "Secret Hospital"
    dataset.StudyDescription = "Jane Doe Head"
    dataset.SeriesDescription = "Patient Jane Series"
    dataset.SeriesNumber = 1
    dataset.InstanceNumber = 1
    if burned_in is not None:
        dataset.BurnedInAnnotation = burned_in
    dataset.Rows = 2
    dataset.Columns = 3
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16 if not compressed else 8
    dataset.BitsStored = 12 if not compressed else 8
    dataset.HighBit = 11 if not compressed else 7
    dataset.PixelRepresentation = 0
    dataset.WindowCenter = 100
    dataset.WindowWidth = 200
    values = np.arange(frames * 6, dtype=np.uint16).reshape(frames, 2, 3)
    if frames > 1:
        dataset.NumberOfFrames = frames
    if compressed:
        dataset.PixelData = encapsulate([b"this-is-not-a-jpeg-bitstream"] * frames)
        dataset["PixelData"].is_undefined_length = True
    else:
        dataset.PixelData = values.tobytes()
    dataset.add_new((0x0011, 0x0010), "LO", "VENDOR_CREATOR")
    dataset.add_new((0x0011, 0x1010), "LO", "PRIVATE_PATIENT_SECRET")
    if add_overlay:
        dataset.add_new((0x6000, 0x0010), "US", 2)
        dataset.add_new((0x6000, 0x0011), "US", 3)
        dataset.add_new((0x6000, 0x0040), "CS", "G")
        dataset.add_new((0x6000, 0x0100), "US", 1)
        dataset.add_new((0x6000, 0x0102), "US", 0)
        dataset.add_new((0x6000, 0x3000), "OW", b"\x00\x00")
    dataset.save_as(path, enforce_file_format=True)
    return dataset


def test_inspect_groups_study_series_instance_and_plans_actions(tmp_path: Path) -> None:
    study_uid = generate_uid()
    series_a = generate_uid()
    series_b = generate_uid()
    first = tmp_path / "first.dcm"
    second = tmp_path / "second.dcm"
    third = tmp_path / "third.dcm"
    _make_dicom(first, study_uid=study_uid, series_uid=series_a, modality="CT")
    _make_dicom(second, study_uid=study_uid, series_uid=series_a, modality="CT")
    _make_dicom(third, study_uid=study_uid, series_uid=series_b, modality="MR")

    manifest = inspect_dicom_paths([str(tmp_path)], profile="research_strict")

    assert manifest["status"] == "ready"
    assert manifest["dicom_count"] == 3
    assert manifest["resolved_profile"] == "strict"
    assert len(manifest["studies"]) == 1
    assert len(manifest["studies"][0]["series"]) == 2
    assert {item["path"] for item in manifest["instances"]} == {str(first), str(second), str(third)}
    assert all(item["study_instance_uid"] == study_uid for item in manifest["instances"])
    assert all(item["metadata_summary"]["planned_action_counts"]["U"] >= 3 for item in manifest["instances"])
    assert all(item["metadata_summary"]["private_tag_count"] == 2 for item in manifest["instances"])


def test_anonymize_preserves_references_and_sources_but_removes_phi(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    study_uid = generate_uid()
    series_uid = generate_uid()
    first_uid = generate_uid()
    second_uid = generate_uid()
    first_path = source_dir / "one.dcm"
    second_path = source_dir / "two.dcm"
    first = _make_dicom(first_path, study_uid=study_uid, series_uid=series_uid, sop_uid=first_uid)
    _make_dicom(second_path, study_uid=study_uid, series_uid=series_uid, sop_uid=second_uid, study_date="20250320")
    reference = Dataset()
    reference.ReferencedSOPClassUID = CTImageStorage
    reference.ReferencedSOPInstanceUID = second_uid
    nested = Dataset()
    nested.PatientName = "NESTED^IDENTITY"
    nested.ReferencedImageSequence = Sequence([reference])
    first.SourceImageSequence = Sequence([nested])
    first.save_as(first_path, enforce_file_format=True)
    source_hashes = {path: _sha256(path) for path in (first_path, second_path)}

    report = anonymize_study(
        [str(first_path), str(second_path)],
        str(output_dir),
        profile="longitudinal",
        options={"mapping_secret": _SECRET, "mapping_namespace": "tenant-a"},
    )

    assert report["status"] == "completed"
    assert report["validation"]["ok"] is True
    assert report["validation"]["instance_count"] == 2
    assert {path: _sha256(path) for path in (first_path, second_path)} == source_hashes
    assert all(not Path(path).resolve().is_relative_to(source_dir.resolve()) for path in report["output_paths"])

    by_original = {
        item["original_sop_instance_uid"]: pydicom.dcmread(item["output_path"]) for item in report["instances"]
    }
    output_first = by_original[first_uid]
    output_second = by_original[second_uid]
    assert output_first.PatientID == output_second.PatientID
    assert output_first.PatientID.startswith("P-")
    assert str(output_first.PatientName) == ""
    assert str(output_first.InstitutionName) == ""
    assert not any(element.tag.is_private for element in output_first.iterall())
    assert output_first.preamble == b"\x00" * 128
    assert "SourceApplicationEntityTitle" not in output_first.file_meta
    assert output_first.PatientIdentityRemoved == "YES"
    assert any(item.CodeValue == "113107" for item in output_first.DeidentificationMethodCodeSequence)
    assert output_first.file_meta.MediaStorageSOPInstanceUID == output_first.SOPInstanceUID
    assert output_first.StudyInstanceUID != study_uid
    assert output_first.SeriesInstanceUID != series_uid
    assert output_first.SOPInstanceUID != first_uid
    assert (
        output_first.SourceImageSequence[0].ReferencedImageSequence[0].ReferencedSOPInstanceUID
        == output_second.SOPInstanceUID
    )
    assert str(output_first.SourceImageSequence[0].PatientName) == ""
    source_delta = pydicom.valuerep.DA("20250320") - pydicom.valuerep.DA("20250314")
    output_delta = pydicom.valuerep.DA(output_second.StudyDate) - pydicom.valuerep.DA(output_first.StudyDate)
    assert output_delta == source_delta
    assert output_first.PixelData == pydicom.dcmread(first_path).PixelData

    tag_diff = diff_dicom_tags(first_path, report["instances"][0]["output_path"])
    assert tag_diff["changed"] is True
    assert any(change["before"] and change["before"].get("keyword") == "PatientName" for change in tag_diff["changes"])


def test_unknown_burned_in_status_requires_explicit_per_instance_review(tmp_path: Path) -> None:
    path = tmp_path / "unknown.dcm"
    dataset = _make_dicom(path, burned_in=None)
    sop_uid = str(dataset.SOPInstanceUID)

    preflight = preflight_study([str(path)], options={"mapping_secret": _SECRET})
    assert preflight["can_execute"] is False
    assert preflight["status"] == "review_required"
    assert preflight["pixel_statuses"][str(path)]["status"] == "review_required"
    assert any(risk["code"] == "PIXEL_BURNED_IN_STATUS_UNKNOWN" for risk in preflight["risks"])

    with pytest.raises(DicomUnsafeOperationError):
        anonymize_study([str(path)], str(tmp_path / "blocked"), options={"mapping_secret": _SECRET})

    approved = anonymize_study(
        [str(path)],
        str(tmp_path / "approved"),
        options={
            "mapping_secret": _SECRET,
            "pixel_review_decisions": {sop_uid: "verified_clear"},
        },
    )
    output = pydicom.dcmread(approved["output_paths"][0])
    assert output.BurnedInAnnotation == "NO"
    assert approved["instances"][0]["pixel_status"] == "verified_clear"


def test_overlay_is_removed_and_declared_in_method(tmp_path: Path) -> None:
    path = tmp_path / "overlay.dcm"
    _make_dicom(path, add_overlay=True)

    report = anonymize_study(
        [str(path)],
        str(tmp_path / "output"),
        options={"mapping_secret": _SECRET},
    )
    output = pydicom.dcmread(report["output_paths"][0])
    assert not any(0x6000 <= element.tag.group <= 0x60FF for element in output.iterall())
    assert report["instances"][0]["overlays_removed"] == 6
    assert any(item.CodeValue == "113103" for item in output.DeidentificationMethodCodeSequence)


def test_multiframe_preview_honours_frame_and_window(tmp_path: Path) -> None:
    path = tmp_path / "multi.dcm"
    _make_dicom(path, modality="DX", frames=3)

    png = render_instance_preview(str(path), frame_index=2, window_center=6, window_width=12)

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    image = Image.open(__import__("io").BytesIO(png))
    assert image.size == (3, 2)
    assert image.mode == "L"
    with pytest.raises(IndexError):
        render_instance_preview(str(path), frame_index=3)


def test_compressed_undecodable_pixel_data_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "compressed.dcm"
    _make_dicom(path, modality="CR", compressed=True)

    manifest = inspect_dicom_paths([str(path)])
    assert manifest["instances"][0]["is_compressed"] is True
    preflight = preflight_study([str(path)], options={"mapping_secret": _SECRET})
    assert preflight["can_execute"] is False
    assert any(risk["code"] == "PIXEL_DATA_UNDECODABLE" for risk in preflight["blocking_risks"])
    with pytest.raises(DicomPixelDecodeError):
        render_instance_preview(str(path))


def test_custom_rule_applies_inside_sequence(tmp_path: Path) -> None:
    path = tmp_path / "sequence.dcm"
    dataset = _make_dicom(path)
    nested = Dataset()
    nested.PatientName = "SEQUENCE^NAME"
    dataset.RequestAttributesSequence = Sequence([nested])
    dataset.save_as(path, enforce_file_format=True)

    report = anonymize_study(
        [str(path)],
        str(tmp_path / "out"),
        options={
            "mapping_secret": _SECRET,
            "rules": [{"selector": "PatientName", "action": "X", "reason": "test override"}],
        },
    )
    output = pydicom.dcmread(report["output_paths"][0])
    assert "PatientName" not in output
    assert "PatientName" not in output.RequestAttributesSequence[0]


def test_public_policy_options_are_mapped_and_unsafe_decode_bypass_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "options.dcm"
    source = _make_dicom(path)

    report = anonymize_study(
        [str(path)],
        str(tmp_path / "retained"),
        profile="longitudinal_research",
        options={
            "mapping_secret": _SECRET,
            "date_mode": "retain",
            "uid_mode": "retain",
            "clean_pixel_data": True,
        },
    )
    output = pydicom.dcmread(report["output_paths"][0])
    assert output.StudyDate == source.StudyDate
    assert output.StudyInstanceUID == source.StudyInstanceUID
    assert output.SOPInstanceUID == source.SOPInstanceUID
    codes = {item.CodeValue for item in output.DeidentificationMethodCodeSequence}
    assert {"113100", "113101", "113106"}.issubset(codes)

    with pytest.raises(DicomConfigurationError):
        preflight_study([str(path)], options={"fail_on_pixel_decode_error": False})


def test_safe_private_allowlist_keeps_only_element_and_required_creator(tmp_path: Path) -> None:
    path = tmp_path / "private.dcm"
    _make_dicom(path)

    report = anonymize_study(
        [str(path)],
        str(tmp_path / "private-output"),
        options={
            "mapping_secret": _SECRET,
            "private_tag_policy": "safe_allowlist",
            "safe_private_tags": ["0011,1010"],
            "retain_safe_private": True,
        },
    )
    output = pydicom.dcmread(report["output_paths"][0])
    assert (0x0011, 0x0010) in output
    assert (0x0011, 0x1010) in output
    private_tags = {element.tag for element in output.iterall() if element.tag.is_private}
    assert private_tags == {pydicom.tag.Tag(0x0011, 0x0010), pydicom.tag.Tag(0x0011, 0x1010)}
    assert any(item.CodeValue == "113111" for item in output.DeidentificationMethodCodeSequence)


def test_batch_publication_rolls_back_if_second_atomic_move_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study_uid = generate_uid()
    first = tmp_path / "first-source.dcm"
    second = tmp_path / "second-source.dcm"
    _make_dicom(first, study_uid=study_uid)
    _make_dicom(second, study_uid=study_uid)
    source_hashes = {_sha256(first), _sha256(second)}
    output_dir = tmp_path / "atomic-output"
    real_replace = dicom_processor.os.replace
    calls = 0

    def fail_second(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected publication failure")
        real_replace(source, destination)

    monkeypatch.setattr(dicom_processor.os, "replace", fail_second)

    with pytest.raises(DicomUnsafeOperationError, match="rolled back"):
        anonymize_study(
            [str(first), str(second)],
            str(output_dir),
            options={"mapping_secret": _SECRET},
        )

    assert not list(output_dir.rglob("*.dcm"))
    assert {_sha256(first), _sha256(second)} == source_hashes


def test_overwrite_is_rejected_without_a_durable_backup_transaction(tmp_path: Path) -> None:
    path = tmp_path / "source.dcm"
    _make_dicom(path)
    with pytest.raises(DicomConfigurationError, match="overwrite"):
        anonymize_study(
            [str(path)],
            str(tmp_path / "out"),
            options={"mapping_secret": _SECRET, "overwrite": True},
        )
