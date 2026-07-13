"""Scanned-PDF sparse text-layer probe cache.

扫描版 PDF 的原生文本层稀疏判定缓存。

Remembers which scanned PDFs have a sparse (or empty) native text layer so the
dual pipeline can skip re-probing them, and hands out a per-file asyncio lock so
concurrent page fan-out probes a given PDF only once. This is pure bookkeeping
around ``FileType.PDF_SCANNED`` detection — no PII decisions live here.
"""
import asyncio
import logging
import os
from collections import OrderedDict
from threading import Lock

from app.core.config import settings
from app.models.schemas import FileType

logger = logging.getLogger(__name__)

_PDF_TEXT_LAYER_SPARSE_SKIP_AFTER = 2
_PDF_TEXT_LAYER_SPARSE_CACHE_MAX_ITEMS = 128
_PDF_TEXT_LAYER_SPARSE_LOCK = Lock()
_PDF_TEXT_LAYER_SPARSE_COUNTS: OrderedDict[tuple[str, int, int], int] = OrderedDict()
_PDF_TEXT_LAYER_PROBE_LOCKS: dict[tuple[str, int, int], asyncio.Lock] = {}
_PDF_TEXT_LAYER_PROBE_LOCKS_LOOP: asyncio.AbstractEventLoop | None = None

# A probe whose char count is at/below this fraction of the min-char threshold
# counts as a strong sparse signal and short-circuits future probes.
_SPARSE_PROBE_STRONG_SIGNAL_DIVISOR = 4


def _pdf_text_layer_sparse_key(file_path: str) -> tuple[str, int, int] | None:
    try:
        resolved = os.path.realpath(file_path)
        stat = os.stat(resolved)
        return (resolved, int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        logger.debug("Unable to stat PDF for sparse text-layer cache: %s", file_path, exc_info=True)
        return None


def _should_skip_sparse_pdf_text_layer(file_path: str, file_type: FileType | str) -> bool:
    if file_type != FileType.PDF_SCANNED:
        return False
    key = _pdf_text_layer_sparse_key(file_path)
    if key is None:
        return False
    with _PDF_TEXT_LAYER_SPARSE_LOCK:
        count = _PDF_TEXT_LAYER_SPARSE_COUNTS.get(key, 0)
        if count:
            _PDF_TEXT_LAYER_SPARSE_COUNTS.move_to_end(key)
        return count >= _PDF_TEXT_LAYER_SPARSE_SKIP_AFTER


def _get_pdf_text_layer_probe_lock(file_path: str, file_type: FileType | str) -> asyncio.Lock | None:
    if file_type != FileType.PDF_SCANNED:
        return None
    key = _pdf_text_layer_sparse_key(file_path)
    if key is None:
        return None

    global _PDF_TEXT_LAYER_PROBE_LOCKS_LOOP
    loop = asyncio.get_running_loop()
    with _PDF_TEXT_LAYER_SPARSE_LOCK:
        if _PDF_TEXT_LAYER_PROBE_LOCKS_LOOP is not loop:
            _PDF_TEXT_LAYER_PROBE_LOCKS.clear()
            _PDF_TEXT_LAYER_PROBE_LOCKS_LOOP = loop
        lock = _PDF_TEXT_LAYER_PROBE_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _PDF_TEXT_LAYER_PROBE_LOCKS[key] = lock
        return lock


def _sparse_pdf_text_layer_probe_weight(stats: dict | None = None) -> int:
    if not isinstance(stats, dict):
        return 1
    min_chars = max(0, int(settings.PDF_TEXT_LAYER_MIN_CHARS))
    if min_chars <= 0:
        return 1
    char_count = int(stats.get("char_count") or 0)
    if char_count <= max(1, min_chars // _SPARSE_PROBE_STRONG_SIGNAL_DIVISOR):
        return _PDF_TEXT_LAYER_SPARSE_SKIP_AFTER
    return 1


def _record_sparse_pdf_text_layer_probe(
    file_path: str,
    file_type: FileType | str,
    *,
    stats: dict | None = None,
) -> None:
    if file_type != FileType.PDF_SCANNED:
        return
    key = _pdf_text_layer_sparse_key(file_path)
    if key is None:
        return
    weight = max(1, _sparse_pdf_text_layer_probe_weight(stats))
    with _PDF_TEXT_LAYER_SPARSE_LOCK:
        _PDF_TEXT_LAYER_SPARSE_COUNTS[key] = min(
            _PDF_TEXT_LAYER_SPARSE_SKIP_AFTER,
            _PDF_TEXT_LAYER_SPARSE_COUNTS.get(key, 0) + weight,
        )
        _PDF_TEXT_LAYER_SPARSE_COUNTS.move_to_end(key)
        while len(_PDF_TEXT_LAYER_SPARSE_COUNTS) > _PDF_TEXT_LAYER_SPARSE_CACHE_MAX_ITEMS:
            _PDF_TEXT_LAYER_SPARSE_COUNTS.popitem(last=False)
