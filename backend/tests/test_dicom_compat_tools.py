from __future__ import annotations

import json

import pytest

pytest.importorskip("pydicom")

from dicom_test_support import REPO_ROOT  # noqa: F401 - also adds repository root to sys.path
from tools.dicom_compat.compare_outputs import compare_trees
from tools.dicom_compat.generate_synthetic_cases import create_fixture_set
from tools.dicom_compat.validate_corpus import inspect_file, run_independent_tools


def test_value_blind_validator_finds_structured_and_unstructured_risks(tmp_path):
    root = tmp_path / "dicom-generated-suite"
    create_fixture_set(root)
    path = root / "single" / "burned_in_fake.dcm"
    result = inspect_file(path, relative_to=root, decode_pixels=True)

    assert result["readable"] is True
    assert result["burned_in_annotation"] == "YES"
    assert result["pixel"]["decoded"] is True
    assert result["structured"]["sequence_depth"] >= 1
    assert result["structured"]["private_element_count"] >= 2
    assert result["structured"]["identifier_presence"]["PatientName"] is True
    rendered = json.dumps(result)
    assert "TEST^PERSON1" not in rendered
    assert "FAKE-MRN-0001" not in rendered
    assert "SYNTHETIC TEST HOSPITAL" not in rendered


def test_validator_distinguishes_non_dicom_from_force_readable_dataset(tmp_path):
    root = tmp_path / "dicom-generated-suite"
    create_fixture_set(root)
    result = inspect_file(root / "malformed" / "not_dicom.dcm")
    # A force parser can produce a meaningless element from arbitrary bytes;
    # it must not be promoted to a valid DICOM object without required UIDs.
    assert not (
        result["readable"]
        and result.get("sop_class_uid_present")
        and result.get("sop_instance_uid_present")
    )


def test_dcmtk_compatibility_when_available(tmp_path):
    root = tmp_path / "dicom-generated-suite"
    create_fixture_set(root)
    results = run_independent_tools(root / "single" / "burned_in_fake.dcm")
    if "dcmtk_dcmdump" not in results:
        pytest.skip("DCMTK not installed; run tools/dicom_compat/fetch_dcmtk.py")
    assert results["dcmtk_dcmdump"]["success"] is True
    assert "diagnostic_sha256" in results["dcmtk_dcmdump"]


def test_output_comparator_enforces_deidentification_and_clinical_integrity(tmp_path):
    import pydicom

    root = tmp_path / "dicom-generated-suite"
    create_fixture_set(root)
    source_root = root / "single"
    output_root = tmp_path / "output"
    output_root.mkdir()
    source = pydicom.dcmread(source_root / "burned_in_fake.dcm")
    output = source.copy()
    for keyword in (
        "PatientName",
        "PatientBirthDate",
        "AccessionNumber",
        "ReferringPhysicianName",
        "PerformingPhysicianName",
        "InstitutionName",
        "StationName",
    ):
        setattr(output, keyword, "")
    output.PatientID = "PSEUDO-0001"
    output.remove_private_tags()
    output.PatientIdentityRemoved = "YES"
    output.DeidentificationMethod = "Basic Application Confidentiality Profile; Clean Pixel Data"
    output.BurnedInAnnotation = "NO"
    output.StudyInstanceUID += ".9"
    output.SeriesInstanceUID += ".9"
    output.SOPInstanceUID += ".9"
    output.file_meta.MediaStorageSOPInstanceUID = output.SOPInstanceUID
    output.FrameOfReferenceUID += ".9"
    output.save_as(output_root / "burned_in_fake.dcm", enforce_file_format=True)

    report = compare_trees(
        source_root,
        output_root,
        [{"source": "burned_in_fake.dcm", "output": "burned_in_fake.dcm", "pixel_modified": True}],
        retain_uids=False,
        allow_private=False,
        include_paths=False,
    )
    assert report["summary"] == {"pairs": 1, "passed": 1, "failed": 0, "uid_mapping_findings": 0}
    rendered = json.dumps(report)
    assert "burned_in_fake.dcm" not in rendered
    assert "PSEUDO-0001" not in rendered


def test_output_comparator_detects_unchanged_identifiers(tmp_path):
    root = tmp_path / "dicom-generated-suite"
    create_fixture_set(root)
    report = compare_trees(
        root / "single",
        root / "single",
        [{"source": "burned_in_fake.dcm", "output": "burned_in_fake.dcm", "pixel_modified": False}],
        retain_uids=False,
        allow_private=False,
        include_paths=False,
    )
    codes = {finding["code"] for finding in report["results"][0]["findings"]}
    assert {"patient_identity_removed_not_yes", "identifier_unchanged", "private_elements_remain", "uid_not_remapped"}.issubset(codes)
