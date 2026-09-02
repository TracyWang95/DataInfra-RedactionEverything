#!/usr/bin/env python3
"""Generate deterministic non-clinical DICOM fixtures for destructive tests.

Every identifier and every visible string is intentionally fake.  These
fixtures complement, rather than replace, the pinned real-world public corpus:
they let tests assert removal of known PHI-like values and pixel text without
ever putting a real person's data in the repository.
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DESTINATION = REPO_ROOT / "backend" / "tests" / "assets" / "dicom" / "generated"
UID_ROOT = "1.2.826.0.1.3680043.10.5432"


def _font(size: int = 20) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _burned_pixels(label: str) -> np.ndarray:
    image = Image.new("L", (320, 160), color=24)
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 315, 61), fill=0, outline=255, width=1)
    draw.text((12, 10), "PATIENT: TEST PERSON", fill=255, font=_font(19))
    draw.text((12, 35), f"MRN: FAKE-{label}", fill=255, font=_font(18))
    # Non-text anatomy-like gradients exercise windowing and pixel preservation.
    for y in range(72, 156):
        value = int(30 + 190 * (y - 72) / 84)
        draw.line((4, y, 315, y), fill=value)
    return np.asarray(image, dtype=np.uint8)


def _dataset(
    *,
    patient_index: int,
    study_index: int,
    series_index: int,
    instance_index: int,
    burned_in: bool,
) -> FileDataset:
    sop_instance_uid = f"{UID_ROOT}.{patient_index}.{study_index}.{series_index}.{instance_index}"
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = f"{UID_ROOT}.99"

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = sop_instance_uid
    ds.StudyInstanceUID = f"{UID_ROOT}.{patient_index}.{study_index}"
    ds.SeriesInstanceUID = f"{UID_ROOT}.{patient_index}.{study_index}.{series_index}"
    ds.FrameOfReferenceUID = f"{UID_ROOT}.{patient_index}.{study_index}.50"
    ds.PatientName = f"TEST^PERSON{patient_index}"
    ds.PatientID = f"FAKE-MRN-{patient_index:04d}"
    ds.PatientBirthDate = "19700101"
    ds.PatientSex = "O"
    ds.AccessionNumber = f"FAKE-ACC-{study_index:04d}"
    ds.StudyID = str(study_index)
    ds.StudyDate = "20260115"
    ds.StudyTime = "120000"
    ds.SeriesDate = "20260115"
    ds.ContentDate = "20260115"
    ds.ContentTime = "120000"
    ds.ReferringPhysicianName = "TEST^DOCTOR"
    ds.PerformingPhysicianName = "TEST^RADIOLOGIST"
    ds.InstitutionName = "SYNTHETIC TEST HOSPITAL"
    ds.StationName = "FAKE-SCANNER-01"
    ds.StudyDescription = "SYNTHETIC BURNED IN TEST"
    ds.SeriesDescription = f"SYNTHETIC SERIES {series_index}"
    ds.Modality = "OT"
    ds.SeriesNumber = series_index
    ds.InstanceNumber = instance_index
    ds.ImageType = ["DERIVED", "SECONDARY"]
    ds.BurnedInAnnotation = "YES" if burned_in else "NO"
    ds.PatientIdentityRemoved = "NO"

    request = Dataset()
    request.RequestedProcedureID = f"FAKE-RP-{study_index}"
    request.ScheduledProcedureStepDescription = "TEST PERSON FOLLOWUP"
    ds.RequestAttributesSequence = Sequence([request])
    ds.add_new((0x0011, 0x0010), "LO", "SYNTHETIC_CREATOR")
    ds.add_new((0x0011, 0x1010), "LO", "FAKE PRIVATE PATIENT NOTE")

    pixels = _burned_pixels(f"{patient_index:04d}") if burned_in else np.tile(
        np.arange(320, dtype=np.uint8), (160, 1)
    )
    ds.Rows, ds.Columns = pixels.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = pixels.tobytes()
    return ds


def create_fixture_set(destination: Path, *, clean: bool = False) -> dict[str, object]:
    destination = destination.resolve()
    if clean and destination.exists():
        # Callers pass an explicit fixture directory; guard against broad removal.
        if destination.name != "generated" and not destination.name.startswith("dicom-generated-"):
            raise ValueError(f"refusing to clean unexpected directory: {destination}")
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    single = destination / "single" / "burned_in_fake.dcm"
    single.parent.mkdir(parents=True, exist_ok=True)
    _dataset(patient_index=1, study_index=1, series_index=1, instance_index=1, burned_in=True).save_as(
        single, enforce_file_format=True
    )

    batch = destination / "batch"
    cases = [
        (1, 10, 1, 1),
        (1, 10, 1, 2),
        (1, 10, 2, 1),
        (2, 20, 1, 1),
    ]
    batch_files: list[Path] = []
    for patient, study, series, instance in cases:
        path = batch / f"p{patient}" / f"study{study}" / f"series{series}" / f"i{instance}.dcm"
        path.parent.mkdir(parents=True, exist_ok=True)
        _dataset(
            patient_index=patient,
            study_index=study,
            series_index=series,
            instance_index=instance,
            burned_in=instance == 1,
        ).save_as(path, enforce_file_format=True)
        batch_files.append(path)

    malformed = destination / "malformed"
    malformed.mkdir(parents=True, exist_ok=True)
    (malformed / "not_dicom.dcm").write_bytes(b"NOT-DICOM\x00fake payload")
    source_bytes = single.read_bytes()
    (malformed / "truncated.dcm").write_bytes(source_bytes[: max(160, len(source_bytes) // 3)])
    (malformed / "empty.dcm").write_bytes(b"")

    archive = destination / "batch_inputs.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in batch_files:
            package.write(path, path.relative_to(destination).as_posix())
        package.writestr("batch/README.txt", "Synthetic fixtures only; no real patient data.\n")

    summary = {
        "synthetic_only": True,
        "single": str(single),
        "batch_files": [str(path) for path in batch_files],
        "studies": 2,
        "series": 3,
        "instances": 4,
        "archive": str(archive),
        "malformed": [str(path) for path in sorted(malformed.iterdir())],
    }
    (destination / "generation-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)
    summary = create_fixture_set(args.destination, clean=args.clean)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
