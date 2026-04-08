"""
OCR 服务客户端
通过 HTTP 调用独立的 PaddleOCR-VL 微服务 (端口8082)
不再在后端进程中加载 PaddleOCR 模型
"""
from __future__ import annotations

import base64
import logging
import httpx
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

from app.core.config import settings
from app.core.retry import retry_sync, RETRYABLE_HTTPX
from app.core.circuit_breaker import ocr_breaker


class OCRServiceError(Exception):
    """OCR 服务错误，区分瞬态（可重试）和永久错误。"""
    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


@dataclass
class OCRItem:
    text: str
    x: float      # 归一化坐标 0-1
    y: float
    width: float
    height: float
    confidence: float
    label: str = "text"


class OCRService:
    """OCR 服务客户端 - 通过 HTTP 调用独立微服务（带连接池复用）"""

    def __init__(self) -> None:
        self.base_url = settings.OCR_BASE_URL.rstrip('/')
        self._read_timeout = float(settings.OCR_TIMEOUT)
        # 健康检查用短超时客户端（复用连接池）
        probe_timeout = max(5.0, float(settings.OCR_HEALTH_PROBE_TIMEOUT))
        self._health_client = httpx.Client(timeout=probe_timeout, trust_env=False)
        # OCR 推理用长超时客户端
        ocr_timeout = httpx.Timeout(connect=15.0, read=self._read_timeout, write=60.0, pool=15.0)
        self._ocr_client = httpx.Client(timeout=ocr_timeout, trust_env=False)

    def is_available(self) -> bool:
        """检查 OCR 微服务是否在线且模型已就绪"""
        try:
            resp = self._health_client.get(f"{self.base_url}/health")
            if resp.status_code == 200:
                data = resp.json()
                return bool(data.get("ready", False))
        except Exception as e:
            logger.debug("OCR health check failed: %s", e)
        return False

    def get_model_name(self) -> str:
        """获取模型名称"""
        try:
            resp = self._health_client.get(f"{self.base_url}/health")
            if resp.status_code == 200:
                return resp.json().get("model", "PaddleOCR-VL")
        except Exception as e:
            logger.debug("OCR model name check failed: %s", e)
        return "PaddleOCR-VL"

    def _do_ocr_request(self, image_b64: str) -> httpx.Response:
        """Execute a single OCR HTTP request (retryable, uses pooled client)."""
        def _request():
            return self._ocr_client.post(
                f"{self.base_url}/ocr",
                json={"image": image_b64, "max_new_tokens": 512},
            )
        return ocr_breaker.call_sync(_request)

    def extract_text_boxes(self, image_bytes: bytes) -> List[OCRItem]:
        """调用 OCR 微服务提取文本框"""
        if not image_bytes:
            return []

        if settings.OCR_REQUIRE_GPU and not self.is_available():
            raise OCRServiceError(
                "OCR 服务离线且已启用 OCR_REQUIRE_GPU，拒绝 CPU 回退。"
                "请启动 GPU 服务: docker compose --profile gpu up -d",
                transient=False,
            )

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        try:
            # 连接要快失败；读取等待 VL 完整推理（默认数分钟）
            resp = retry_sync(
                self._do_ocr_request, image_b64,
                max_retries=2, base_delay=1.0,
                retryable_exceptions=RETRYABLE_HTTPX,
            )
            if resp.status_code != 200:
                logger.error("OCR Client error: %d %s", resp.status_code, resp.text[:200])
                return []

            data = resp.json()
            items = []
            for box in data.get("boxes", []):
                items.append(OCRItem(
                    text=box["text"],
                    x=box["x"],
                    y=box["y"],
                    width=box["width"],
                    height=box["height"],
                    confidence=box.get("confidence", 0.9),
                    label=box.get("label", "text"),
                ))
            logger.info("OCR Client got %d boxes in %.2fs", len(items), data.get('elapsed', 0))
            return items

        except httpx.TimeoutException as e:
            msg = (
                f"OCR 微服务超时（read≈{self._read_timeout:.0f}s）。"
                "若 8082 仍在推理属正常，请增大 OCR_TIMEOUT；若长期无响应请查看 ocr_server 控制台。"
            )
            logger.warning(msg)
            raise OCRServiceError(msg, transient=True) from e
        except (httpx.ConnectError, httpx.NetworkError) as e:
            msg = f"无法连接 OCR 微服务 ({self.base_url}): {e}"
            logger.error(msg)
            raise OCRServiceError(msg, transient=True) from e
        except Exception as e:
            msg = f"OCR 识别失败: {e}"
            logger.error(msg)
            raise OCRServiceError(msg, transient=False) from e


# 全局实例
ocr_service = OCRService()
