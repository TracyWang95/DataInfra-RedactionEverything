"""R4w: run_has_text_analysis 主 NER 调用接入 aggregate_ner_samples.

离线 glue（纯 mock，无 GPU）。验证主 NER 调用走多趟并集聚合器：
  * K = settings.HAS_NER_SELF_CONSIST_SAMPLES 控制趟数；
  * 第 0 趟恒 temp=0 贪心种子，>=1 趟带 per-request temperature 与递增
    sample_index（缓存键含 index，不塌成 1 趟）；
  * K=1 与现状逐字等价（单趟 temp=0 种子，并集永不加宽）。

真实 temp>0 是否提升召回 / 饱和收敛 / 突发防崩由人类 GPU 主循环验证——这里只
钉住接线 glue（趟号、per-request 温度、并集只增不减到达输出）。
"""
import asyncio
import threading

from app.core.config import settings
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.ocr_pipeline import run_has_text_analysis


class _SampleRecordingClient:
    """按 sample_index 返回不同集合的 has_client 替身，记录每次 ner 的温度/趟号。

    主 payload 的多趟采样是被测对象；bridge/残差 re-ask 走独立（更短）payload、
    默认 sample_index=0，因此在 index>=1 才返回扩展值——只有主 payload 真正以
    distinct index 重采样时并集才会加宽。
    """

    base_url = "http://stub-selfconsist:0"

    def __init__(self):
        self.calls = []  # (temperature, sample_index)
        self._lock = threading.Lock()

    def ner(self, text, entity_types=None, *, temperature=None, sample_index=0, **_kw):
        with self._lock:
            self.calls.append((temperature, sample_index))
        if sample_index >= 1:
            return {"姓名": ["张三", "李四"]}
        return {"姓名": ["张三"]}


def _blocks():
    lines = [f"张三 李四 联系电话 13800000000 第{i}行文字内容足够长" for i in range(4)]
    return [
        OCRTextBlock(
            text=line,
            polygon=[[0, 40 * i], [500, 40 * i], [500, 40 * i + 30], [0, 40 * i + 30]],
        )
        for i, line in enumerate(lines)
    ]


class _NameType:
    id = "PERSON"
    name = "姓名"


def _run(client):
    return asyncio.run(
        run_has_text_analysis(_blocks(), client, vision_types=[_NameType()])
    )


def test_k1_single_pass_temp0_seed_equivalent_to_status_quo(monkeypatch):
    monkeypatch.setattr(settings, "HAS_NER_SELF_CONSIST_SAMPLES", 1, raising=False)
    client = _run_client = _SampleRecordingClient()
    entities = _run(client)
    # 主 payload 只跑 temp=0 种子——绝无 sample_index>=1 的重采样。
    assert all(idx == 0 for _t, idx in client.calls)
    assert all(temp in (None, 0.0) for temp, _idx in client.calls)
    texts = {e["text"] for e in entities}
    assert "张三" in texts
    # 并集从未加宽：李四 只在 index>=1 出现，K=1 下永不出现 == 现状种子。
    assert "李四" not in texts


def test_k_gt_1_unions_multi_pass_samples(monkeypatch):
    monkeypatch.setattr(settings, "HAS_NER_SELF_CONSIST_SAMPLES", 3, raising=False)
    monkeypatch.setattr(settings, "HAS_NER_SELF_CONSIST_TEMPERATURE", 0.7, raising=False)
    client = _SampleRecordingClient()
    entities = _run(client)
    indices = [idx for _t, idx in client.calls]
    # 主 payload 以 distinct 趟号（0 然后 >=1）重采样，不塌成 1 趟。
    assert 0 in indices and 1 in indices, indices
    # 第 0 趟恒 temp=0 种子；>=1 趟带配置采样温度。
    seed_temps = [t for t, i in client.calls if i == 0]
    resample_temps = [t for t, i in client.calls if i >= 1]
    assert seed_temps and all(t in (None, 0.0) for t in seed_temps)
    assert resample_temps and all(t == 0.7 for t in resample_temps)
    # 并集只增不减：李四（仅 index>=1 返回）到达输出。
    texts = {e["text"] for e in entities}
    assert {"张三", "李四"} <= texts
