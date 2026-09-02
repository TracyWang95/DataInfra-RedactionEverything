#!/usr/bin/env python3
"""Validate DICOM inputs with pydicom plus any available independent tools.

The JSON report is deliberately value-blind: it records whether identifying
attributes exist, never their values.  This makes reports safe to attach to CI
artifacts even when the input corpus is supplied by a hospital under a DUA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

try:
    import pydicom
    from pydicom.errors import InvalidDicomError
    from pydicom.uid import ExplicitVRBigEndian, ExplicitVRLittleEndian, ImplicitVRLittleEndian
except ImportError as exc:  # pragma: no cover - CLI gives a direct installation hint
    raise SystemExit("pydicom is required: python -m pip install pydicom") from exc

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "backend" / "tests" / "assets" / "dicom"
DEFAULT_MANIFEST = ASSET_ROOT / "manifest.json"
DEFAULT_INPUT = ASSET_ROOT / "cache"

DIRECT_IDENTIFIER_KEYWORDS = (
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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return any(_nonempty(item) for item in value)
    return bool(str(value).strip())


def _safe_int(value: Any, default: int = 0) -> tuple[int, bool]:
    try:
        return int(value), True
    except (TypeError, ValueError):
        return default, False


def _sequence_depth(dataset: Any, depth: int = 0) -> int:
    maximum = depth
    for element in dataset:
        if element.VR != "SQ":
            continue
        maximum = max(maximum, depth + 1)
        for item in element.value or []:
            maximum = max(maximum, _sequence_depth(item, depth + 1))
    return maximum


def _iter_elements(dataset: Any) -> Iterable[Any]:
    for element in dataset:
        yield element
        if element.VR == "SQ":
            for item in element.value or []:
                yield from _iter_elements(item)


def _find_binary(name: str, environment_name: str) -> str | None:
    configured = os.environ.get(environment_name)
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which(name)
    if found:
        return found
    patterns = (
        f"tmp/dicom-tools/**/{name}.exe",
        f"tmp/dcmtk-portable/**/{name}.exe",
    )
    for pattern in patterns:
        match = next(REPO_ROOT.glob(pattern), None)
        if match and match.is_file():
            return str(match)
    return None


def available_independent_tools() -> dict[str, str]:
    candidates = {
        "dcmtk_dcmdump": _find_binary("dcmdump", "DCMDUMP_PATH"),
        "gdcm_gdcminfo": _find_binary("gdcminfo", "GDCMINFO_PATH"),
        "dicom3tools_dciodvfy": _find_binary("dciodvfy", "DCIODVFY_PATH"),
    }
    return {name: path for name, path in candidates.items() if path}


def _external_command(tool: str, binary: str, path: Path) -> list[str]:
    if tool == "dcmtk_dcmdump":
        return [binary, "--load-short", str(path)]
    return [binary, str(path)]


def run_independent_tools(path: Path, *, timeout: float = 30.0) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for tool, binary in available_independent_tools().items():
        started = time.monotonic()
        try:
            completed = subprocess.run(
                _external_command(tool, binary, path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
            combined = completed.stdout + b"\0" + completed.stderr
            results[tool] = {
                "available": True,
                "success": completed.returncode == 0,
                "returncode": completed.returncode,
                "diagnostic_sha256": sha256_bytes(combined),
                "stdout_bytes": len(completed.stdout),
                "stderr_bytes": len(completed.stderr),
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            }
        except subprocess.TimeoutExpired:
            results[tool] = {
                "available": True,
                "success": False,
                "timeout": True,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            }
        except OSError as exc:
            results[tool] = {
                "available": True,
                "success": False,
                "error_type": type(exc).__name__,
            }
    return results


def inspect_file(
    path: Path,
    *,
    relative_to: Path | None = None,
    decode_pixels: bool = False,
    independent: bool = False,
    force_fallback: bool = True,
) -> dict[str, Any]:
    raw_size = path.stat().st_size
    result: dict[str, Any] = {
        "path": path.relative_to(relative_to).as_posix() if relative_to else path.name,
        "bytes": raw_size,
        "sha256": sha256_file(path),
        "has_dicm_prefix": False,
        "readable": False,
        "forced_read": False,
    }
    if raw_size >= 132:
        with path.open("rb") as stream:
            stream.seek(128)
            result["has_dicm_prefix"] = stream.read(4) == b"DICM"

    dataset = None
    try:
        dataset = pydicom.dcmread(path, stop_before_pixels=not decode_pixels)
    except InvalidDicomError:
        if force_fallback:
            try:
                dataset = pydicom.dcmread(path, force=True, stop_before_pixels=not decode_pixels)
                result["forced_read"] = True
            except Exception as exc:  # malformed corpus cases intentionally reach this boundary
                result["read_error_type"] = type(exc).__name__
        else:
            result["read_error_type"] = "InvalidDicomError"
    except Exception as exc:
        result["read_error_type"] = type(exc).__name__

    if dataset is not None:
        result["readable"] = True
        file_meta = getattr(dataset, "file_meta", None)
        frames, frames_valid = _safe_int(getattr(dataset, "NumberOfFrames", 1) or 1, 1)
        rows, rows_valid = _safe_int(getattr(dataset, "Rows", 0) or 0)
        columns, columns_valid = _safe_int(getattr(dataset, "Columns", 0) or 0)
        result.update(
            {
                "modality": str(getattr(dataset, "Modality", "")),
                "transfer_syntax": str(getattr(file_meta, "TransferSyntaxUID", "")),
                "sop_class_uid_present": _nonempty(getattr(dataset, "SOPClassUID", None)),
                "sop_instance_uid_present": _nonempty(getattr(dataset, "SOPInstanceUID", None)),
                "study_instance_uid_present": _nonempty(getattr(dataset, "StudyInstanceUID", None)),
                "series_instance_uid_present": _nonempty(getattr(dataset, "SeriesInstanceUID", None)),
                "frames": frames,
                "rows": rows,
                "columns": columns,
                "numeric_fields_valid": frames_valid and rows_valid and columns_valid,
                "burned_in_annotation": str(getattr(dataset, "BurnedInAnnotation", "")),
                "patient_identity_removed": str(getattr(dataset, "PatientIdentityRemoved", "")),
                "deidentification_method_present": _nonempty(getattr(dataset, "DeidentificationMethod", None))
                or _nonempty(getattr(dataset, "DeidentificationMethodCodeSequence", None)),
            }
        )
        try:
            elements = list(_iter_elements(dataset))
        except Exception as exc:
            # ``force=True`` can manufacture a Dataset from arbitrary bytes.
            # Materialising its raw elements is therefore part of validation,
            # and failure must be reported rather than crash the validator.
            result["dataset_validation_error_type"] = type(exc).__name__
            result["structured"] = {
                "element_count_recursive": 0,
                "sequence_depth": 0,
                "private_element_count": 0,
                "overlay_element_count": 0,
                "structured_report_content_present": False,
                "encapsulated_document_present": False,
                "identifier_presence": {keyword: False for keyword in DIRECT_IDENTIFIER_KEYWORDS},
            }
            result["pixel"] = {"present": False, "decoded": False}
            if independent:
                result["independent_tools"] = run_independent_tools(path)
            return result
        result["structured"] = {
            "element_count_recursive": len(elements),
            "sequence_depth": _sequence_depth(dataset),
            "private_element_count": sum(1 for element in elements if element.tag.is_private),
            "overlay_element_count": sum(1 for element in elements if 0x6000 <= element.tag.group <= 0x60FF),
            "structured_report_content_present": "ContentSequence" in dataset,
            "encapsulated_document_present": "EncapsulatedDocument" in dataset,
            "identifier_presence": {
                keyword: _nonempty(getattr(dataset, keyword, None)) for keyword in DIRECT_IDENTIFIER_KEYWORDS
            },
        }
        if (
            result["forced_read"]
            and not getattr(file_meta, "TransferSyntaxUID", None)
            and result["sop_class_uid_present"]
            and result["sop_instance_uid_present"]
        ):
            if dataset.is_little_endian and dataset.is_implicit_VR:
                file_meta.TransferSyntaxUID = ImplicitVRLittleEndian
            elif dataset.is_little_endian:
                file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            else:
                file_meta.TransferSyntaxUID = ExplicitVRBigEndian
            result["transfer_syntax_inferred_for_pixel_decode"] = str(file_meta.TransferSyntaxUID)
        if decode_pixels and "PixelData" in dataset:
            try:
                array = dataset.pixel_array
                result["pixel"] = {
                    "present": True,
                    "decoded": True,
                    "shape": list(array.shape),
                    "dtype": str(array.dtype),
                    "decoded_sha256": sha256_bytes(array.tobytes()),
                }
            except Exception as exc:
                result["pixel"] = {
                    "present": True,
                    "decoded": False,
                    "error_type": type(exc).__name__,
                }
        else:
            result["pixel"] = {"present": "PixelData" in dataset, "decoded": False}

    if independent:
        result["independent_tools"] = run_independent_tools(path)
    return result


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def discover_inputs(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob("*") if path.is_file() and not path.name.endswith(".json"))


def validate_manifest_corpus(
    root: Path,
    manifest: dict[str, Any],
    *,
    decode_pixels: bool,
    independent: bool,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    missing: list[str] = []
    mismatched: list[str] = []
    expected_valid_failures: list[str] = []
    unexpected_anomaly_successes: list[str] = []
    for sample in manifest["samples"]:
        path = root / sample["path"]
        if not path.is_file():
            missing.append(sample["id"])
            continue
        inspected = inspect_file(
            path,
            relative_to=root,
            decode_pixels=decode_pixels and "pixel" in sample.get("features", []),
            independent=independent,
        )
        inspected["sample_id"] = sample["id"]
        inspected["category"] = sample["category"]
        if inspected["bytes"] != sample["bytes"] or inspected["sha256"] != sample["sha256"]:
            mismatched.append(sample["id"])
        if sample["category"].startswith("valid") and not inspected["readable"]:
            expected_valid_failures.append(sample["id"])
        if sample["category"] == "known-anomaly" and inspected["readable"]:
            unexpected_anomaly_successes.append(sample["id"])
        results.append(inspected)

    tool_counts: Counter[str] = Counter()
    tool_failures: Counter[str] = Counter()
    for item in results:
        for name, status in item.get("independent_tools", {}).items():
            tool_counts[name] += 1
            # Malformed fixtures exist to prove rejection behavior; an
            # independent parser rejecting them is an expected success.
            if item.get("category", "").startswith("valid") and not status.get("success"):
                tool_failures[name] += 1
    return {
        "schema_version": 1,
        "input_root": str(root),
        "manifest_updated": manifest.get("updated"),
        "summary": {
            "manifest_samples": len(manifest["samples"]),
            "validated_samples": len(results),
            "missing_samples": len(missing),
            "hash_or_size_mismatches": len(mismatched),
            "valid_read_failures": len(expected_valid_failures),
            "known_anomalies_readable": len(unexpected_anomaly_successes),
            "modalities": dict(Counter(item.get("modality") or "unknown" for item in results)),
            "independent_tool_runs": dict(tool_counts),
            "independent_tool_failures": dict(tool_failures),
        },
        "missing": missing,
        "mismatched": mismatched,
        "valid_read_failures": expected_valid_failures,
        "known_anomalies_readable": unexpected_anomaly_successes,
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--decode-pixels", action="store_true")
    parser.add_argument("--independent", action="store_true")
    parser.add_argument("--require-independent", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest(args.manifest)
    report = validate_manifest_corpus(
        args.input.resolve(),
        manifest,
        decode_pixels=args.decode_pixels,
        independent=args.independent or args.require_independent,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))

    summary = report["summary"]
    failed = bool(summary["hash_or_size_mismatches"] or summary["valid_read_failures"])
    if summary["missing_samples"] and not args.allow_missing:
        failed = True
    if args.require_independent:
        tools = summary["independent_tool_runs"]
        failed = failed or not tools or bool(summary["independent_tool_failures"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
