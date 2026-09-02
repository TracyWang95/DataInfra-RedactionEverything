#!/usr/bin/env python3
"""Compare source and anonymized DICOM trees without leaking identifier values.

By default files are paired by relative path.  A mapping JSON may instead map
source relative paths to output relative paths and declare whether pixels were
intentionally modified::

    {"pairs": [{"source": "a.dcm", "output": "x.dcm", "pixel_modified": true}]}

The emitted report contains pair numbers and path hashes, not filenames or
attribute values, so it can be retained as a CI or hospital acceptance record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pydicom

IDENTIFIERS = (
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientAddress",
    "OtherPatientIDs",
    "OtherPatientNames",
    "AccessionNumber",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "InstitutionName",
    "InstitutionAddress",
    "StationName",
)
PRIMARY_UIDS = ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "FrameOfReferenceUID")
CLINICAL_FIELDS = (
    "Modality",
    "SOPClassUID",
    "Rows",
    "Columns",
    "NumberOfFrames",
    "SamplesPerPixel",
    "PhotometricInterpretation",
    "BitsAllocated",
    "BitsStored",
    "HighBit",
    "PixelRepresentation",
    "PixelSpacing",
    "ImageOrientationPatient",
    "ImagePositionPatient",
    "SliceThickness",
)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def _value(dataset: Any, keyword: str) -> str:
    value = getattr(dataset, keyword, "")
    if isinstance(value, (list, tuple)):
        return "\\".join(str(item) for item in value)
    return str(value)


def _pixel_digest(dataset: Any) -> str | None:
    if "PixelData" not in dataset:
        return None
    array = dataset.pixel_array
    return hashlib.sha256(array.tobytes()).hexdigest()


def _read(path: Path) -> Any:
    try:
        return pydicom.dcmread(path)
    except pydicom.errors.InvalidDicomError:
        return pydicom.dcmread(path, force=True)


def _default_pairs(source_root: Path, output_root: Path) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative = source.relative_to(source_root)
        pairs.append({"source": relative.as_posix(), "output": relative.as_posix(), "pixel_modified": False})
    return pairs


def _load_pairs(mapping: Path | None, source_root: Path, output_root: Path) -> list[dict[str, Any]]:
    if mapping is None:
        return _default_pairs(source_root, output_root)
    with mapping.open(encoding="utf-8") as stream:
        document = json.load(stream)
    pairs = document.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("mapping JSON must contain a 'pairs' list")
    return pairs


def _safe_join(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes root: {relative!r}") from exc
    return candidate


def compare_pair(
    source_path: Path,
    output_path: Path,
    *,
    pixel_modified: bool,
    retain_uids: bool,
    allow_private: bool,
) -> tuple[dict[str, Any], dict[str, tuple[str, str]]]:
    findings: list[dict[str, str]] = []
    uid_pairs: dict[str, tuple[str, str]] = {}
    try:
        source = _read(source_path)
    except Exception as exc:
        return {"passed": False, "findings": [{"code": "source_unreadable", "type": type(exc).__name__}]}, uid_pairs
    try:
        output = _read(output_path)
    except Exception as exc:
        return {"passed": False, "findings": [{"code": "output_unreadable", "type": type(exc).__name__}]}, uid_pairs

    if str(getattr(output, "PatientIdentityRemoved", "")).upper() != "YES":
        findings.append({"code": "patient_identity_removed_not_yes"})
    if not (_value(output, "DeidentificationMethod") or getattr(output, "DeidentificationMethodCodeSequence", None)):
        findings.append({"code": "deidentification_method_missing"})

    for keyword in IDENTIFIERS:
        before = _value(source, keyword).strip()
        after = _value(output, keyword).strip()
        if before and after == before:
            findings.append({"code": "identifier_unchanged", "keyword": keyword})

    if not allow_private and any(element.tag.is_private for element in output.iterall()):
        findings.append({"code": "private_elements_remain"})

    for keyword in CLINICAL_FIELDS:
        if _value(source, keyword) != _value(output, keyword):
            findings.append({"code": "clinical_field_changed", "keyword": keyword})

    for keyword in PRIMARY_UIDS:
        before = _value(source, keyword)
        after = _value(output, keyword)
        if before and not after:
            findings.append({"code": "required_uid_missing", "keyword": keyword})
        elif before and after:
            uid_pairs[keyword] = (before, after)
            if not retain_uids and before == after:
                findings.append({"code": "uid_not_remapped", "keyword": keyword})

    if "PixelData" in source:
        if "PixelData" not in output:
            findings.append({"code": "pixel_data_missing"})
        else:
            try:
                source_shape = list(source.pixel_array.shape)
                output_shape = list(output.pixel_array.shape)
                if source_shape != output_shape:
                    findings.append({"code": "pixel_shape_changed"})
                if not pixel_modified and _pixel_digest(source) != _pixel_digest(output):
                    findings.append({"code": "pixels_changed_without_declaration"})
            except Exception as exc:
                findings.append({"code": "pixel_decode_failed", "type": type(exc).__name__})

    if str(getattr(source, "BurnedInAnnotation", "")).upper() == "YES" and not pixel_modified:
        findings.append({"code": "burned_in_source_not_marked_pixel_modified"})
    if pixel_modified and str(getattr(output, "BurnedInAnnotation", "")).upper() == "YES":
        findings.append({"code": "burned_in_annotation_still_yes"})
    return {"passed": not findings, "findings": findings}, uid_pairs


def compare_trees(
    source_root: Path,
    output_root: Path,
    pairs: list[dict[str, Any]],
    *,
    retain_uids: bool,
    allow_private: bool,
    include_paths: bool,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    mappings: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for index, pair in enumerate(pairs, start=1):
        source_rel = str(pair["source"])
        output_rel = str(pair["output"])
        source_path = _safe_join(source_root, source_rel)
        output_path = _safe_join(output_root, output_rel)
        item: dict[str, Any] = {
            "pair": index,
            "source_path_sha256": _hash_text(source_rel),
            "output_path_sha256": _hash_text(output_rel),
        }
        if include_paths:
            item.update(source=source_rel, output=output_rel)
        if not source_path.is_file() or not output_path.is_file():
            item.update(passed=False, findings=[{"code": "paired_file_missing"}])
            results.append(item)
            continue
        comparison, uid_pairs = compare_pair(
            source_path,
            output_path,
            pixel_modified=bool(pair.get("pixel_modified", False)),
            retain_uids=retain_uids,
            allow_private=allow_private,
        )
        item.update(comparison)
        results.append(item)
        for keyword, (before, after) in uid_pairs.items():
            mappings[keyword][before].add(after)

    mapping_findings: list[dict[str, str]] = []
    for keyword, source_map in mappings.items():
        for outputs in source_map.values():
            if len(outputs) != 1:
                mapping_findings.append({"code": "inconsistent_uid_mapping", "keyword": keyword})
        flattened = [next(iter(outputs)) for outputs in source_map.values() if outputs]
        if len(flattened) != len(set(flattened)):
            mapping_findings.append({"code": "uid_mapping_collision", "keyword": keyword})

    passed = sum(1 for result in results if result.get("passed"))
    return {
        "schema_version": 1,
        "value_blind": not include_paths,
        "summary": {
            "pairs": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "uid_mapping_findings": len(mapping_findings),
        },
        "uid_mapping_findings": mapping_findings,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--retain-uids", action="store_true")
    parser.add_argument("--allow-private", action="store_true")
    parser.add_argument("--include-paths", action="store_true")
    args = parser.parse_args(argv)
    try:
        pairs = _load_pairs(args.mapping, args.source.resolve(), args.output.resolve())
        report = compare_trees(
            args.source.resolve(),
            args.output.resolve(),
            pairs,
            retain_uids=args.retain_uids,
            allow_private=args.allow_private,
            include_paths=args.include_paths,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 1 if report["summary"]["failed"] or report["summary"]["uid_mapping_findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
