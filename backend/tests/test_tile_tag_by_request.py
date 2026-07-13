"""tile 框按请求打标, 永不解析 echo (contract19 实证: 查询词≠slug 时 tile 全灭).

_detect_on_tiles 每 tile 只带一个查询(该 slug 的清单措辞), 响应框按构造属于
该 slug。旧 echo 校验拿服务器归一化的查询措辞与 slug 比较——query==slug 时是
恒真式, 清单措辞分化后("handwritten name signature"/"red inked thumbprint
mark")把这些类型的 tile 框全部静默吞掉(历史日志 'fingerprint,qr_code kept
0/6 纯浪费' 的真相)。
"""
import asyncio

from app.services.vision.locate_grounding import LocateAnythingGroundingService


def test_tile_boxes_tagged_by_request_not_echo(monkeypatch):
    async def fake_post(self, image_data, categories):
        # server contract: category echoes the normalized QUERY WORDING
        return [{"category": categories[0].lower(), "x": 0.2, "y": 0.3, "width": 0.3, "height": 0.2, "confidence": 0.82}]

    monkeypatch.setattr(LocateAnythingGroundingService, "_post_detect", fake_post)
    svc = LocateAnythingGroundingService()
    boxes = asyncio.run(svc._detect_on_tiles(
        _tiny_jpeg(), 1, ["signature"], queries={"signature": "handwritten name signature"},
    ))
    assert boxes, "boxes must survive even though echo != slug"
    assert all(b.type == "signature" for b in boxes)


def _tiny_jpeg() -> bytes:
    import io

    from PIL import Image

    img = Image.new("RGB", (400, 500), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()
