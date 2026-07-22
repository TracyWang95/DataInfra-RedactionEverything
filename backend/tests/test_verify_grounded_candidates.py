"""Model-centric verification of grounding-sourced visual boxes.

One re-ground replaces the whole pixel-gate pile. The principle: a
tile/grid/fragment pass forces the grounding model to localise its target
inside a context-rich margin crop, so a page-holding finger / red underline /
camera watermark gets boxed as a seal / fingerprint / edge-seal. Re-grounding
the box's OWN checked wording on JUST its tight crop separates them — a real
stamp still reads as itself, a context artifact returns nothing once its
borrowed context is gone. The cut is EXISTENCE (any box), never a score, so a
real signature that re-grounds at 0.16 survives. Only grounding boxes are
verified; YOLO is a separate trained detector. Errors fail OPEN.
"""
import asyncio
import io

from PIL import Image

from app.models.schemas import BoundingBox
from app.services.vision.locate_grounding import LocateAnythingGroundingService


def _box(source_detail: str, type_: str = "official_seal", *, id_: str, text: str = "公章") -> BoundingBox:
    return BoundingBox(
        id=id_, x=0.1, y=0.1, width=0.2, height=0.2, type=type_, text=text, page=1,
        confidence=0.6, source="visual_features", source_detail=source_detail,
        evidence_source="visual_feature_model",
    )


# a real white page — the re-ground result is stubbed, only the crop path
# (decode + Image.crop) must run.
def _white_png(w: int = 60, h: int = 60) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (245, 245, 245)).save(buf, "PNG")
    return buf.getvalue()


_PNG = _white_png()


def _run(coro):
    return asyncio.run(coro)


def test_drops_box_the_model_no_longer_grounds():
    """A fragment box whose re-ground returns nothing (context artifact) is dropped."""
    svc = LocateAnythingGroundingService()

    async def fake(image_data, categories, max_image_side=None):
        return []  # model finds nothing on the tight crop

    svc._post_detect = fake  # type: ignore[assignment]
    fp = _box("locate_anything:fragment_seal", id_="a")
    out = _run(svc._verify_grounded_candidates([fp], _PNG, {"official_seal": "公章"}))
    assert out == []


def test_keeps_box_the_model_reconfirms():
    """A box the model re-grounds on its own crop (n>=1) is kept."""
    svc = LocateAnythingGroundingService()

    async def fake(image_data, categories, max_image_side=None):
        return [{"x": 0.2, "y": 0.2, "width": 0.5, "height": 0.5, "confidence": 0.66}]

    svc._post_detect = fake  # type: ignore[assignment]
    fp = _box("locate_anything:detect", id_="b")
    out = _run(svc._verify_grounded_candidates([fp], _PNG, {"official_seal": "公章"}))
    assert [b.id for b in out] == ["b"]


def test_signature_is_never_verified():
    """A real name re-grounds n=0 on a tight crop yet n=1 slightly wider, so
    verifying signatures would drop a real name whose box is tight (a leak).
    Signatures skip verify and are kept — the false signatures on blank margins
    are over-mask, the safe direction."""
    svc = LocateAnythingGroundingService()

    async def boom(image_data, categories, max_image_side=None):
        raise AssertionError("a signature box must not be re-grounded")

    svc._post_detect = boom  # type: ignore[assignment]
    sig = _box("locate_anything:tile_retry", type_="signature", id_="s", text="签字")
    out = _run(svc._verify_grounded_candidates([sig], _PNG, {"signature": "handwritten signature"}))
    assert [b.id for b in out] == ["s"]


def test_fingerprint_is_verified_precision_first():
    """Fingerprints ARE re-grounded (precision-first: no pixel skin gate, so the
    verify is the model-centric filter that prunes context-artifact false prints).
    A print whose crop no longer grounds is dropped."""
    svc = LocateAnythingGroundingService()

    async def fake(image_data, categories, max_image_side=None):
        return []  # the crop no longer grounds as a fingerprint

    svc._post_detect = fake  # type: ignore[assignment]
    fp = _box("locate_anything:tile_retry", type_="fingerprint", id_="f", text="指纹")
    out = _run(svc._verify_grounded_candidates([fp], _PNG, {"fingerprint": "red inked thumbprint mark"}))
    assert out == []


def test_yolo_box_is_never_reground_and_always_kept():
    """The trained YOLO detector is precise on its own — not routed through verify."""
    svc = LocateAnythingGroundingService()

    async def boom(image_data, categories, max_image_side=None):
        raise AssertionError("YOLO box must not be re-grounded")

    svc._post_detect = boom  # type: ignore[assignment]
    yolo = _box("has_image:yolo", id_="y")
    out = _run(svc._verify_grounded_candidates([yolo], _PNG, {"official_seal": "公章"}))
    assert [b.id for b in out] == ["y"]


def test_reground_uses_checked_wording_not_a_mapping():
    """The re-ground query is the box's checked wording, carried verbatim — never
    a slug->name table (the schema the 清单 checked is what gets re-tested)."""
    svc = LocateAnythingGroundingService()
    seen: list[list[str]] = []

    async def fake(image_data, categories, max_image_side=None):
        seen.append(categories)
        return [{"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.3, "confidence": 0.5}]

    svc._post_detect = fake  # type: ignore[assignment]
    custom = _box("locate_anything:detect", type_="my_custom_stamp", id_="c", text="红头")
    _run(svc._verify_grounded_candidates([custom], _PNG, {"my_custom_stamp": "机构红头章"}))
    assert seen == [["机构红头章"]]  # the checked wording, not SLUG_TO_NAME_ZH


def test_fails_open_on_reground_error():
    """A missed redaction outranks a false one — a server error keeps the box."""
    svc = LocateAnythingGroundingService()

    async def boom(image_data, categories, max_image_side=None):
        raise RuntimeError("503")

    svc._post_detect = boom  # type: ignore[assignment]
    fp = _box("locate_anything:fragment_seal", id_="e")
    out = _run(svc._verify_grounded_candidates([fp], _PNG, {"official_seal": "公章"}))
    assert [b.id for b in out] == ["e"]
