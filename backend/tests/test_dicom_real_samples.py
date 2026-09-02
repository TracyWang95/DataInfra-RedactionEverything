from __future__ import annotations

import warnings

import pytest
from dicom_test_support import sample_path, samples_by_id

pydicom = pytest.importorskip("pydicom")

SAMPLES = samples_by_id()


def _require(sample_id: str):
    sample = SAMPLES[sample_id]
    path = sample_path(sample)
    if not path.is_file():
        pytest.skip("real DICOM corpus not fetched; run tools/dicom_compat/fetch_samples.py")
    return sample, path


@pytest.mark.parametrize(
    "sample_id",
    [
        "ct_explicit_le",
        "mr_explicit_le",
        "mr_implicit_le",
        "mr_explicit_be",
        "mr_jpeg2000_lossless",
        "mr_rle_lossless",
        "sc_jpeg_baseline",
        "sc_rle_multiframe",
        "secondary_capture_deflated",
        "nested_private_sequence",
        "comprehensive_sr",
        "mr_overlay",
        "dicomdir",
        "enhanced_ct_multiframe",
        "dx_overlay_private",
    ],
)
def test_valid_real_samples_match_declared_metadata(sample_id):
    sample, path = _require(sample_id)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dataset = pydicom.dcmread(path, stop_before_pixels=True)
    assert str(getattr(dataset, "Modality", "")) == sample["modality"]
    assert str(getattr(dataset.file_meta, "TransferSyntaxUID", "")) == sample["transfer_syntax"]
    assert int(getattr(dataset, "NumberOfFrames", 1) or 1) == sample["frames"]
    assert (path.read_bytes()[128:132] == b"DICM") is sample["has_dicm_prefix"]


def test_valid_cr_without_prefix_requires_controlled_force_fallback():
    sample, path = _require("cr_no_preamble")
    with pytest.raises(pydicom.errors.InvalidDicomError):
        pydicom.dcmread(path, stop_before_pixels=True)
    dataset = pydicom.dcmread(path, force=True, stop_before_pixels=True)
    assert dataset.Modality == sample["modality"] == "CR"
    assert dataset.SOPClassUID == "1.2.840.10008.5.1.4.1.1.1"


@pytest.mark.parametrize(
    "sample_id",
    [
        "ct_explicit_le",
        "mr_implicit_le",
        "mr_explicit_be",
        "mr_jpeg2000_lossless",
        "mr_rle_lossless",
        "sc_jpeg_baseline",
        "sc_rle_multiframe",
        "secondary_capture_deflated",
        "enhanced_ct_multiframe",
        "cr_no_preamble",
        "dx_overlay_private",
    ],
)
def test_real_pixel_samples_decode_with_expected_frame_count(sample_id):
    sample, path = _require(sample_id)
    dataset = pydicom.dcmread(path, force=sample["category"] == "valid-force-read")
    if sample["category"] == "valid-force-read" and not getattr(dataset.file_meta, "TransferSyntaxUID", None):
        dataset.file_meta.TransferSyntaxUID = pydicom.uid.ImplicitVRLittleEndian
    try:
        pixels = dataset.pixel_array
    except (ImportError, RuntimeError) as exc:
        pytest.skip(f"optional pixel codec unavailable: {exc}")
    assert pixels.size > 0
    if sample["frames"] > 1:
        assert pixels.shape[0] == sample["frames"]
    else:
        assert pixels.ndim in {2, 3}


def test_structured_sr_and_nested_private_sequences_are_recursive():
    _, sr_path = _require("comprehensive_sr")
    sr = pydicom.dcmread(sr_path, stop_before_pixels=True)
    assert sr.Modality == "SR" and len(sr.ContentSequence) > 0
    assert any(element.VR == "SQ" for element in sr.iterall())

    _, private_path = _require("nested_private_sequence")
    private = pydicom.dcmread(private_path, stop_before_pixels=True)
    assert any(element.tag.is_private for element in private.iterall())
    assert any(element.VR == "SQ" for element in private.iterall())


def test_overlay_and_burned_in_flags_are_visible_to_risk_pipeline():
    _, overlay_path = _require("mr_overlay")
    overlay = pydicom.dcmread(overlay_path, stop_before_pixels=True)
    assert any(0x6000 <= element.tag.group <= 0x60FF for element in overlay.iterall())

    _, enhanced_path = _require("enhanced_ct_multiframe")
    enhanced = pydicom.dcmread(enhanced_path, stop_before_pixels=True)
    assert enhanced.BurnedInAnnotation == "NO"
    assert int(enhanced.NumberOfFrames) == 2


def test_dicomdir_references_downloaded_batch_members():
    _, path = _require("dicomdir")
    for sample_id in ("cr_batch_1", "cr_batch_2", "cr_batch_3"):
        _require(sample_id)
    directory = pydicom.dcmread(path)
    references = {
        "/".join(str(part) for part in record.ReferencedFileID)
        for record in directory.DirectoryRecordSequence
        if hasattr(record, "ReferencedFileID")
    }
    assert {"77654033/CR1/6154", "77654033/CR2/6247", "77654033/CR3/6278"}.issubset(references)


@pytest.mark.parametrize("sample_id", ["mr_truncated", "invalid_vr", "missing_transfer_syntax", "ct_no_file_meta_anomaly"])
def test_known_anomalies_are_present_for_rejection_or_quarantine(sample_id):
    sample, path = _require(sample_id)
    assert sample["category"] == "known-anomaly"
    assert path.stat().st_size == sample["bytes"]
