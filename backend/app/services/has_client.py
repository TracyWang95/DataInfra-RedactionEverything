# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
HaS (Hide And Seek) 本地模型客户端
使用 llama.cpp 的 OpenAI 兼容接口

推荐模型：xuanwulab/HaS_Text_0209_0.6B_Q4（GGUF：HaS_Text_0209_0.6B_Q4_K_M.gguf）
NER / Hide / Pair / Seek 的 user 提示须与模型卡模板逐字一致（勿在 NER 首段插入额外说明）。

功能：
1. ner - 敏感实体识别
2. hide - 标签化匿名化
3. pair - 提取标签映射
4. seek - 标签还原
"""

import json
import logging
import re
import httpx

logger = logging.getLogger(__name__)
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass

from app.core.retry import retry_sync, RETRYABLE_HTTPX
from app.core.circuit_breaker import ner_breaker


@dataclass
class HaSEntity:
    """HaS识别的实体"""
    text: str
    type: str
    tag: Optional[str] = None  # 结构化语义标签


@dataclass 
class HaSResult:
    """HaS处理结果"""
    original_text: str
    masked_text: str
    entities: Dict[str, List[str]]  # {类型: [实体列表]}
    mapping: Dict[str, List[str]]   # {标签: [原文列表]}


class HaSClient:
    """HaS本地模型客户端"""
    
    # 法律文档常用实体类型
    LEGAL_ENTITY_TYPES = [
        "人名", "组织", "地址", "职务", 
        "联系方式", "身份证号", "银行卡号",
        "案件编号", "金额", "日期", "合同编号"
    ]
    
    def __init__(
        self,
        base_url: str = None,
        timeout: float = None
    ):
        from app.core.config import settings
        self._base_url_override = base_url.rstrip("/") if base_url else None
        self.timeout = httpx.Timeout(timeout or settings.HAS_TIMEOUT)
        # 复用 httpx 连接池，避免每次请求创建新连接
        self._http_client = httpx.Client(timeout=self.timeout, trust_env=False)

    def _effective_base_url(self) -> str:
        from app.core.config import get_has_chat_base_url
        if self._base_url_override:
            return self._base_url_override.rstrip("/")
        return get_has_chat_base_url().rstrip("/")
    
    def _do_chat_request(self, base: str, payload: Dict[str, Any]) -> httpx.Response:
        """Execute a single chat completions HTTP request (retryable, uses pooled client)."""
        def _request():
            resp = self._http_client.post(f"{base}/chat/completions", json=payload)
            resp.raise_for_status()
            return resp
        return ner_breaker.call_sync(_request)

    def _call_model(self, messages: List[Dict]) -> str:
        """调用 OpenAI 兼容接口（llama.cpp HaS）。"""
        base = self._effective_base_url()
        payload: Dict[str, Any] = {"messages": messages}
        response = retry_sync(
            self._do_chat_request, base, payload,
            max_retries=2, base_delay=1.0,
            retryable_exceptions=RETRYABLE_HTTPX,
        )
        data = response.json()
        # 安全访问嵌套结构，避免 KeyError/IndexError
        choices = data.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            logger.error("HaS 模型返回无 choices: %.200s", str(data))
            return ""
        message = choices[0].get("message", {})
        return message.get("content", "")
    
    def create_session_mapping(self) -> Dict[str, List[str]]:
        """创建一个独立的会话映射（用于并发安全的批处理）。

        调用方应在请求开始时创建，然后传给 hide() 的 mapping 参数，
        这样每个请求拥有独立的映射，不会互相污染。
        """
        return {}
    
    def ner(
        self, 
        text: str, 
        entity_types: Optional[List[str]] = None
    ) -> Dict[str, List[str]]:
        """
        使用NER能力进行敏感实体识别
        
        Args:
            text: 待识别文本
            entity_types: 要识别的实体类型，默认使用法律文档类型
            
        Returns:
            {类型: [实体列表]}
        """
        types = entity_types or self.LEGAL_ENTITY_TYPES
        types_str = json.dumps(types, ensure_ascii=False)

        # 与 HaS_Text_0209 模型卡 NER 模板一致（Specified types: 与 JSON 数组之间无空格）
        prompt = f"""Recognize the following entity types in the text.
Specified types:{types_str}
<text>{text}</text>"""
        
        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        try:
            response = self._call_model(messages)
            # 解析JSON响应
            result = json.loads(response)
            if not isinstance(result, dict):
                logger.warning("HaS NER 返回非字典类型: %s", type(result).__name__)
                return {}
            return result
        except json.JSONDecodeError:
            # 尝试从响应中提取JSON
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass
            logger.warning("HaS NER 响应无法解析为 JSON: %.200s", response)
            return {}
        except Exception as e:
            logger.error("HaS NER 失败: %s", e)
            return {}
    
    def hide(
        self,
        text: str,
        entity_types: Optional[List[str]] = None,
        use_history: bool = True,
        mapping: Optional[Dict[str, List[str]]] = None,
    ) -> Tuple[str, Dict[str, List[str]]]:
        """
        使用Hide能力进行标签化匿名化

        流程：
        1. 先调用NER识别实体
        2. 再调用Hide替换为结构化标签

        Args:
            text: 待匿名化文本
            entity_types: 要识别的实体类型
            use_history: 是否使用已有映射（保持指代一致性）
            mapping: 请求级映射字典，由调用方通过 create_session_mapping()
                     创建并在同一请求内复用。若为 None 则每次创建新的空映射。

        Returns:
            (匿名化后文本, 映射表)
        """
        types = entity_types or self.LEGAL_ENTITY_TYPES
        types_str = json.dumps(types, ensure_ascii=False)

        # 使用调用方传入的映射，或创建一个请求局部的空映射
        session_mapping: Dict[str, List[str]] = mapping if mapping is not None else {}

        # Step 1: NER识别
        ner_result = self.ner(text, types)
        if not ner_result or all(len(v) == 0 for v in ner_result.values()):
            return text, {}

        ner_json = json.dumps(ner_result, ensure_ascii=False)

        # Step 2: Hide 第 1 轮与 ner() 使用相同 NER 模板
        ner_prompt = f"""Recognize the following entity types in the text.
Specified types:{types_str}
<text>{text}</text>"""

        if use_history and session_mapping:
            # 带历史映射
            history_json = json.dumps(session_mapping, ensure_ascii=False)
            messages = [
                {
                    "role": "user",
                    "content": ner_prompt
                },
                {
                    "role": "assistant",
                    "content": ner_json
                },
                {
                    "role": "user",
                    "content": f"Replace the above-mentioned entity types in the text according to the existing mapping pairs:{history_json}"
                }
            ]
        else:
            # 不带历史映射
            messages = [
                {
                    "role": "user",
                    "content": ner_prompt
                },
                {
                    "role": "assistant",
                    "content": ner_json
                },
                {
                    "role": "user",
                    "content": "Replace the above-mentioned entity types in the text."
                }
            ]

        try:
            masked_text = self._call_model(messages)

            # Step 3: 提取映射
            new_mapping = self.pair(text, masked_text)

            # 将新映射合并到 session_mapping（调用方持有同一引用）
            for tag, values in new_mapping.items():
                if tag not in session_mapping:
                    session_mapping[tag] = []
                for v in values:
                    if v not in session_mapping[tag]:
                        session_mapping[tag].append(v)

            return masked_text, new_mapping

        except Exception as e:
            logger.error("HaS Hide 失败: %s", e)
            return text, {}
    
    def pair(self, original_text: str, masked_text: str) -> Dict[str, List[str]]:
        """
        使用Pair能力提取标签映射
        
        Args:
            original_text: 原始文本
            masked_text: 匿名化后文本
            
        Returns:
            {标签: [原文列表]}
        """
        messages = [
            {
                "role": "user",
                "content": f"""<original>{original_text}</original>
<anonymized>{masked_text}</anonymized>
Extract the mapping from anonymized entities to original entities."""
            }
        ]
        
        try:
            response = self._call_model(messages)
            result = json.loads(response)
            return result
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except (json.JSONDecodeError, ValueError):
                    pass
            return {}
        except Exception as e:
            logger.error("HaS Pair 失败: %s", e)
            return {}
    
    def seek(self, masked_text: str, mapping: Optional[Dict[str, List[str]]] = None) -> str:
        """
        使用Seek能力进行标签还原

        Args:
            masked_text: 匿名化后的文本
            mapping: 映射表（必须由调用方显式提供）

        Returns:
            还原后的原文
        """
        if not mapping:
            return masked_text

        mapping_json = json.dumps(mapping, ensure_ascii=False)
        
        messages = [
            {
                "role": "user",
                "content": f"""The mapping from anonymized entities to original entities:
{mapping_json}
Restore the original text based on the above mapping:
{masked_text}"""
            }
        ]
        
        try:
            restored_text = self._call_model(messages)
            return restored_text
        except Exception as e:
            logger.error("HaS Seek 失败: %s", e)
            return masked_text
    
    def extract_entities_for_ui(
        self, 
        text: str,
        entity_types: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        提取实体用于前端展示
        
        Returns:
            [{"id", "text", "type", "start", "end", "tag", "source"}]
        """
        # 先做NER
        ner_result = self.ner(text, entity_types)
        
        entities = []
        entity_id = 0
        
        for entity_type, entity_list in ner_result.items():
            for entity_text in entity_list:
                # 在原文中查找位置
                start = text.find(entity_text)
                if start >= 0:
                    entities.append({
                        "id": f"has_{entity_id}",
                        "text": entity_text,
                        "type": self._map_type_to_english(entity_type),
                        "start": start,
                        "end": start + len(entity_text),
                        "tag": None,  # 标签在hide时生成
                        "source": "has",
                        "confidence": 0.95,
                    })
                    entity_id += 1
        
        # 按位置排序
        entities.sort(key=lambda e: e["start"])
        
        return entities
    
    def _map_type_to_english(self, chinese_type: str) -> str:
        """中文类型映射到英文（使用统一数据源）"""
        from app.models.type_mapping import cn_to_id
        return cn_to_id(chinese_type)
    
    def is_available(self) -> bool:
        """检查 NER 后端是否可用（llama.cpp /v1/models）。"""
        from app.core.config import get_has_health_check_url
        url = get_has_health_check_url()
        import httpx
        try:
            response = httpx.get(url, timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False


# 全局客户端实例
has_client = HaSClient()
