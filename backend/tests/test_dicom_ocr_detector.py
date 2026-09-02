from __future__ import annotations

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from pydicom.dataset import Dataset

from app.services.dicom import facade
from app.services.dicom.ocr_detector import DicomOCRPixelDetector
from app.services.dicom_jobs import DicomJobService


def _dataset(*, burned_in: str | None, frames: int = 1) -> tuple[Dataset, list[np.ndarray]]:
    dataset = Dataset()
    dataset.Rows = 40
    dataset.Columns = 64
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 8
    dataset.BitsStored = 8
    dataset.HighBit = 7
    dataset.PixelRepresentation = 0
    if frames > 1:
        dataset.NumberOfFrames = str(frames)
    if burned_in is not None:
        dataset.BurnedInAnnotation = burned_in
    arrays = [np.arange(64, dtype=np.uint8)[None, :].repeat(40, axis=0) for _ in range(frames)]
    return dataset, arrays


def _region(text: str, left: int, top: int, width: int, height: int, confidence: float = 0.9):
    return SimpleNamespace(
        text=text,
        left=left,
        top=top,
        width=width,
        height=height,
        confidence=confidence,
    )


class _FakeVisionService:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self.calls = calls

    async def detect_and_draw(
        self,
        image_bytes: bytes,
        vision_types=None,
        draw_result: bool = True,
        blocks_out: list | None = None,
    ):
        call_index = len(self.calls)
        with Image.open(__import__("io").BytesIO(image_bytes)) as image:
            image_info = {"size": image.size, "mode": image.mode}
        blocks = [
            _region("PATIENT: TEST PERSON", 2, 3, 30, 6),
            _region("ANATOMY", 2, 18, 22, 5),
        ]
        if blocks_out is not None:
            blocks_out.extend(blocks)
        # This narrower semantic hit overlaps the first OCR line.  The DICOM
        # YES fallback must retain the whole line and de-duplicate this crop.
        semantic = [_region("TEST PERSON", 12, 3, 15, 6)]
        self.calls.append(
            {
                **image_info,
                "call_index": call_index,
                "vision_types": vision_types,
                "draw_result": draw_result,
                "blocks_out_supplied": blocks_out is not None,
            }
        )
        return semantic, None


def test_declared_burned_in_masks_every_ocr_block_on_every_frame_without_text_leak() -> None:
    dataset, frames = _dataset(burned_in="YES", frames=2)
    calls: list[dict[str, object]] = []
    detector = DicomOCRPixelDetector(_FakeVisionService(calls), verify_backends=False)

    result = detector.detect(dataset, frames)

    assert result.detector_name == "PaddleOCR+HaS+DICOM-fail-safe"
    assert len(calls) == 2
    assert all(call["size"] == (64, 40) for call in calls)
    assert all(call["mode"] == "L" for call in calls)
    assert all(call["draw_result"] is False for call in calls)
    assert all(call["blocks_out_supplied"] is True for call in calls)
    assert {(item.frame_index, item.x, item.y) for item in result.regions} == {
        (0, 2, 3),
        (0, 2, 18),
        (1, 2, 3),
        (1, 2, 18),
    }
    assert all(item.text == "" for item in result.regions)
    serialised = repr([asdict(item) for item in result.regions])
    assert "TEST PERSON" not in serialised
    assert "PATIENT" not in serialised


class _UnknownStatusVisionService:
    async def detect_and_draw(
        self,
        image_bytes: bytes,
        vision_types=None,
        draw_result: bool = True,
        blocks_out: list | None = None,
    ):
        del image_bytes, vision_types, draw_result
        assert blocks_out is not None
        blocks_out.extend(
            [
                _region("ANATOMY ONLY", 1, 2, 8, 4),
                _region("Patient Name: Jane Doe", 10, 8, 20, 5),
                _region("MRN: 998877", 20, 16, 18, 5),
                _region("病历号：A001", 30, 24, 18, 5),
            ]
        )
        return [_region("semantic finding", 45, 30, 12, 5)], None


def test_unknown_burned_in_status_adds_dicom_label_lines_but_not_unrelated_ocr() -> None:
    dataset, frames = _dataset(burned_in=None)
    detector = DicomOCRPixelDetector(_UnknownStatusVisionService(), verify_backends=False)

    # Exercise direct synchronous core use while an event loop is running.
    async def invoke():
        return detector.detect(dataset, frames)

    result = asyncio.run(invoke())

    assert {(item.x, item.y) for item in result.regions} == {
        (10, 8),
        (20, 16),
        (30, 24),
        (45, 30),
    }
    assert all(item.text == "" for item in result.regions)


def test_detector_fails_closed_when_gpu_backend_is_offline() -> None:
    class _Health:
        def __init__(self, online: bool) -> None:
            self.online = online

        def is_available(self) -> bool:
            return self.online

    service = SimpleNamespace(_ocr_service=_Health(False), _has_client=_Health(True))
    dataset, frames = _dataset(burned_in="NO")
    detector = DicomOCRPixelDetector(service)

    with pytest.raises(RuntimeError, match="offline"):
        detector.detect(dataset, frames)


def test_server_core_options_force_pixel_detection_and_cleaning_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DICOM_PIXEL_OCR_ENABLED", raising=False)
    service = object.__new__(DicomJobService)

    options = service._core_options(
        "doctor-tenant",
        {"pixel_ocr_required": False, "clean_pixel_data": False},
    )

    assert options["pixel_ocr_required"] is True
    assert options["clean_pixel_data"] is True
    assert options["mapping_namespace"].startswith("tenant-")


def test_server_pixel_detection_can_be_disabled_only_by_deployment_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DICOM_PIXEL_OCR_ENABLED", "false")
    service = object.__new__(DicomJobService)

    options = service._core_options("doctor-tenant", {"clean_pixel_data": False})

    assert options["pixel_ocr_required"] is False
    assert options["clean_pixel_data"] is False


def test_facade_supplies_detector_to_preflight_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    captured: dict[str, object] = {}

    class _Preflight:
        def model_dump(self, mode: str):
            assert mode == "json"
            return {"status": "ready", "risks": []}

    def fake_run(paths, *, profile, options, detector):
        captured.update(paths=paths, profile=profile, options=options, detector=detector)
        return _Preflight(), {}, object()

    monkeypatch.setattr(facade, "get_dicom_ocr_pixel_detector", lambda: sentinel)
    monkeypatch.setattr(facade, "_run_preflight", fake_run)

    result = facade.preflight_study(
        ["source.dcm"],
        profile="research_strict",
        options={"pixel_ocr_required": True, "clean_pixel_data": True},
    )

    assert result["status"] == "ready"
    assert captured["detector"] is sentinel
    assert captured["options"]["pixel_ocr_required"] is True
    assert captured["options"]["clean_pixel_data"] is True
    assert captured["options"]["require_decodable_pixel_data"] is True
