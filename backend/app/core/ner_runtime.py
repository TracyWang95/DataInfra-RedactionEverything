# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
运行时 NER 后端配置（优先于环境变量 / .env）
由前端「模型设置」页写入 data/ner_backend.json
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class NerBackendRuntime(BaseModel):
    backend: Literal["llamacpp"] = "llamacpp"
    llamacpp_base_url: str = Field(default="http://127.0.0.1:8080/v1")


def _path() -> str:
    from app.core.config import get_settings
    return os.path.join(get_settings().DATA_DIR, "ner_backend.json")


def load_ner_runtime() -> Optional[NerBackendRuntime]:
    p = _path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return NerBackendRuntime(**json.load(f))
    except Exception as e:
        logger.warning("读取 ner_backend.json 失败: %s", e)
        return None


def save_ner_runtime(cfg: NerBackendRuntime) -> None:
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg.model_dump(), f, ensure_ascii=False, indent=2)
