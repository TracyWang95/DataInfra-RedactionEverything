"""
HaS (Hide And Seek) 本地脱敏模型服务
基于 xuanwulab/HaS_Text_0209_0.6B_Q4（GGUF：HaS_Text_0209_0.6B_Q4_K_M.gguf）
通过 llama.cpp OpenAI 兼容接口调用

功能：
1. NER 敏感实体识别
2. 结构化语义标签脱敏
3. 指代消解（同一实体用相同ID）
4. 支持信息还原
"""

import re
from typing import Optional, Dict, List
from app.models.schemas import Entity
from app.services.has_client import has_client, HaSClient
from typing import Any

# 类型别名，兼容 EntityTypeConfig 和 CustomEntityType
EntityTypeConfig = Any


class HaSService:
    """HaS NER 服务 - 用于混合 NER 架构"""
    
    # 中文类型到实体类型ID的映射 - 基于 GB/T 37964-2019
    TYPE_MAPPING_CN_TO_ID = {
        # 直接标识符
        "人名": "PERSON", "姓名": "PERSON",
        "身份证号": "ID_CARD", "身份证": "ID_CARD",
        "护照号": "PASSPORT",
        "电话号码": "PHONE", "联系方式": "PHONE", "手机号": "PHONE",
        "电子邮箱": "EMAIL", "邮箱": "EMAIL",
        "银行卡号": "BANK_CARD",
        "银行账号": "BANK_ACCOUNT", "账号": "BANK_ACCOUNT",
        "开户行": "BANK_NAME", "开户银行": "BANK_NAME", "银行名称": "BANK_NAME",
        "社保号": "SOCIAL_SECURITY",
        # 准标识符
        "公司名称": "COMPANY", "公司": "COMPANY", "企业": "COMPANY",
        "甲方": "COMPANY", "乙方": "COMPANY", "丙方": "COMPANY",
        "组织": "ORG", "机构名称": "ORG",
        "地址": "ADDRESS", "详细地址": "ADDRESS",
        "出生日期": "BIRTH_DATE",
        "日期": "DATE",
        "车牌号": "LICENSE_PLATE",
        "案件编号": "CASE_NUMBER",
        "合同编号": "CONTRACT_NO",
        "统一社会信用代码": "COMPANY_CODE",
        # 敏感属性
        "金额": "AMOUNT",
        # 法律文书
        "当事人": "LEGAL_PARTY",
        "律师": "LAWYER",
        "法官": "JUDGE",
        "证人": "WITNESS",
    }
    
    # 实体类型ID到中文的映射
    TYPE_MAPPING_ID_TO_CN = {v: k for k, v in TYPE_MAPPING_CN_TO_ID.items()}
    
    def __init__(self, base_url: Optional[str] = None):
        self.client = HaSClient(base_url=base_url)
    
    def is_available(self) -> bool:
        """检查 HaS 服务是否可用"""
        return self.client.is_available()
    
    def _convert_entity_types_to_chinese(
        self, 
        entity_types: List[EntityTypeConfig]
    ) -> List[str]:
        """将实体类型配置转换为 HaS 需要的中文类型列表"""
        chinese_types = []
        for et in entity_types:
            # 优先使用映射
            if et.id in self.TYPE_MAPPING_ID_TO_CN:
                chinese_types.append(self.TYPE_MAPPING_ID_TO_CN[et.id])
            else:
                # 自定义类型使用名称
                chinese_types.append(et.name)
        return chinese_types
    
    async def extract_entities(
        self, 
        content: str, 
        entity_types: List[EntityTypeConfig]
    ) -> List[Entity]:
        """
        使用 HaS 模型进行 NER 识别
        
        Args:
            content: 待识别文本
            entity_types: 要识别的实体类型配置
            
        Returns:
            识别到的实体列表
        """
        if not content.strip():
            return []
        
        # 转换实体类型为中文
        chinese_types = self._convert_entity_types_to_chinese(entity_types)
        
        try:
            # 调用 HaS NER
            ner_result = self.client.ner(content, chinese_types)
            
            if not ner_result:
                return []
            
            # 转换为 Entity 对象
            entities = []
            entity_id = 0
            coref_map: Dict[str, str] = {}  # text:type -> coref_id
            
            for chinese_type, entity_list in ner_result.items():
                # 映射中文类型到英文ID
                entity_type_id = self.TYPE_MAPPING_CN_TO_ID.get(chinese_type, chinese_type.upper())
                
                for entity_text in entity_list:
                    if not entity_text:
                        continue
                    
                    # 在原文中查找所有出现位置
                    start = 0
                    while True:
                        pos = content.find(entity_text, start)
                        if pos < 0:
                            break
                        
                        # 指代消解：相同文本+类型使用相同 coref_id
                        coref_key = f"{entity_text}:{entity_type_id}"
                        if coref_key not in coref_map:
                            coref_map[coref_key] = f"coref_{len(coref_map)}"
                        
                        entities.append(Entity(
                            id=f"has_{entity_id}",
                            text=entity_text,
                            type=entity_type_id,
                            start=pos,
                            end=pos + len(entity_text),
                            page=1,
                            confidence=0.95,
                            source="has",
                            coref_id=coref_map[coref_key],
                        ))
                        
                        entity_id += 1
                        start = pos + len(entity_text)
            
            # 按位置排序
            entities.sort(key=lambda e: e.start)
            
            return entities
            
        except Exception as e:
            print(f"HaS NER 失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def hide_text(
        self, 
        content: str,
        entity_types: List[EntityTypeConfig]
    ) -> tuple[str, Dict[str, List[str]]]:
        """
        使用 HaS 进行结构化语义标签脱敏
        
        Args:
            content: 原始文本
            entity_types: 要脱敏的实体类型
            
        Returns:
            (脱敏后文本, 映射表)
        """
        chinese_types = self._convert_entity_types_to_chinese(entity_types)
        
        try:
            masked_text, mapping = self.client.hide(content, chinese_types)
            return masked_text, mapping
        except Exception as e:
            print(f"HaS Hide 失败: {e}")
            return content, {}
    
    async def extract_entities_with_hide(
        self,
        content: str,
        entity_types: List[EntityTypeConfig],
    ) -> List[Entity]:
        """
        使用 HaS Hide 模式识别实体（带指代消解）

        基于结构化语义标签解析出实体位置和 coref_id。
        """
        if not content.strip():
            return []

        chinese_types = self._convert_entity_types_to_chinese(entity_types)

        try:
            masked_text, mapping = self.client.hide(
                content, chinese_types, use_history=True
            )
        except Exception as e:
            print(f"HaS Hide 模式失败: {e}")
            return []

        if not mapping:
            return []

        entities: List[Entity] = []
        used_positions: set[tuple[int, int]] = set()
        entity_id = 0

        def find_next_occurrence(text: str) -> Optional[int]:
            start = 0
            while True:
                pos = content.find(text, start)
                if pos < 0:
                    return None
                end = pos + len(text)
                overlaps = any(not (end <= s or pos >= e) for s, e in used_positions)
                if not overlaps:
                    return pos
                start = pos + len(text)

        for tag_info in HaSTagParser.find_all_tags(masked_text):
            tag = tag_info.get("tag")
            if not tag:
                continue

            candidates = mapping.get(tag, [])
            if not candidates:
                continue

            # 使用第一个可定位的原文
            found_text = None
            found_pos = None
            for candidate in candidates:
                if not candidate:
                    continue
                pos = find_next_occurrence(candidate)
                if pos is not None:
                    found_text = candidate
                    found_pos = pos
                    break

            if found_text is None or found_pos is None:
                continue

            entity_type_cn = tag_info.get("entity_type") or "自定义"
            entity_type_id = self.TYPE_MAPPING_CN_TO_ID.get(
                entity_type_cn, entity_type_cn.upper()
            )

            start = found_pos
            end = found_pos + len(found_text)
            used_positions.add((start, end))

            entities.append(Entity(
                id=f"has_hide_{entity_id}",
                text=found_text,
                type=entity_type_id,
                start=start,
                end=end,
                page=1,
                confidence=0.96,
                source="has",
                coref_id=tag,
            ))
            entity_id += 1

        entities.sort(key=lambda e: e.start)
        return entities

    async def seek_text(
        self,
        masked_text: str,
        mapping: Optional[Dict[str, List[str]]] = None
    ) -> str:
        """
        使用 HaS 进行标签还原
        
        Args:
            masked_text: 脱敏后的文本
            mapping: 标签映射表
            
        Returns:
            还原后的原文
        """
        try:
            restored = self.client.seek(masked_text, mapping)
            return restored
        except Exception as e:
            print(f"HaS Seek 失败: {e}")
            return masked_text


# 标签解析工具
class HaSTagParser:
    """HaS 结构化语义标签解析器"""
    
    # 标签正则: <类型[序号].子类型.属性>
    TAG_PATTERN = re.compile(r'<([^>\[]+)\[(\d+)\]\.([^>\.]+)\.([^>]+)>')
    
    @classmethod
    def parse_tag(cls, tag: str) -> Optional[Dict]:
        """解析标签"""
        match = cls.TAG_PATTERN.match(tag)
        if match:
            return {
                "entity_type": match.group(1),
                "entity_id": match.group(2),
                "sub_type": match.group(3),
                "attribute": match.group(4),
            }
        return None
    
    @classmethod
    def find_all_tags(cls, text: str) -> List[Dict]:
        """在文本中查找所有标签"""
        tags = []
        for match in cls.TAG_PATTERN.finditer(text):
            tags.append({
                "tag": match.group(),
                "start": match.start(),
                "end": match.end(),
                **cls.parse_tag(match.group()),
            })
        return tags
    
    @classmethod
    def generate_tag(
        cls, 
        entity_type: str, 
        entity_id: int,
        sub_type: str,
        attribute: str
    ) -> str:
        """生成标签"""
        return f"<{entity_type}[{entity_id:03d}].{sub_type}.{attribute}>"


# 全局服务实例
has_service = HaSService()
