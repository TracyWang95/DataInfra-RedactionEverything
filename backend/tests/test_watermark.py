"""W2-1 成品水印：图像/PDF 输出可选叠加半透明文案（默认关闭）。"""
from __future__ import annotations

import fitz
import pytest
from PIL import Image

from app.services.redaction.watermark import apply_watermark


def _make_png(path, size=(400, 300), color=(255, 255, 255)):
    Image.new("RGB", size, color).save(path)


def test_png_watermark_changes_pixels(tmp_path):
    p = tmp_path / "out.png"
    _make_png(p)
    before = list(Image.open(p).convert("RGB").getdata())
    assert apply_watermark(str(p), "仅供测试项目使用") is True
    img = Image.open(p)
    assert img.size == (400, 300)
    after = list(img.convert("RGB").getdata())
    assert before != after, "watermark must visibly alter the image"


def test_jpeg_watermark_keeps_format(tmp_path):
    p = tmp_path / "out.jpg"
    Image.new("RGB", (300, 200), (250, 250, 250)).save(p, quality=92)
    assert apply_watermark(str(p), "内部资料") is True
    img = Image.open(p)
    assert img.format == "JPEG" and img.size == (300, 200)


def test_multipage_tiff_keeps_all_frames(tmp_path):
    p = tmp_path / "out.tiff"
    frames = [Image.new("RGB", (200, 150), (255, 255, 255)) for _ in range(3)]
    frames[0].save(p, save_all=True, append_images=frames[1:])
    assert apply_watermark(str(p), "仅供演示") is True
    img = Image.open(p)
    assert getattr(img, "n_frames", 1) == 3, "multi-page tiff must keep every page"


def test_pdf_watermark_text_extractable(tmp_path):
    p = tmp_path / "out.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    doc.save(str(p))
    doc.close()
    assert apply_watermark(str(p), "仅供某某项目使用") is True
    doc = fitz.open(str(p))
    for page in doc:
        assert "仅供某某项目使用" in page.get_text()
    doc.close()


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_text_is_noop(tmp_path, text):
    p = tmp_path / "out.png"
    _make_png(p)
    before = p.read_bytes()
    assert apply_watermark(str(p), text) is False
    assert p.read_bytes() == before


def test_unsupported_extension_is_noop(tmp_path):
    p = tmp_path / "out.txt"
    p.write_text("hello")
    assert apply_watermark(str(p), "水印") is False
    assert p.read_text() == "hello"
