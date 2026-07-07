"""HaS NER 输出被截断（复读循环耗尽 max_tokens）时的自愈行为。

回归背景（2026-07-02 简历 E2E）：日期密集文档上 0.6B 模型对"日期"桶复读循环，
输出在后续桶（自定义项排在末尾）之前被 max_tokens 截断——JSON 经 json_repair
恢复后：①排在后面的类型整桶丢失；②被切断的残值（如 '2'）留在末桶变成假框。
修复：json_repair 解析路径上 ①对缺失类型补发一次查询并合并；②丢弃末桶的
截断残值（是同桶更早值的前缀时）。
"""

import json

from app.services.has_client import HaSClient

FLOOD_TRUNCATED = (
    '{"姓名":["焦先生"],"日期":["2016.04 - 至今（8年1个月）","2012.07 - 2013.07 (1年)",'
    '"2016.04 - 至今（8年1个月）","2012.07 - 2013.07 (1年)","2'
)

CLEAN_TAIL = '{"薪酬":["10K-15K/月","2.8万-3.5万/月"],"年龄（岁）":["36岁"]}'

TEXT = "焦先生 男 36岁 (1988年4月) 咨询项目经理 2.8万-3.5万/月 10K-15K/月 2016.04 - 至今（8年1个月） 2012.07 - 2013.07 (1年)"

TYPES = ["姓名", "日期", "薪酬", "年龄（岁）"]


def make_client(responses):
    client = HaSClient()
    calls = []

    def fake_call_model(messages, *, max_tokens=None):
        calls.append(messages[0]["content"])
        return responses[min(len(calls) - 1, len(responses) - 1)]

    client._call_model = fake_call_model
    return client, calls


def test_truncated_flood_requeries_missing_types_and_merges():
    client, calls = make_client([FLOOD_TRUNCATED, CLEAN_TAIL])
    result = client.ner(TEXT + " t1", TYPES, type_guidance=[])

    assert len(calls) == 2, f"expected exactly one retry, got {len(calls)} calls"
    # 补查的 prompt 只带缺失类型
    assert "薪酬" in calls[1] and "年龄（岁）" in calls[1]
    assert '"姓名"' not in calls[1]
    # 合并结果包含被截断丢失的桶
    assert result.get("薪酬") == ["10K-15K/月", "2.8万-3.5万/月"]
    assert result.get("年龄（岁）") == ["36岁"]
    # 截断残值 '2' 被丢弃
    assert "2" not in result.get("日期", [])
    assert "焦先生" in result.get("姓名", [])


def test_clean_parse_with_absent_types_does_not_retry():
    clean = json.dumps({"姓名": ["焦先生"], "日期": ["2016.04 - 至今（8年1个月）"]}, ensure_ascii=False)
    client, calls = make_client([clean])
    result = client.ner(TEXT + " t2", TYPES, type_guidance=[])

    assert len(calls) == 1, "clean parse must not trigger a retry"
    assert "薪酬" not in result


def test_truncation_retry_happens_at_most_once():
    truncated_again = '{"薪酬":["10K'
    client, calls = make_client([FLOOD_TRUNCATED, truncated_again])
    client.ner(TEXT + " t3", TYPES, type_guidance=[])

    assert len(calls) == 2, f"retry must be capped at one, got {len(calls)} calls"


def test_trim_keeps_tail_value_that_is_not_a_repetition_prefix():
    result = {"日期": ["2016.04 - 至今（8年1个月）", "2015.05 - 2016.04（11个月）"]}
    trimmed = HaSClient._trim_truncated_tail_value(result)
    assert trimmed["日期"] == ["2016.04 - 至今（8年1个月）", "2015.05 - 2016.04（11个月）"]
