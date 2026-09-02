from __future__ import annotations

import hashlib
import zipfile
from collections import Counter

import pytest

pydicom = pytest.importorskip("pydicom")

from dicom_test_support import REPO_ROOT  # noqa: F401 - also adds repository root to sys.path
from tools.dicom_compat.generate_synthetic_cases import create_fixture_set


@pytest.fixture()
def generated(tmp_path):
    root = tmp_path / "dicom-generated-suite"
    create_fixture_set(root)
    return root


def test_single_dicom_roundtrip_preserves_structured_and_pixel_content(generated, tmp_path):
    source = generated / "single" / "burned_in_fake.dcm"
    dataset = pydicom.dcmread(source)
    output = tmp_path / "roundtrip.dcm"
    dataset.save_as(output, enforce_file_format=True)
    reread = pydicom.dcmread(output)

    assert reread.PatientName == dataset.PatientName
    assert reread.RequestAttributesSequence[0].RequestedProcedureID == "FAKE-RP-1"
    assert reread[(0x0011, 0x1010)].value == "FAKE PRIVATE PATIENT NOTE"
    assert reread.BurnedInAnnotation == "YES"
    assert reread.pixel_array.shape == dataset.pixel_array.shape == (160, 320)
    assert hashlib.sha256(reread.pixel_array.tobytes()).digest() == hashlib.sha256(dataset.pixel_array.tobytes()).digest()


def test_batch_groups_at_patient_study_series_instance_levels(generated):
    datasets = [pydicom.dcmread(path, stop_before_pixels=True) for path in (generated / "batch").rglob("*.dcm")]
    assert len(datasets) == 4
    assert len({str(ds.PatientID) for ds in datasets}) == 2
    assert len({str(ds.StudyInstanceUID) for ds in datasets}) == 2
    assert len({str(ds.SeriesInstanceUID) for ds in datasets}) == 3
    assert len({str(ds.SOPInstanceUID) for ds in datasets}) == 4
    per_series = Counter(str(ds.SeriesInstanceUID) for ds in datasets)
    assert sorted(per_series.values()) == [1, 1, 2]


def test_batch_archive_contains_only_safe_relative_members(generated):
    with zipfile.ZipFile(generated / "batch_inputs.zip") as archive:
        names = archive.namelist()
    assert len([name for name in names if name.endswith(".dcm")]) == 4
    assert all(not name.startswith(("/", "\\")) and ".." not in name.split("/") for name in names)


def test_malformed_and_non_dicom_inputs_are_rejected(generated):
    malformed = generated / "malformed"
    with pytest.raises((pydicom.errors.InvalidDicomError, EOFError)):
        pydicom.dcmread(malformed / "not_dicom.dcm")
    with pytest.raises((pydicom.errors.InvalidDicomError, EOFError)):
        pydicom.dcmread(malformed / "empty.dcm")
    # Truncation may be tolerated for metadata, but pixel decoding must fail or
    # yield fewer bytes than the declared complete frame.
    truncated = pydicom.dcmread(malformed / "truncated.dcm")
    with pytest.raises(ValueError):
        _ = truncated.pixel_array
