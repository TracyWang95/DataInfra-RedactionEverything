# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
结构化日志配置 — JSON 格式输出，方便日志聚合（ELK / Loki / CloudWatch）。

使用方式：在 main.py 启动时调用 setup_logging()。
"""
import logging
import sys
from pythonjsonlogger import jsonlogger

from app.core.request_id import request_id_var


class RequestIdJsonFormatter(jsonlogger.JsonFormatter):
    """JSON 格式化器，自动注入 request_id。"""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["request_id"] = request_id_var.get("")
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        if not log_record.get("timestamp"):
            log_record["timestamp"] = self.formatTime(record)


def setup_logging(json_mode: bool = True, level: int = logging.INFO) -> None:
    """
    配置全局日志。

    json_mode=True  → JSON 格式（生产环境）
    json_mode=False → 传统文本格式（开发调试）
    """
    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有 handler（避免重复）
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if json_mode:
        formatter = RequestIdJsonFormatter(
            fmt="%(timestamp)s %(level)s %(logger)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(name)s] %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # 降低第三方库噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
