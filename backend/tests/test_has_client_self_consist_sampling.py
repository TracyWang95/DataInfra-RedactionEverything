"""Per-request temperature + sample-index cache key on HaSClient.ner.

Self-consistent multi-pass sampling needs two things from the client that the
pure union aggregator cannot provide on its own:

1. Per-request temperature — pass 0 is temp=0 greedy, passes >=1 are temp>0.
   The temperature must reach the request payload, not be hardcoded.
2. A sample-index component in the NER cache key — otherwise pass 1 over the
   SAME payload would be served pass 0's cached deterministic result and the
   union would collapse to a single 趟. Distinct sample_index -> distinct key.

The real sampling loop is the human GPU main loop's job; these tests pin the
offline mechanism only.
"""
from app.services.has_client import HaSClient


class _FakeResp:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"finish_reason": "stop", "message": {"content": self._content}}]}


def _capturing_client(base_url, *, cache_ttl):
    client = HaSClient(base_url=base_url)
    client._ner_cache_ttl_sec = cache_ttl
    client._ner_cache_max_items = 128
    client._ner_cache.clear()
    payloads: list[dict] = []

    def fake_request(base, payload):
        payloads.append(payload)
        return _FakeResp('{"姓名":["张三"]}')

    client._do_chat_request = fake_request
    return client, payloads


def test_has_client_self_consist_per_request_temperature_flows_to_payload():
    client, payloads = _capturing_client("http://stub-temp:0", cache_ttl=0)
    client.ner("这是一段足够长的测试文本内容用于识别", ["姓名"], temperature=0.7)
    assert payloads[0]["temperature"] == 0.7
    # Omitting temperature keeps the deterministic default (temp=0 seed).
    client.ner("这是另一段足够长的测试文本内容用于识别", ["姓名"])
    assert payloads[1]["temperature"] == 0.0


def test_has_client_self_consist_sample_index_is_in_cache_key():
    client, _ = _capturing_client("http://stub-key:0", cache_ttl=300)
    key0 = client._ner_cache_key("同一段足够长的文本内容", ["姓名"], "", 0)
    key1 = client._ner_cache_key("同一段足够长的文本内容", ["姓名"], "", 1)
    assert key0 != key1
    # Same everything else -> only the sample index differs.
    assert key0[:-1] == key1[:-1]


def test_has_client_self_consist_distinct_sample_index_bypasses_cache():
    client, payloads = _capturing_client("http://stub-collapse:0", cache_ttl=300)
    text = "这是一段足够长的测试文本内容用于识别"
    client.ner(text, ["姓名"], sample_index=0)
    client.ner(text, ["姓名"], sample_index=1)
    assert len(payloads) == 2, "different sample_index must re-sample, not collapse to 1 趟"
    # Re-asking the SAME sample index is still served from cache (one union entry).
    client.ner(text, ["姓名"], sample_index=0)
    assert len(payloads) == 2
