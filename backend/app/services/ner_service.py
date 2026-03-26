"""
命名实体识别 (NER) 服务
文本NER已迁移至 HaS + 正则（hybrid_ner_service）
此文件保留向后兼容的接口
"""
from typing import Optional, List
from app.models.schemas import Entity, CustomEntityType
from app.services.hybrid_ner_service import perform_hybrid_ner


class NERService:
    """NER 识别服务 - 使用 HaS + 正则"""
    
    async def extract_entities(
        self,
        content: str,
        pages: Optional[list[str]] = None,
        builtin_types: Optional[list[str]] = None,
        custom_types: Optional[list[CustomEntityType]] = None,
    ) -> list[Entity]:
        """
        从文本中提取实体（使用 HaS + 正则）
        
        Args:
            content: 文本内容
            pages: 分页内容（如果有）
            builtin_types: 要识别的内置实体类型列表
            custom_types: 要识别的自定义实体类型列表
            
        Returns:
            识别到的实体列表
        """
        if not content.strip():
            return []
        
        # 构建类型配置（兼容 hybrid_ner_service 格式）
        from app.api.entity_types import get_enabled_types
        entity_types = get_enabled_types()
        
        # 调用混合识别
        return await perform_hybrid_ner(content, entity_types)
    
    async def extract_entities_with_types(
        self,
        content: str,
        entity_types: List,  # List[EntityTypeConfig]
    ) -> list[Entity]:
        """
        使用指定的实体类型配置进行识别
        
        Args:
            content: 文本内容
            entity_types: 实体类型配置列表
            
        Returns:
            识别到的实体列表
        """
        if not content.strip():
            return []
        
        # 调用混合识别
        return await perform_hybrid_ner(content, entity_types)
