"""Fixed + user-defined visual labels flow through ONE detect path.

detect_categories fans out one LA call per target and tags each box by the
REQUESTED target, not LA's echoed category — so a fixed slug keeps its slug and a
custom (possibly 中文) label keeps its own type_id, without any normalize/filter
step that would strip a non-ASCII tag. The LA-server half (dropping the /detect
fixed-slug filter) is verified on deploy.
"""
import asyncio
import io
from types import SimpleNamespace

from PIL import Image

from app.core.visual_feature_categories import DEFAULT_VISUAL_FEATURE_SLUGS
from app.services.vision.locate_grounding import (
    LocateAnythingGroundingService,
    _detect_requests,
)


def _pt(id: str, name: str = "") -> SimpleNamespace:
    return SimpleNamespace(id=id, name=name)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_detect_requests_fixed_and_custom() -> None:
    reqs, fixed = _detect_requests([
        _pt("fingerprint"),
        _pt("custom_visual_features_shouyin", "红色手印"),
        _pt("official_seal"),
    ])
    # fixed: sent as slug, tagged by slug, named by SLUG_TO_NAME_ZH
    # custom: sent as its human label verbatim, tagged by its own type_id
    assert reqs == [
        ("fingerprint", "fingerprint", "指纹"),
        ("红色手印", "custom_visual_features_shouyin", "红色手印"),
        ("official_seal", "official_seal", "公章"),
    ]
    assert fixed == ["fingerprint", "official_seal"]


def test_detect_requests_none_is_all_fixed() -> None:
    reqs, fixed = _detect_requests(None)
    assert fixed == list(DEFAULT_VISUAL_FEATURE_SLUGS)
    assert all(tag == rtype for tag, rtype, _text in reqs)  # fixed: tag == type


def test_detect_requests_custom_falls_back_to_slug_label() -> None:
    reqs, fixed = _detect_requests([_pt("custom_visual_features_red_stamp", "")])
    assert reqs == [("red stamp", "custom_visual_features_red_stamp", "red stamp")]
    assert fixed == []


def test_detect_requests_dedups_and_ignores_unknown() -> None:
    reqs, fixed = _detect_requests([_pt("signature"), _pt("signature"), _pt("banana")])
    assert fixed == ["signature"]  # deduped; "banana" is neither fixed nor custom
    assert [r[1] for r in reqs] == ["signature"]


def test_detect_categories_tags_by_request_not_echo() -> None:
    # LA echoes a lossy "object" category; both a fixed slug and a 中文 custom
    # label must still come back tagged by what we REQUESTED. "face" avoids the
    # seal/YOLO/tile supplements so this isolates the core detect path.
    svc = LocateAnythingGroundingService()

    async def fake_post(image_data, categories):
        (tag,) = categories
        return [{"x": 0.1, "y": 0.2, "width": 0.2, "height": 0.05,
                 "category": "object", "confidence": 0.7}]

    svc._post_detect = fake_post  # type: ignore[method-assign]
    types = [_pt("face"), _pt("custom_visual_features_shouyin", "红色手印")]
    boxes, _timings = asyncio.run(svc.detect_categories(_png(), 1, types))

    by_type = {b.type: b for b in boxes}
    assert by_type["face"].text == "人脸"
    assert by_type["custom_visual_features_shouyin"].text == "红色手印"
    assert by_type["custom_visual_features_shouyin"].source_detail == "locate_anything:detect"
