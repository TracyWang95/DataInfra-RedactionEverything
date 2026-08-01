"""整页误判身份证过滤 (立案告知书实证: 放大后LA把整页文书ground成id_card 5/5).

谓词纯几何+既有词表/正则,零调参: id_card视觉框(归一化)覆盖全页OCR文本(OCR
像素hull⊆框)且框内OCR无身份证卡面证据(卡面专有词 OR 既有18位号正则)→整页
幻觉drop。真身份证(卡面词/号可读)逃逸保留。失效方向: 任一逃逸命中即保留(不漏真卡)。
"""
from app.models.entity_schemas import BoundingBox
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision_service import VisionService

PAGE = (700, 900)


def _box(btype, x, y, w, h, src="visual_features"):
    return BoundingBox(id=f"b_{btype}_{x}", x=x, y=y, width=w, height=h, type=btype,
        text=btype, page=1, confidence=0.88, source=src,
        source_detail="locate_anything:detect", evidence_source="visual_feature_model")


def _blk(text, left, top, w=100, h=20):
    return OCRTextBlock(text=text, polygon=[[left,top],[left+w,top],[left+w,top+h],[left,top+h]], confidence=0.95)


def _ocr_box(x, y, w, h, text):
    return BoundingBox(id=f"ocr_{x}_{y}", x=x, y=y, width=w, height=h, type="id_card",
        text=text, page=1, confidence=0.95, source="ocr_has",
        source_detail="pdf_text_layer", evidence_source="ocr_has")


def _ocr_typed(x, y, w, h, type_, text):
    return BoundingBox(id=f"t_{x}_{y}", x=x, y=y, width=w, height=h, type=type_,
        text=text, page=1, confidence=0.95, source="ocr_has",
        source_detail="text_match", evidence_source="ocr_has")


def _drop(boxes, blocks):
    return VisionService()._drop_page_hallucinated_cards(boxes, blocks, PAGE)


def test_full_page_hallucination_dropped():
    card = _box("id_card", 0.0, 0.0, 1.0, 1.0)
    blocks = [_blk("立案告知书", 100, 40), _blk("本告知书已收到", 66, 338), _blk("办案人", 87, 450)]
    assert _drop([card], blocks) == []


def test_real_card_with_face_words_kept():
    card = _box("id_card", 0.0, 0.0, 1.0, 1.0)
    blocks = [_blk("居民身份证 公民身份号码", 120, 200), _blk("签发机关 有效期限", 120, 260)]
    assert len(_drop([card], blocks)) == 1


def test_card_with_18_digit_number_kept_even_if_words_blurred():
    card = _box("id_card", 0.0, 0.0, 1.0, 1.0)
    blocks = [_blk("模糊不清的文字", 100, 100), _blk("11010119900307461X", 150, 300)]
    assert len(_drop([card], blocks)) == 1


def test_card_not_covering_all_text_kept():
    card = _box("id_card", 0.1, 0.1, 0.3, 0.2)  # px (70,90,210,180)
    blocks = [_blk("标题", 100, 40), _blk("很远的文字", 100, 700)]
    assert len(_drop([card], blocks)) == 1


def test_no_ocr_blocks_keeps_card():
    card = _box("id_card", 0.0, 0.0, 1.0, 1.0)
    assert len(_drop([card], [])) == 1


def test_non_idcard_untouched():
    seal = _box("official_seal", 0.0, 0.0, 1.0, 1.0)
    assert _drop([seal], [_blk("x", 1, 1)]) == [seal]


def test_card_enclosing_seal_dropped_even_if_footer_clipped():
    # 立案告知书实证: card box covers 95% but clips footer OCR; a real 身份证
    # never encloses a 公章 -> the seal-containment identity drops it
    card = _box("id_card", 0.076, 0.045, 0.849, 0.807)  # clips bottom footer
    seal = _box("official_seal", 0.5, 0.4, 0.2, 0.15)   # inside the card box
    blocks = [_blk("立案告知书", 100, 40), _blk("一式两份一份附卷", 36, 560)]  # footer at y560 > card bottom
    out = _drop([card, seal], blocks)
    assert [b.type for b in out] == ["official_seal"]  # card dropped, seal kept


def test_real_card_with_seal_nearby_but_face_words_kept():
    # a card that has face evidence is kept regardless of any seal geometry
    card = _box("id_card", 0.0, 0.0, 1.0, 1.0)
    seal = _box("official_seal", 0.5, 0.5, 0.1, 0.1)
    blocks = [_blk("居民身份证 公民身份号码 11010119900307461X", 120, 200)]
    out = _drop([card, seal], blocks)
    assert any(b.type == "id_card" for b in out)


def test_textline_idcard_number_covered_elsewhere_dropped():
    # 图片_20260714 保姆合同: LA grounds the "身份证号码：…" form row as id_card.
    # 保覆盖门禁: only drop it because the SAME id number is already carried by a
    # retained ocr_has box overlapping the region — so the number stays masked.
    card = _box("id_card", 0.357, 0.178, 0.286, 0.033)  # px [250,160,450,190]
    blocks = [_blk("身份证号码：11010119900307461X", 250, 160, w=200, h=30)]  # center inside card
    ocr = _ocr_box(0.357, 0.178, 0.286, 0.033, "11010119900307461X")       # covers the number
    out = _drop([card, ocr], blocks)
    assert [b.source for b in out] == ["ocr_has"]  # LA card dropped, OCR number kept


def test_textline_idcard_number_not_covered_kept():
    # Same wide id_card ground, but NOTHING else covers the number. A wide aspect
    # alone must NOT drop it — dropping an uncovered number is a leak. Keep it.
    card = _box("id_card", 0.357, 0.178, 0.286, 0.033)
    blocks = [_blk("身份证号码：11010119900307461X", 250, 160, w=200, h=30)]
    assert _drop([card], blocks) == [card]


def test_handwritten_idcard_dropped_when_ocr_typed_it_idcard():
    # 保姆合同: LA grounds the handwritten 身份证号 region as id_card. The digits
    # OCR as '4102/1989010…' (a slash — NOT a clean 18-digit), so the number-parse
    # gate cannot confirm coverage; but the text channel already TYPED the region
    # ID_CARD and masks it. No card face -> the visual card is redundant, drop it.
    card = _box("id_card", 0.68, 0.19, 0.22, 0.04)
    blocks = [_blk("4102/1989010 31424", 480, 150, w=160, h=28)]  # handwritten, unparseable
    ocr = _ocr_typed(0.68, 0.19, 0.20, 0.04, "ID_CARD", "4102/1989010")
    out = _drop([card, ocr], blocks)
    assert [b.source for b in out] == ["ocr_has"]  # visual card dropped, OCR ID_CARD kept


def test_handwritten_idcard_kept_when_no_ocr_idcard_covers_it():
    # Same unparseable handwritten number but NOTHING covers it (no ocr_has ID_CARD)
    # -> dropping would leak. Keep the visual card.
    card = _box("id_card", 0.68, 0.19, 0.22, 0.04)
    blocks = [_blk("4102/1989010 31424", 480, 150, w=160, h=28)]
    assert _drop([card], blocks) == [card]


def test_idcard_with_face_words_inside_kept_even_if_number_covered():
    # A genuine card face: its 二代证 face words sit inside the box, so even
    # though the number is separately masked, dropping the box would uncover the
    # name/photo. Real-card protection keeps it.
    card = _box("id_card", 0.30, 0.20, 0.40, 0.30)  # px [210,180,490,450]
    blocks = [_blk("居民身份证 公民身份号码 11010119900307461X", 220, 220, w=250, h=40)]
    ocr = _ocr_box(0.32, 0.24, 0.30, 0.05, "11010119900307461X")
    out = _drop([card, ocr], blocks)
    assert any(b.source == "visual_features" and b.type == "id_card" for b in out)
