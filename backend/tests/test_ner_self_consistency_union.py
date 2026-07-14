"""Self-consistent multi-pass NER union aggregator (pure offline core).

The union of K sampled NER passes over the SAME payload. Pass 0 is the temp=0
greedy seed (the caller wires temperature/sample-index per pass); passes >=1 are
temp>0 re-samples. The union is monotone non-decreasing — type->values only ever
accumulate — so it is always a superset of pass 0, i.e. of today's deterministic
result. "No new value this pass" only signals budget convergence (stop spending
GPU); it is NEVER treated as proof the page holds no more PII.

The real per-pass GPU calls are the human main loop's job. This tests the pure
union+seed+stopping function only: it takes a callable that yields each pass's
result and returns (union, passes_run).
"""
from app.services.vision.has_text_analysis import aggregate_ner_samples


def _from_sequence(results):
    calls = {"indices": []}

    def sample_fn(index):
        calls["indices"].append(index)
        return results[index]

    return sample_fn, calls


def test_self_consist_union_accumulates_and_stops_on_convergence():
    # spec: [{ID:[甲]},{ID:[甲,乙]},{ID:[甲,乙]}] -> union {甲,乙}; pass 3 adds
    # nothing new -> stop (3 calls total).
    sample_fn, calls = _from_sequence(
        [{"ID": ["甲"]}, {"ID": ["甲", "乙"]}, {"ID": ["甲", "乙"]}]
    )
    union, passes = aggregate_ner_samples(sample_fn, max_passes=8)
    assert union == {"ID": ["甲", "乙"]}
    assert passes == 3
    assert calls["indices"] == [0, 1, 2]


def test_self_consist_seed_pass_is_index_zero_and_always_in_union():
    # index 0 is the temp=0 seed; even if later passes never return 甲 again,
    # the seed value can never leave the union (union only grows).
    sample_fn, calls = _from_sequence(
        [{"ID": ["甲"]}, {"ID": ["乙"]}, {"ID": ["乙"]}]
    )
    union, passes = aggregate_ner_samples(sample_fn, max_passes=8)
    assert calls["indices"][0] == 0
    assert "甲" in union["ID"]
    assert union == {"ID": ["甲", "乙"]}
    assert passes == 3


def test_self_consist_distinct_sample_indices_do_not_collapse_to_one_pass():
    # The aggregator drives distinct pass indices (0,1,2). Combined with the
    # sample-index cache key on the client, temp>0 passes re-sample instead of
    # being served the seed's cached result — the union never collapses to 1 趟.
    seen = []

    def sample_fn(index):
        seen.append(index)
        return {"ID": ["甲"]} if index == 0 else {"ID": ["甲", f"v{index}"]}

    union, passes = aggregate_ner_samples(sample_fn, max_passes=3)
    assert seen == [0, 1, 2]
    assert passes == 3
    assert set(union["ID"]) == {"甲", "v1", "v2"}


def test_self_consist_hallucinated_value_stays_in_union_matcher_gates_regions():
    # The aggregator never drops a value — a hallucinated string sampled at
    # temp>0 stays in the union. Leak-safety is downstream: the matcher yields
    # 0 region for any value absent from the OCR blocks. Union stays inclusive.
    sample_fn, _ = _from_sequence(
        [{"ID": ["真串"]}, {"ID": ["真串", "幻觉串"]}, {"ID": ["真串", "幻觉串"]}]
    )
    union, _passes = aggregate_ner_samples(sample_fn, max_passes=8)
    assert "幻觉串" in union["ID"]
    assert "真串" in union["ID"]


def test_self_consist_empty_seed_still_takes_a_second_sample():
    # An empty greedy seed must not stop the loop at a single pass — convergence
    # is only checked for passes after the seed.
    sample_fn, calls = _from_sequence([{}, {"ID": ["乙"]}, {"ID": ["乙"]}])
    union, passes = aggregate_ner_samples(sample_fn, max_passes=8)
    assert calls["indices"][:2] == [0, 1]
    assert union == {"ID": ["乙"]}
    assert passes == 3


def test_self_consist_budget_caps_pass_count():
    # A payload where every pass keeps adding a new value never converges; the
    # budget封顶 stops it. The union already gathered is kept, never rolled back.
    def sample_fn(index):
        return {"ID": [f"v{index}"]}

    union, passes = aggregate_ner_samples(sample_fn, max_passes=4)
    assert passes == 4
    assert set(union["ID"]) == {"v0", "v1", "v2", "v3"}


def test_self_consist_early_convergence_two_passes():
    sample_fn, _ = _from_sequence([{"ID": ["甲"]}, {"ID": ["甲"]}])
    union, passes = aggregate_ner_samples(sample_fn, max_passes=8)
    assert union == {"ID": ["甲"]}
    assert passes == 2
