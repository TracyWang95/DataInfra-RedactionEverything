"""Residual pass token-boundary + char-coverage (R3).

Pure-logic offline tests for _block_residual_ink plus one end-to-end proof
that a merged two-column block is actually re-asked.

The old "已消费" test was bare containment: any(value in block or block in
value). It let a single recalled value swallow a merged two-column block, so
the second column's value never reached the residual re-ask. The new identity
carves out only ISOLATED-TOKEN occurrences and keeps the block alive while it
still holds a value-sized run of unexplained ink.

(File named *multi_field* so the vision regression -k selector collects it.)
"""
import asyncio

from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_analysis import (
    _block_residual_ink,
    run_has_text_analysis,
)


# ---- pure logic -----------------------------------------------------------

def test_multi_field_two_column_id_block_is_unconsumed():
    # merged 身份证号码 two-column block, only the FIRST id recalled.
    block = "身份证号码11010119900307461X身份证号码22020219850612345"
    residual = _block_residual_ink(block, ["11010119900307461X"])
    assert residual is not None                     # not consumed
    assert "22020219850612345" in residual          # second column survives
    assert "11010119900307461X" not in residual     # consumed sibling dropped


def test_multi_field_block_equal_to_value_is_consumed():
    # block IS the value -> consumed (block ⊂ value, kept second branch)
    assert _block_residual_ink("11010119900307461X", ["11010119900307461X"]) is None


def test_multi_field_isolated_token_spares_superstring():
    # 张三 is NOT an isolated token inside 张三丰, so it must not consume it.
    residual = _block_residual_ink("负责人张三丰", ["张三"])
    assert residual is not None
    assert "张三丰" in residual


def test_multi_field_exact_name_block_is_consumed():
    assert _block_residual_ink("张三", ["张三"]) is None


def test_multi_field_label_only_leftover_is_consumed():
    # single value block: after carving the id, only 号码： remains — below the
    # half-of-shortest-anchor scale, so no wasteful re-ask and no gate swell.
    assert _block_residual_ink("号码：11010119900307461X", ["11010119900307461X"]) is None


def test_multi_field_empty_block_is_none():
    assert _block_residual_ink("", ["张三"]) is None


def test_multi_field_no_consumed_value_returns_whole_block():
    # nothing anchored -> the block is wholly unexplained ink.
    assert _block_residual_ink("张三丰", []) == "张三丰"


# ---- end to end -----------------------------------------------------------

def _block(text: str, top: int) -> OCRTextBlock:
    return OCRTextBlock(
        text=text,
        polygon=[[100, top], [600, top], [600, top + 30], [100, top + 30]],
        confidence=0.98,
    )


class _ContentHaS:
    """Answers by INPUT content, not call index, so a bridge pass (if any)
    cannot shift the assertions: any text still holding the first id returns
    only the first (models the long-payload dilution); the carved residual
    holds only the second id and returns it."""

    def __init__(self):
        self.calls = []

    def ner(self, text, labels=None, **_kwargs):
        # Accept the real ner's keyword-only temperature/sample_index (the main
        # call now drives the self-consistent aggregator through them).
        self.calls.append(text)
        compact = "".join(text.split())
        if "11010119900307461X" in compact:
            return {"身份证": ["11010119900307461X"]}
        if "22020219850612345" in compact:
            return {"身份证": ["22020219850612345"]}
        return {}


def test_multi_field_two_column_block_is_reasked_end_to_end():
    # a LONE merged two-column block: the residual payload must differ from the
    # full page text (residual_text != text_content gate) and recover column 2.
    blocks = [_block("身份证号码 11010119900307461X 身份证号码 22020219850612345", 100)]
    client = _ContentHaS()
    entities = asyncio.run(run_has_text_analysis(blocks, client, vision_types=None))
    ids = {e["text"] for e in entities}
    assert "11010119900307461X" in ids
    assert "22020219850612345" in ids               # recovered by residual
    assert len(client.calls) >= 2                    # residual pass ran
    residual_text = client.calls[-1]
    assert "22020219850612345" in residual_text
    assert "11010119900307461X" not in residual_text  # residual != main payload
