"""
HaS (Hide And Seek) 本地模型客户端
使用 llama.cpp 的 OpenAI 兼容接口

模型：xuanwulab/HaS_4.0_0.6B_GGUF

功能：
1. ner - 敏感实体识别
2. hide - 标签化脱敏
3. pair - 提取标签映射
4. seek - 标签还原
"""

import json
import re
import httpx
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


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
        self.base_url = (base_url or settings.HAS_BASE_URL).rstrip('/')
        self.model_name = getattr(settings, 'HAS_MODEL_NAME', 'glm') # 默认占位符，如果没设则不影响 llama.cpp
        self.timeout = httpx.Timeout(timeout or settings.HAS_TIMEOUT)
        self._history_mapping: Dict[str, List[str]] = {}  # 历史映射记录
    
    def _call_model(self, messages: List[Dict]) -> str:
        # 配置 httpx 客户端强行忽略各类代理 (避免 mac 下 localhost 被拦截导致 502)
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            payload = {
                "model": self.model_name,
                "messages": messages,
                "temperature": 0.1, # 强制低温度以保留实体原本的稳定输出
            }
            response = client.post(
                f"{self.base_url}/chat/completions",
                json=payload
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
    
    def reset_history(self):
        """重置历史映射"""
        self._history_mapping = {}
    
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
        
        # 构建更精确的 prompt
        prompt = f"""Recognize the following entity types in the text.
Specified types:{types_str}

Important rules:
- For "人名": Only extract actual person names (e.g. 张三, 李四, 王小明). Do NOT extract role titles like 法定代表人, 代理人, 原告, 被告, 委托人, 负责人, etc.
- Be precise: only return entities that exactly match the specified types.

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
            return result
        except json.JSONDecodeError:
            # 尝试从响应中提取JSON
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
            return {}
        except Exception as e:
            print(f"HaS NER 失败: {e}")
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
        
        # Step 2: Hide替换
        # 构建与 ner() 一致的精确 prompt
        ner_prompt = f"""Recognize the following entity types in the text.
Specified types:{types_str}

Important rules:
- For "人名": Only extract actual person names (e.g. 张三, 李四, 王小明). Do NOT extract role titles like 法定代表人, 代理人, 原告, 被告, 委托人, 负责人, etc.
- Be precise: only return entities that exactly match the specified types.

<text>{text}</text>"""
        
        if use_history and self._history_mapping:
            # 带历史映射
            history_json = json.dumps(self._history_mapping, ensure_ascii=False)
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
            
            # 更新历史映射
            for tag, values in mapping.items():
                if tag not in self._history_mapping:
                    self._history_mapping[tag] = []
                for v in values:
                    if v not in self._history_mapping[tag]:
                        self._history_mapping[tag].append(v)
            
            return masked_text, mapping
            
        except Exception as e:
            print(f"HaS Hide 失败: {e}")
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
                except:
                    pass
            return {}
        except Exception as e:
            print(f"HaS Pair 失败: {e}")
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
            print(f"HaS Seek 失败: {e}")
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
        """中文类型映射到英文"""
        mapping = {
            "人名": "PERSON",
            "组织": "ORG",
            "地址": "ADDRESS",
            "职务": "TITLE",
            "联系方式": "PHONE",
            "身份证号": "ID_CARD",
            "银行卡号": "BANK_CARD",
            "案件编号": "CASE_NUMBER",
            "金额": "MONEY",
            "日期": "DATE",
            "合同编号": "CONTRACT_NO",
            "邮箱": "EMAIL",
            "文件": "DOCUMENT",
            "账号": "ACCOUNT",
            "密码": "PASSWORD",
        }
        return mapping.get(chinese_type, chinese_type.upper())
    
    def is_available(self) -> bool:
        """检查HaS服务是否可用"""
        try:
            with httpx.Client(timeout=5.0) as client:
                # llama.cpp server 使用 /v1/models 端点
                response = client.get(f"{self.base_url}/models")
                if response.status_code == 200:
                    return True
        except:
            pass
        
        try:
            # 备选：尝试 /health 端点
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.base_url.replace('/v1', '')}/health")
                return response.status_code == 200
        except:
            return False


# 全局客户端实例
has_client = HaSClient()
