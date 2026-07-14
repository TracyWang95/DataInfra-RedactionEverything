"""幻觉卡判定的 OCR blocks 必须是"本次调用"的, 不能读进程级单例 (静默泄露修复).

_drop_page_hallucinated_cards 原来读 self.ocr_has_service.last_ocr_blocks —— 一个
进程级单例, 每次 OCR 末尾被覆盖。并发跨页/跨请求时, A 页的身份证框可能拿 B 页的
blocks 做 covers_all_text 判定 → 误判为整页幻觉 → 丢掉真身份证框 = 漏 redaction。
修法: 本次调用的 blocks 经 per-call 容器显式流转到 self._page_ocr_blocks, 判定恒对
应本页; 对单例后续改写免疫。
"""
import asyncio
import io

from PIL import Image

from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision_service import VisionService


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, "PNG")
    return buf.getvalue()


def _blk(text: str) -> OCRTextBlock:
    return OCRTextBlock(text=text, polygon=[[0, 0], [10, 0], [10, 10], [0, 10]], confidence=0.9)


class _FakeOCR:
    def __init__(self):
        self.last_ocr_blocks = []

    async def detect_and_draw(self, image_data, vision_types=None, draw_result=True, blocks_out=None):
        mine = [_blk("身份证号码：11010119900307461X")]
        self.last_ocr_blocks = list(mine)          # process-wide singleton write
        if blocks_out is not None:
            blocks_out[:] = mine                    # per-call, race-free
        return [], None


def test_page_blocks_captured_per_call():
    vs = VisionService()
    vs.ocr_has_service = _FakeOCR()
    asyncio.run(vs._detect_with_ocr_has(_png(), 1, None))
    captured = [b.text for b in (getattr(vs, "_page_ocr_blocks", []) or [])]
    assert captured == ["身份证号码：11010119900307461X"]


def test_page_blocks_immune_to_singleton_overwrite():
    vs = VisionService()
    vs.ocr_has_service = _FakeOCR()
    asyncio.run(vs._detect_with_ocr_has(_png(), 1, None))
    # a concurrent detect on another page overwrites the shared singleton
    vs.ocr_has_service.last_ocr_blocks = [_blk("OTHER PAGE 全是文字没有号码")]
    still = [b.text for b in (getattr(vs, "_page_ocr_blocks", []) or [])]
    assert still == ["身份证号码：11010119900307461X"]   # unchanged by the overwrite
