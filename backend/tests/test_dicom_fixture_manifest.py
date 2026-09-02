from __future__ import annotations

import re
from urllib.parse import urlparse

from dicom_test_support import CACHE_ROOT, manifest, sample_path, sha256

SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def test_manifest_is_auditable_and_immutable():
    document = manifest()
    assert document["schema_version"] == 1
    assert document["policy"]["binary_files_committed"] is False
    assert document["policy"]["reports_must_not_contain_identifier_values"] is True
    assert {"pydicom", "pydicom-data", "gdcm-data"} == set(document["sources"])
    for source in document["sources"].values():
        assert COMMIT.fullmatch(source["commit"])
        assert source["repository"].startswith("https://github.com/")
        assert source["license"] and source["redistribution"] and source["privacy_review"]


def test_manifest_samples_have_unique_safe_paths_and_pinned_hashes():
    document = manifest()
    ids = [sample["id"] for sample in document["samples"]]
    paths = [sample["path"] for sample in document["samples"]]
    assert len(ids) == len(set(ids))
    assert len(paths) == len(set(paths))
    for sample in document["samples"]:
        assert SHA256.fullmatch(sample["sha256"])
        assert sample["bytes"] > 0
        assert sample["source"] in document["sources"]
        assert sample["category"] in {"valid", "valid-force-read", "known-anomaly"}
        assert ".." not in sample["path"].split("/")
        assert not sample["path"].startswith(("/", "\\"))
        parsed = urlparse(sample["url"])
        assert parsed.scheme == "https" and parsed.netloc == "raw.githubusercontent.com"
        assert document["sources"][sample["source"]]["commit"] in sample["url"]


def test_matrix_covers_required_modalities_encodings_and_risks():
    samples = manifest()["samples"]
    modalities = {sample["modality"] for sample in samples}
    features = {feature for sample in samples for feature in sample["features"]}
    assert {"CT", "MR", "CR", "DX"}.issubset(modalities)
    assert {
        "explicit-vr",
        "implicit-vr",
        "big-endian",
        "compressed",
        "jpeg-baseline",
        "jpeg2000",
        "rle",
        "multiframe",
        "missing-dicm-prefix",
        "private-tags",
        "nested-sequence",
        "overlay",
        "burned-in-no",
        "sr",
        "anomaly",
        "batch",
    }.issubset(features)


def test_any_locally_cached_samples_match_manifest_exactly():
    # Fetching is an explicit developer/CI step; pytest never downloads data.
    for sample in manifest()["samples"]:
        path = sample_path(sample)
        if not path.exists():
            continue
        assert path.stat().st_size == sample["bytes"]
        assert sha256(path) == sample["sha256"]
        assert path.resolve().is_relative_to(CACHE_ROOT.resolve())

