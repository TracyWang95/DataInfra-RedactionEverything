"""HTML table parsing/expansion and structural recall from OCR structure.

Split out of ocr_pipeline.py (which stays the public facade): amount
value/format primitives, structural AMOUNT recall from table semantics,
form-field DOCUMENT_NUMBER recall, HTML table placement parsing and per-cell
expansion, and the chars-verified block text evidence helper
(_block_search_text) shared with entity matching.
"""
from __future__ import annotations

import html
import logging
from difflib import SequenceMatcher
from html.parser import HTMLParser

from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_payload import (
    _compact_text,
)
from app.services.vision.ocr_tuning import (
    _AMOUNT_FORMAT_ALLOWED_CHARS,
    _AMOUNT_TRAILING_ZEROS_MIN_DIGITS,
    _STANDALONE_AMOUNT_MAX_DIGITS,
    _STANDALONE_AMOUNT_MIN_DIGITS,
    _TABLE_CELL_CONFIDENCE_FACTOR,
)

logger = logging.getLogger(__name__)


def _compact_amount_candidate(text: str) -> str:
    return _compact_text(text).strip(" \t\r\n:：;；,，.。()（）[]【】$¥￥")


def _amount_digit_count(text: str) -> int:
    return sum(1 for ch in text if ch.isdigit())


def _amount_digit_signature(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _amount_value_signature(text: str) -> str:
    """Normalize display variants of the same amount for dedupe.

    This is deliberately a value-level helper, not a detector. HaS still decides
    whether text is an amount; this only prevents OCR supplements such as
    1431400 and 1431400.00 from being kept as separate findings.
    """
    raw = str(text or "")
    digits = _amount_digit_signature(raw)
    if len(digits) > _AMOUNT_TRAILING_ZEROS_MIN_DIGITS and digits.endswith("00") and any(ch in raw for ch in ".,\uff0c\uff0e"):
        return digits[:-2]
    return digits


def _is_amount_format_text(text: str) -> bool:
    """Format test: the text is one numeric value (digits plus optional
    thousands separators / decimal point / currency symbols).

    This is a literal-format judgement, like the standalone-date test: it says
    nothing about whether the number is sensitive. Semantics come from table
    structure (an amount-labelled column header).
    """
    compact = _compact_amount_candidate(text)
    if not compact or not any(ch.isdigit() for ch in compact):
        return False
    return all(ch in _AMOUNT_FORMAT_ALLOWED_CHARS for ch in compact)


def _is_standalone_amount_ocr_block(text: str) -> bool:
    """Return True when an OCR block is essentially one amount value."""
    compact = _compact_amount_candidate(text)
    if not _is_amount_format_text(compact):
        return False
    digits = _amount_digit_count(compact)
    if digits < _STANDALONE_AMOUNT_MIN_DIGITS or digits > _STANDALONE_AMOUNT_MAX_DIGITS:
        return False
    return bool(_amount_value_signature(compact))


def _parse_table_placements(table_html: str) -> list[tuple[str, int, int, int, int]]:
    """
    Parse an HTML table into cell placements with explicit row/column indices.

    Returns (cell_text, row, col, row_span, col_span) per cell, with colspan /
    rowspan occupancy resolved so the column index is the true HTML grid column.
    """
    rows: list[list[tuple[str, int, int]]] = []

    class TableCellParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_cell = False
            self.current_cell = ""
            self.current_row: list[tuple[str, int, int]] = []
            self.current_colspan = 1
            self.current_rowspan = 1

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self.current_row = []
            if tag in ("td", "th"):
                self.in_cell = True
                self.current_cell = ""
                self.current_colspan = 1
                self.current_rowspan = 1
                for k, v in attrs:
                    if k == "colspan":
                        try:
                            self.current_colspan = max(1, int(v))
                        except Exception:
                            self.current_colspan = 1
                    elif k == "rowspan":
                        try:
                            self.current_rowspan = max(1, int(v))
                        except Exception:
                            self.current_rowspan = 1

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.in_cell:
                self.in_cell = False
                cell_text = html.unescape(self.current_cell).strip()
                self.current_row.append((cell_text, self.current_colspan, self.current_rowspan))
            if tag == "tr":
                if self.current_row:
                    rows.append(self.current_row)
                self.current_row = []

        def handle_data(self, data):
            if self.in_cell:
                self.current_cell += data

    try:
        parser = TableCellParser()
        parser.feed(table_html)
        if getattr(parser, "current_row", None):
            rows.append(parser.current_row)
    except Exception as e:
        logger.warning("Failed to parse table HTML: %s", e)
        return []

    if not rows:
        return []

    placements: list[tuple[str, int, int, int, int]] = []
    occupied: set[tuple[int, int]] = set()
    for r_idx, row in enumerate(rows):
        col_idx = 0
        for cell_text, colspan, rowspan in row:
            while (r_idx, col_idx) in occupied:
                col_idx += 1
            col_span = max(1, colspan)
            row_span = max(1, rowspan)
            placements.append((cell_text, r_idx, col_idx, row_span, col_span))
            for rr in range(r_idx, r_idx + row_span):
                for cc in range(col_idx, col_idx + col_span):
                    occupied.add((rr, cc))
            col_idx += col_span

    return placements


def extract_table_cells(table_html: str, block: OCRTextBlock) -> list[OCRTextBlock]:
    """
    Parse an HTML table and create virtual OCRTextBlock per cell.

    Cell positions are estimated from row/column indices and the parent block's
    bounding box. Cells inside an amount-labelled column (header semantics +
    HTML column index) are tagged for the structural AMOUNT recall.
    """
    placements = _parse_table_placements(table_html)
    if not placements:
        return []

    num_rows = max(row + row_span for _, row, _, row_span, _ in placements)
    num_cols = max(col + col_span for _, _, col, _, col_span in placements)
    if num_rows == 0 or num_cols == 0:
        return []

    row_height = max(block.height / num_rows, 1.0)
    col_width = max(block.width / num_cols, 1.0)

    virtual_blocks: list[OCRTextBlock] = []
    for cell_text, r_idx, col_idx, row_span, col_span in placements:
        if cell_text.strip():
            cell_left = block.left + col_idx * col_width
            cell_top = block.top + r_idx * row_height
            cell_width = col_width * col_span
            cell_height = row_height * row_span

            cell_block = OCRTextBlock(
                text=cell_text,
                polygon=[
                    [cell_left, cell_top],
                    [cell_left + cell_width, cell_top],
                    [cell_left + cell_width, cell_top + cell_height],
                    [cell_left, cell_top + cell_height],
                ],
                confidence=block.confidence * _TABLE_CELL_CONFIDENCE_FACTOR,
            )
            virtual_blocks.append(cell_block)

    return virtual_blocks


def _html_to_plain_text(markup: str) -> str:
    parts: list[str] = []

    class PlainTextParser(HTMLParser):
        def handle_data(self, data):
            if data:
                parts.append(data)

    parser = PlainTextParser()
    parser.feed(markup)
    return " ".join(html.unescape(part).strip() for part in parts if part.strip()).strip()


def expand_table_blocks(ocr_blocks: list[OCRTextBlock]) -> list[OCRTextBlock]:
    """Expand HTML table blocks into per-cell blocks for cleaner NER input."""
    expanded: list[OCRTextBlock] = []
    for block in ocr_blocks:
        if block.text.startswith("<table") and "</table>" in block.text:
            cell_blocks = extract_table_cells(block.text, block)
            if cell_blocks:
                expanded.extend(cell_blocks)
                continue
            # parse failed - strip HTML tags as fallback
            plain = _html_to_plain_text(block.text)
            if plain:
                expanded.append(OCRTextBlock(
                    text=plain,
                    polygon=block.polygon,
                    confidence=block.confidence,
                ))
            else:
                expanded.append(block)
        else:
            expanded.append(block)
    return expanded


def _block_search_text(block: OCRTextBlock) -> str:
    """Authoritative text to match entities against.

    block.chars are produced together with the box geometry, so when the OCR
    service mis-pairs text labels with boxes (observed PP-StructureV3
    pathology: duplicated boxes whose `text` belongs to a different box), the
    joined char boxes still spell the box's real content. The text label is
    kept only while the chars corroborate it as the same content:

    - same glyph sequence (whitespace ignored);
    - equal glyph counts: the char-level recognizer read the same glyphs
      differently (帐号 vs 账号, 江苏省×X市 vs 江苏省XX市);
    - chars form an in-order subsequence of the text: the service dropped
      some char boxes (observed: chars 9,000.00 under text 89,000.00) —
      partial evidence of the same content, not a contradiction.

    Anything else means the chars spell different content than the label, so
    match against the chars text: a value is only ever attached to a box that
    actually contains it. The old whole-block fallback attached the lying
    text label to a box holding different pixels.
    """
    block_text = str(block.text or "")
    chars = getattr(block, "chars", None) or []
    if not chars:
        return block_text
    chars_text = "".join(str(char_box.get("c", "")) for char_box in chars)
    compact_chars = _compact_text(chars_text)
    compact_block = _compact_text(block_text)
    if compact_chars == compact_block:
        return block_text
    if len(compact_chars) == len(compact_block):
        return block_text
    corresponding_glyphs = sum(
        size
        for _block_pos, _chars_pos, size in SequenceMatcher(
            None, compact_block, compact_chars, autojunk=False
        ).get_matching_blocks()
    )
    # Most char glyphs align in order with the label -> SAME content, the char
    # recognizer merely read a few glyphs differently (rare-char variance:
    # label 洪棘颢 vs char boxes 洪棘题 / a dropped 颢). HaS matched the LABEL,
    # so keep it; switching to the divergent char text drops the entity
    # entirely (the name never gets a box). Only a WHOLESALE mismatch — the
    # duplicated-box pathology, where the chars spell UNRELATED content and
    # overlap is near zero — falls back to the char text. The two regimes sit
    # far apart (same-content overlap ~1.0 vs pathology ~0), so this majority
    # split is robust, not a tuned cut.
    if corresponding_glyphs >= len(compact_chars) * 0.5:
        return block_text
    return chars_text
