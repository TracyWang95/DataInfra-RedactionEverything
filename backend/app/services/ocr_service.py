"""
OCR 服务客户端
通过 HTTP 调用独立的 PaddleOCR-VL 微服务 (端口8082)
不再在后端进程中加载 PaddleOCR 模型
"""
from __future__ import annotations

import base64
import httpx
from dataclasses import dataclass
from typing import List

from app.core.config import settings


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
    """OCR 服务客户端 - 通过 HTTP 调用独立微服务"""

    def __init__(self) -> None:
        self.base_url = settings.OCR_BASE_URL.rstrip('/')
        self._read_timeout = float(settings.OCR_TIMEOUT)

    def is_available(self) -> bool:
        """检查 OCR 微服务是否在线且模型已就绪"""
        try:
            t = max(5.0, float(settings.OCR_HEALTH_PROBE_TIMEOUT))
            with httpx.Client(timeout=t, trust_env=False) as client:
                resp = client.get(f"{self.base_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    return bool(data.get("ready", False))
        except Exception:
            pass
        return False

    def get_model_name(self) -> str:
        """获取模型名称"""
        try:
            t = max(5.0, float(settings.OCR_HEALTH_PROBE_TIMEOUT))
            with httpx.Client(timeout=t, trust_env=False) as client:
                resp = client.get(f"{self.base_url}/health")
                if resp.status_code == 200:
                    return resp.json().get("model", "PaddleOCR-VL")
        except Exception:
            pass
        return "PaddleOCR-VL"

    def extract_text_boxes(self, image_bytes: bytes) -> List[OCRItem]:
        """调用 OCR 微服务提取文本框"""
        if not image_bytes:
            return []

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        try:
            # 连接要快失败；读取等待 VL 完整推理（默认数分钟）
            ocr_timeout = httpx.Timeout(connect=15.0, read=self._read_timeout, write=60.0, pool=15.0)
            with httpx.Client(timeout=ocr_timeout, trust_env=False) as client:
                resp = client.post(
                    f"{self.base_url}/ocr",
                    json={"image": image_b64, "max_new_tokens": 512},
                )
                if resp.status_code != 200:
                    print(f"[OCR Client] Error: {resp.status_code} {resp.text[:200]}")
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
                print(f"[OCR Client] Got {len(items)} boxes in {data.get('elapsed', 0):.2f}s")
                return items

        except httpx.TimeoutException:
            print(
                f"[OCR Client] 等待 OCR 微服务超时（read≈{self._read_timeout}s）。"
                "若 8082 仍在推理属正常，请增大环境变量 OCR_TIMEOUT 或减轻并发；"
                "若长期无响应请查看 ocr_server 控制台。"
            )
            return []
        except Exception as e:
            print(f"[OCR Client] Error: {e}")
            return []


# 全局实例
ocr_service = OCRService()
