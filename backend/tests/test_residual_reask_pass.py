"""残差补检 pass (0712 海关发票实证: USD 4,700.00/USD 125.00 被长payload稀释).

病理: 整文档一次NER(161块×38标签), 金额桶16值恰漏两个USD值——同标签块级
14/14全召回, 收窄/匹配全无辜, 是0.6B长上下文召回稀释(temp=0确定性)。
修法: "已消费"恒等式=模型自己的答案——任一已返回值(不短于其类型min-len,
防'男'把整块标已消费/多值块部分召回逃逸)与块文本compact后互为子串→块已
消费; 未消费块拼残差payload(同caps同标签)再问一次, 附加式合并只增不减。
"""
import asyncio

from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_analysis import run_has_text_analysis


def _block(text: str, top: int) -> OCRTextBlock:
    return OCRTextBlock(
        text=text,
        polygon=[[100, top], [600, top], [600, top + 30], [100, top + 30]],
        confidence=0.98,
    )


class _RecordingHaS:
    """First call = main pass answers; later calls = residual answers."""

    def __init__(self, answers_by_call):
        self.answers_by_call = answers_by_call
        self.calls = []

    def ner(self, text, labels=None, **_kwargs):
        # Accept the real ner's keyword-only temperature/sample_index (the main
        # call now drives the self-consistent aggregator through them).
        self.calls.append(text)
        index = min(len(self.calls) - 1, len(self.answers_by_call) - 1)
        return self.answers_by_call[index]


def _run(blocks, client):
    return asyncio.run(run_has_text_analysis(blocks, client, vision_types=None))


def test_partially_recalled_block_reaches_the_residual_pass():
    # main pass returns only ONE of the two amounts in the same block set —
    # the residual pass must re-ask over the unconsumed block and recover it
    blocks = [
        _block("单价 USD 2,350.00", 100),
        _block("总价 USD 4,700.00", 140),
    ]
    client = _RecordingHaS([
        {"金额": ["USD 2,350.00"]},          # main pass: dilution drops 4,700
        {"金额": ["USD 4,700.00"]},          # residual pass recovers it
    ])
    entities = _run(blocks, client)
    texts = {e["text"] for e in entities if e["type"] == "AMOUNT"}
    assert any("2,350.00" in t or "2350.00" in t for t in texts)
    assert any("4,700.00" in t or "4700.00" in t for t in texts)
    assert len(client.calls) >= 2  # residual pass actually ran
    # the consumed block must NOT be in the residual payload
    assert "2,350.00" not in client.calls[-1]
    assert "4,700.00" in client.calls[-1]


def test_short_value_does_not_consume_a_block():
    # '男' (below the default min length) is kept as an entity but must not
    # mark the whole 性别 block as consumed — the block stays in the residual
    # payload (张三's block IS consumed, so the residual differs from the main)
    blocks = [
        _block("性别：男，联系电话见附页", 100),
        _block("张三", 140),
    ]
    client = _RecordingHaS([
        {"性别": ["男"], "姓名": ["张三"]},
        {},  # residual finds nothing more
    ])
    _run(blocks, client)
    assert len(client.calls) >= 2, "short values must not suppress the residual pass"
    assert "性别" in client.calls[-1]
    assert "张三" not in client.calls[-1]


def test_fully_consumed_page_skips_the_residual_call():
    blocks = [_block("张三", 100)]
    client = _RecordingHaS([
        {"姓名": ["张三"]},
    ])
    entities = _run(blocks, client)
    assert [e["text"] for e in entities if e["type"] == "PERSON"] == ["张三"]
    assert len(client.calls) == 1  # nothing unconsumed -> no residual call


def test_empty_residual_answer_changes_nothing():
    blocks = [
        _block("张三", 100),
        _block("表头栏目名称说明文字", 140),
    ]
    client = _RecordingHaS([
        {"姓名": ["张三"]},
        {},  # residual over the header block returns nothing
    ])
    entities = _run(blocks, client)
    assert [e["text"] for e in entities if e["type"] == "PERSON"] == ["张三"]
