"""LB least-inflight 调度（deploy/host-scripts/lb_proxy.py）。

lb_proxy 是部署产物不在 app 包里，按文件路径 import；只测 _pick 的调度语义。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

LB_PATH = Path(__file__).resolve().parents[2] / "deploy" / "host-scripts" / "lb_proxy.py"


def _load_lb(monkeypatch):
    monkeypatch.setenv("LB_UPSTREAMS", "http://a,http://b,http://c")
    spec = importlib.util.spec_from_file_location("lb_proxy_under_test", LB_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_idle_traffic_rotates_round_robin(monkeypatch):
    lb = _load_lb(monkeypatch)
    picks = [lb._pick() for _ in range(6)]
    # 全空闲时轮转铺开（顺序不限，但 3 个上游各拿 2 次）
    assert sorted(picks) == ["http://a", "http://a", "http://b", "http://b", "http://c", "http://c"]


def test_busy_upstream_is_skipped(monkeypatch):
    lb = _load_lb(monkeypatch)
    lb._inflight["http://a"] = 2
    lb._inflight["http://b"] = 1
    picks = {lb._pick() for _ in range(4)}
    assert picks == {"http://c"}


def test_counts_recover_after_decrement(monkeypatch):
    lb = _load_lb(monkeypatch)
    lb._inflight["http://a"] = 1
    assert lb._pick() in ("http://b", "http://c")
    lb._inflight["http://a"] = 0
    assert "http://a" in {lb._pick() for _ in range(3)}


def test_requires_env(monkeypatch):
    assert os.path.exists(LB_PATH)
