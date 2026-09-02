from __future__ import annotations

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from app.services.dicom.errors import DicomPixelDecodeError
from app.services.dicom.pixel import PixelRegion, redact_pixel_regions


def _color_dataset(path, pixels: np.ndarray) -> FileDataset:
    sop_uid = generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    dataset.SOPClassUID = SecondaryCaptureImageStorage
    dataset.SOPInstanceUID = sop_uid
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.Modality = "OT"
    dataset.Rows = pixels.shape[0]
    dataset.Columns = pixels.shape[1]
    dataset.SamplesPerPixel = 3
    dataset.PhotometricInterpretation = "RGB"
    dataset.PlanarConfiguration = 0
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    dataset.PixelData = np.ascontiguousarray(pixels).tobytes()
    return dataset


def test_color_redaction_clips_padded_region_and_preserves_outside_pixels(tmp_path) -> None:
    source_pixels = np.arange(6 * 8 * 3, dtype=np.uint8).reshape(6, 8, 3)
    dataset = _color_dataset(tmp_path / "rgb.dcm", source_pixels)
    sop_uid = dataset.SOPInstanceUID

    count = redact_pixel_regions(
        dataset,
        [PixelRegion(frame_index=0, x=-1, y=1, width=3, height=2)],
        padding=1,
        source_path=tmp_path / "rgb.dcm",
    )

    assert count == 1
    assert dataset.SOPInstanceUID == sop_uid
    assert dataset.PhotometricInterpretation == "RGB"
    assert dataset.PlanarConfiguration == 0
    output_pixels = np.asarray(dataset.pixel_array)
    mask = np.zeros(source_pixels.shape[:2], dtype=bool)
    mask[0:4, 0:3] = True
    assert np.all(output_pixels[mask] == 0)
    np.testing.assert_array_equal(output_pixels[~mask], source_pixels[~mask])


def test_monochrome1_redaction_uses_display_black_and_rejects_invalid_frame(tmp_path) -> None:
    pixels = np.arange(30, dtype=np.uint16).reshape(5, 6)
    dataset = _color_dataset(tmp_path / "mono.dcm", np.zeros((5, 6, 3), dtype=np.uint8))
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME1"
    del dataset.PlanarConfiguration
    dataset.BitsAllocated = 16
    dataset.BitsStored = 12
    dataset.HighBit = 11
    dataset.PixelData = pixels.tobytes()

    with pytest.raises(DicomPixelDecodeError):
        redact_pixel_regions(
            dataset,
            [PixelRegion(frame_index=1, x=0, y=0, width=2, height=2)],
            padding=0,
        )

    count = redact_pixel_regions(
        dataset,
        [PixelRegion(frame_index=0, x=2, y=1, width=2, height=3)],
        padding=0,
    )
    assert count == 1
    output_pixels = np.asarray(dataset.pixel_array)
    assert np.all(output_pixels[1:4, 2:4] == 4095)
    outside = np.ones(pixels.shape, dtype=bool)
    outside[1:4, 2:4] = False
    np.testing.assert_array_equal(output_pixels[outside], pixels[outside])


def test_written_color_dataset_round_trips_after_redaction(tmp_path) -> None:
    path = tmp_path / "rgb-roundtrip.dcm"
    source_pixels = np.full((4, 5, 3), 127, dtype=np.uint8)
    dataset = _color_dataset(path, source_pixels)
    redact_pixel_regions(
        dataset,
        [PixelRegion(frame_index=0, x=1, y=1, width=2, height=2)],
        padding=0,
        source_path=path,
    )
    dataset.save_as(path, enforce_file_format=True)

    output = pydicom.dcmread(path)
    assert output.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian
    assert output.pixel_array.shape == source_pixels.shape
    assert np.all(output.pixel_array[1:3, 1:3] == 0)
