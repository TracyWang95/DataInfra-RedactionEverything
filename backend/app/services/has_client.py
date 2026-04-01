"""
HaS (Hide And Seek) 本地模型客户端
使用 llama.cpp 的 OpenAI 兼容接口

推荐模型：xuanwulab/HaS_Text_0209_0.6B_Q4（GGUF：HaS_Text_0209_0.6B_Q4_K_M.gguf）
NER / Hide / Pair / Seek 的 user 提示须与模型卡模板逐字一致（勿在 NER 首段插入额外说明）。

功能：
1. ner - 敏感实体识别
2. hide - 标签化脱敏
3. pair - 提取标签映射
4. seek - 标签还原
"""

import json
import logging
import re
import httpx

logger = logging.getLogger(__name__)
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field

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
        # 注意：_history_mapping 不再作为实例级共享状态
        # 每次 hide() 调用应显式传入或创建新的 mapping，避免并发请求互相污染
        import threading
        self._history_lock = threading.Lock()
        self._history_mapping: Dict[str, List[str]] = {}  # 仅用于单请求内的映射

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
        """调用 OpenAI 兼容接口（llama.cpp HaS 或 Ollama）。"""
        from app.core.config import is_ner_ollama, get_ollama_model
        base = self._effective_base_url()
        payload: Dict[str, Any] = {"messages": messages}
        if is_ner_ollama():
            payload["model"] = get_ollama_model()
            payload["temperature"] = 0.1
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
    
    def reset_history(self):
        """重置历史映射"""
        with self._history_lock:
            self._history_mapping = {}

    def create_session_mapping(self) -> Dict[str, List[str]]:
        """创建一个独立的会话映射（用于并发安全的批处理）"""
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
        use_history: bool = True
    ) -> Tuple[str, Dict[str, List[str]]]:
        """
        使用Hide能力进行标签化脱敏
        
        流程：
        1. 先调用NER识别实体
        2. 再调用Hide替换为结构化标签
        
        Args:
            text: 待脱敏文本
            entity_types: 要识别的实体类型
            use_history: 是否使用历史映射（保持指代一致性）
            
        Returns:
            (脱敏后文本, 映射表)
        """
        types = entity_types or self.LEGAL_ENTITY_TYPES
        types_str = json.dumps(types, ensure_ascii=False)
        
        # Step 1: NER识别
        ner_result = self.ner(text, types)
        if not ner_result or all(len(v) == 0 for v in ner_result.values()):
            return text, {}
        
        ner_json = json.dumps(ner_result, ensure_ascii=False)
        
        # Step 2: Hide 第 1 轮与 ner() 使用相同 NER 模板
        ner_prompt = f"""Recognize the following entity types in the text.
Specified types:{types_str}
<text>{text}</text>"""
        
        # 使用线程锁安全读取历史映射
        with self._history_lock:
            history_snapshot = dict(self._history_mapping) if use_history else {}
        if use_history and history_snapshot:
            # 带历史映射
            history_json = json.dumps(history_snapshot, ensure_ascii=False)
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
            mapping = self.pair(text, masked_text)
            
            # 线程安全更新历史映射
            with self._history_lock:
                for tag, values in mapping.items():
                    if tag not in self._history_mapping:
                        self._history_mapping[tag] = []
                    for v in values:
                        if v not in self._history_mapping[tag]:
                            self._history_mapping[tag].append(v)
            
            return masked_text, mapping
            
        except Exception as e:
            logger.error("HaS Hide 失败: %s", e)
            return text, {}
    
    def pair(self, original_text: str, masked_text: str) -> Dict[str, List[str]]:
        """
        使用Pair能力提取标签映射
        
        Args:
            original_text: 原始文本
            masked_text: 脱敏后文本
            
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
            masked_text: 脱敏后的文本
            mapping: 映射表，默认使用历史映射
            
        Returns:
            还原后的原文
        """
        use_mapping = mapping or self._history_mapping
        if not use_mapping:
            return masked_text
        
        mapping_json = json.dumps(use_mapping, ensure_ascii=False)
        
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
        """检查 NER 后端是否可用（llama.cpp /v1/models 或 Ollama /api/tags）。"""
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
