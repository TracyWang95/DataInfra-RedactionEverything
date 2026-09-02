"""Integration checks against pydicom's bundled, non-synthetic DICOM corpus."""

from __future__ import annotations

from pathlib import Path

import pydicom
import pytest
from pydicom.data import get_testdata_file

from app.services.dicom import anonymize_study, inspect_dicom_paths, render_instance_preview

_CORPUS = Path(__file__).parent / "assets" / "dicom" / "cache"


def _bundled(name: str) -> str:
    path = get_testdata_file(name, download=False)
    if not path:
        pytest.skip(f"pydicom bundled sample is unavailable: {name}")
    return path


def test_real_dicomdir_indexes_cr_ct_mr_hierarchy() -> None:
    manifest = inspect_dicom_paths([_bundled("DICOMDIR")], profile="basic")

    assert manifest["status"] == "ready"
    assert manifest["dicom_count"] == 31
    assert len(manifest["studies"]) == 6
    assert {instance["modality"] for instance in manifest["instances"]} == {"CR", "CT", "MR"}
    assert not manifest["skipped"]


def test_real_ct_and_mr_round_trip_with_manual_pixel_review(tmp_path: Path) -> None:
    paths = [_bundled("CT_small.dcm"), _bundled("MR_small.dcm")]
    source_datasets = [pydicom.dcmread(path) for path in paths]
    decisions = {str(dataset.SOPInstanceUID): "verified_clear" for dataset in source_datasets}

    report = anonymize_study(
        paths,
        str(tmp_path / "real-output"),
        profile="longitudinal_research",
        options={
            "mapping_secret": "real-corpus-validation-secret-32-bytes",
            "mapping_namespace": "real-corpus-test",
            "pixel_review_decisions": decisions,
        },
    )

    assert report["validation"]["ok"] is True
    assert report["validation"]["checked_instances"] == 2
    assert {item["pixel_status"] for item in report["instances"]} == {"verified_clear"}
    for source, result in zip(source_datasets, report["instances"], strict=True):
        output = pydicom.dcmread(result["output_path"])
        assert output.pixel_array.shape == source.pixel_array.shape
        assert output.PixelData == source.PixelData
        assert str(output.PatientName) == ""
        assert output.PatientID != source.PatientID
        assert output.PatientIdentityRemoved == "YES"
        assert render_instance_preview(result["output_path"]).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize(
    ("relative_path", "force", "expected_modality", "expected_overlay_minimum"),
    [
        ("pydicom/MR_small_bigendian.dcm", False, "MR", 0),
        ("pydicom/MR_small_jp2klossless.dcm", False, "MR", 0),
        ("pydicom/MR_small_RLE.dcm", False, "MR", 0),
        ("pydicom/examples_overlay.dcm", False, "MR", 1),
        ("pydicom-data/eCT_Supplemental.dcm", False, "CT", 0),
        ("gdcm-data/CR-MONO1-10-chest.dcm", True, "CR", 0),
        ("gdcm-data/DX_GE_FALCON_SNOWY-VOI.dcm", False, "DX", 1),
    ],
)
def test_audited_real_modalities_encodings_and_overlays_round_trip(
    tmp_path: Path,
    relative_path: str,
    force: bool,
    expected_modality: str,
    expected_overlay_minimum: int,
) -> None:
    source_path = _CORPUS / relative_path
    if not source_path.is_file():
        pytest.skip("audited DICOM compatibility corpus has not been fetched")
    source = pydicom.dcmread(source_path, force=force)
    options = {
        "mapping_secret": "audited-real-corpus-secret-32-bytes",
        "mapping_namespace": relative_path,
        "force_dicom_read": force,
        "pixel_review_decisions": {str(source.SOPInstanceUID): "verified_clear"},
    }

    report = anonymize_study(
        [str(source_path)],
        str(tmp_path / Path(relative_path).stem),
        options=options,
    )
    output = pydicom.dcmread(report["output_paths"][0])

    assert report["validation"]["ok"] is True
    assert output.Modality == expected_modality
    assert output.PixelData == source.PixelData
    if force and not source.file_meta.get("TransferSyntaxUID"):
        assert output.pixel_array.shape == (int(source.Rows), int(source.Columns))
    else:
        assert output.pixel_array.shape == source.pixel_array.shape
    assert output.file_meta.TransferSyntaxUID == source.file_meta.get(
        "TransferSyntaxUID", output.file_meta.TransferSyntaxUID
    )
    assert report["instances"][0]["overlays_removed"] >= expected_overlay_minimum
    assert not any(0x6000 <= element.tag.group <= 0x60FF for element in output.iterall())
