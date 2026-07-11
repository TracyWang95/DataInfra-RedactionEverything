"""OCR pipeline tuning constants and semantic vocabulary.

Split out of ocr_pipeline.py (which stays the public facade): the thresholds,
ratios and vocabulary tables shared by the pipeline stage modules.
"""
from __future__ import annotations

from app.core.visual_feature_categories import VISUAL_ONLY_ENTITY_TYPES

TABLE_PRECISION_ENTITY_TYPES = {
    "AMOUNT",
    "BANK_ACCOUNT",
    "ACCOUNT_NUMBER",
    "BANK_CARD",
    "COMPANY_CODE",
    "CONTRACT_NO",
}

OCR_VISUAL_ENTITY_TYPES = VISUAL_ONLY_ENTITY_TYPES

# --- Tuning constants (extracted magic numbers) -------------------------------
# Window (seconds) for treating a recent negative HaS health check as still valid.
_HAS_NEGATIVE_HEALTH_TTL_SEC = 5.0


# Standalone-amount digit-count bounds.
_STANDALONE_AMOUNT_MIN_DIGITS = 4
_STANDALONE_AMOUNT_MAX_DIGITS = 14
# Probable amount-token digit-count bounds (with/without thousands separators).
# An amount value signature drops a trailing ".00"; require more than this many digits first.
_AMOUNT_TRAILING_ZEROS_MIN_DIGITS = 2

# Visual-row grouping tolerance: fraction of median block height, with a floor.
# Amount-table column detection needs at least this many cells in a header row.
# Horizontal padding around an amount column header: fraction of header width, with a floor.
# Slack (px) below a header baseline when testing column membership.
# Person form-field value visual-unit bounds and label-proximity tuning.
# Loose person-form expansion: max trailing-suffix length to treat as same value.
# Quality scoring weights for person form-field candidate ranking.
# Drop a person candidate whose block overlaps an already-selected block by this ratio.
# Visual-line same-line tests.
_SAME_LINE_VERTICAL_OVERLAP_RATIO = 0.35
_SAME_LINE_CENTER_HEIGHT_RATIO = 0.65
# Visual-line join gap cap: max(floor px, typical height * multiplier).
_VISUAL_LINE_JOIN_GAP_MIN_PX = 28
_VISUAL_LINE_JOIN_GAP_HEIGHT_MULT = 3.2
# Short-CJK-prefix bridging bounds.
_BRIDGE_LEFT_MIN_LEN = 2
_BRIDGE_LEFT_MAX_LEN = 6
_BRIDGE_RIGHT_MIN_LEN = 4
_BRIDGE_RIGHT_MAX_LEN = 24
_BRIDGE_COMBINED_MAX_LEN = 30
_BRIDGE_LEFT_MIN_CJK = 2
_BRIDGE_RIGHT_MIN_CJK = 3
# Confidence discount applied to a unioned (reconstructed) virtual block.
_UNION_BLOCK_CONFIDENCE_FACTOR = 0.95
# Tall non-text glyph filter for visual-line reconstruction.
_RECONSTRUCT_TALL_HEIGHT_MULT = 2.4
_RECONSTRUCT_TALL_ASPECT_MULT = 1.8

# Blank-page detection: minimum dimensions and ink-ratio thresholds.
_BLANK_PAGE_MIN_WIDTH_PX = 600
_BLANK_PAGE_MIN_HEIGHT_PX = 800
_BLANK_PAGE_THUMBNAIL_PX = 512
_BLANK_PAGE_DARK_PIXEL_MAX = 180
_BLANK_PAGE_INK_PIXEL_MAX = 230
_BLANK_PAGE_DARK_RATIO_MAX = 0.00002
_BLANK_PAGE_INK_RATIO_MAX = 0.0001

# Table-line heuristic: downsample size, dimension floor, darkness and line-count thresholds.
_TABLE_HEURISTIC_THUMBNAIL_PX = 640
_TABLE_HEURISTIC_MIN_DIM_PX = 80
_TABLE_HEURISTIC_DARK_PIXEL_MAX = 90
_TABLE_HEURISTIC_HORIZONTAL_DARK_RATIO = 0.35
_TABLE_HEURISTIC_VERTICAL_DARK_RATIO = 0.25
_TABLE_HEURISTIC_MIN_LINES = 3

# Coarse multi-line block detection.
_COARSE_MULTILINE_MIN_COMPACT_LEN = 40
_COARSE_MULTILINE_HEIGHT_MULT = 1.7

# Default OCR-item confidence when the service omits one.
_DEFAULT_OCR_ITEM_CONFIDENCE = 0.9

# OCR-block merge IOU thresholds and structure-precision supplement bounds.
_MERGE_DUPLICATE_IOU = 0.5
_MERGE_OVERLAP_IOU = 0.85
_SHORT_FIELD_MIN_COMPACT_LEN = 4
_SHORT_FIELD_MAX_COMPACT_LEN = 80
_SHORT_FIELD_MAX_DELIMITERS = 4
_SUPPLEMENT_WIDTH_RATIO = 1.2
_SUPPLEMENT_HEIGHT_RATIO = 2.2
_SUPPLEMENT_SIMILARITY_MIN = 0.55
_SUPPLEMENT_WIDER_RATIO = 1.1
_SUPPLEMENT_LONGER_TEXT_MARGIN = 6

# Seal region overlay color (legacy /ocr path).
_SEAL_REGION_COLOR = (255, 0, 0)

# HTML table virtual-cell confidence discount.
_TABLE_CELL_CONFIDENCE_FACTOR = 0.9

# Bridge NER payload character cap.
_BRIDGE_PAYLOAD_MAX_CHARS = 1200
# Minimum entity text length by type for NER results.
_NER_DEFAULT_MIN_LEN = 2
_NER_MIN_LEN_BY_TYPE = {
    "PERSON": 2,
    "ORG": 2,
    "ADDRESS": 4,
}


# Characters allowed in an amount-formatted value (digits plus separators,
# currency symbols and grouping decoration). Shared by the standalone-amount
# block test and the table-cell amount-format test.
_AMOUNT_FORMAT_ALLOWED_CHARS = set("0123456789.,，￥¥$€£-()（）[] ")


# Form-field label/value width tuning.
# Visual-wrap break search window and scoring.
# Typical text-line height inference: minimum block height to consider.
_TEXTLINE_MIN_HEIGHT_PX = 4

# Entity-region estimation tuning.
# Entity-to-OCR matching: fuzzy match and per-type width-cap tuning.
_FUZZY_MATCH_MIN_ENTITY_LEN = 4
_FUZZY_MATCH_BLOCK_LEN_MULT = 3
_FUZZY_MATCH_BLOCK_LEN_FLOOR = 24
_FUZZY_MATCH_RATIO = 0.9
_FUZZY_MATCH_CONFIDENCE = 0.9
_TABLE_FALLBACK_CONFIDENCE = 0.8
