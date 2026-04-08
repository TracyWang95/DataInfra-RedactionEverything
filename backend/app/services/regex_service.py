"""
正则表达式识别服务
用于识别有固定模式的敏感信息，准确率接近100%
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class RegexPattern:
    """正则模式配置"""
    pattern: str
    priority: int = 1  # 优先级，数字越大越优先
    validator: Optional[callable] = None  # 可选的校验函数


# 预定义的正则模式
BUILTIN_PATTERNS: Dict[str, List[RegexPattern]] = {
    # 身份证号 - 15位或18位
    "ID_CARD": [
        RegexPattern(
            pattern=r'\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b',
            priority=10,
        ),
        RegexPattern(
            pattern=r'\b[1-9]\d{5}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}\b',
            priority=9,
        ),
    ],
    
    # 手机号 - 中国大陆
    "PHONE": [
        RegexPattern(
            pattern=r'\b1[3-9]\d{9}\b',
            priority=10,
        ),
        # 带区号的座机
        RegexPattern(
            pattern=r'\b(?:0\d{2,3}[-\s]?)?\d{7,8}\b',
            priority=5,
        ),
    ],
    
    # 银行卡号 - 16-19位数字
    "BANK_CARD": [
        RegexPattern(
            pattern=r'\b(?:62|4|5)\d{14,17}\b',
            priority=10,
        ),
    ],
    
    # 邮箱
    "EMAIL": [
        RegexPattern(
            pattern=r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            priority=10,
        ),
    ],
    
    # 案件编号 - 常见格式
    "CASE_NUMBER": [
        # (2024)京01民初123号
        RegexPattern(
            pattern=r'[\(（]\d{4}[\)）][京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领A-Z]{1,4}\d{0,4}[民刑行执破知赔财商][初终复再抗申裁监督撤]?\d+号',
            priority=10,
        ),
        # 兼容更多格式
        RegexPattern(
            pattern=r'[\(（]\d{4}[\)）][A-Za-z\u4e00-\u9fff]+\d*[A-Za-z\u4e00-\u9fff]*\d+号',
            priority=8,
        ),
    ],
    
    # 日期 - 多种格式
    "DATE": [
        # 2024年1月1日
        RegexPattern(
            pattern=r'\d{4}年\d{1,2}月\d{1,2}日',
            priority=10,
        ),
        # 2024-01-01 或 2024/01/01
        RegexPattern(
            pattern=r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',
            priority=9,
        ),
    ],
    
    # 金额
    "MONEY": [
        # 人民币格式
        RegexPattern(
            pattern=r'(?:人民币|￥|¥|RMB)?\s*[\d,]+(?:\.\d{1,2})?\s*(?:元|万元)?',
            priority=8,
        ),
        # 纯数字金额后跟单位
        RegexPattern(
            pattern=r'\d[\d,]*(?:\.\d{1,2})?\s*(?:元|万元|亿元)',
            priority=9,
        ),
    ],
    
    # 车牌号
    "LICENSE_PLATE": [
        RegexPattern(
            pattern=r'[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领][A-Z][A-Z0-9]{5,6}',
            priority=10,
        ),
    ],
    
    # IP地址
    "IP_ADDRESS": [
        RegexPattern(
            pattern=r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b',
            priority=10,
        ),
    ],
    
    # 网址
    "URL": [
        RegexPattern(
            pattern=r'https?://[^\s<>"{}|\\^`\[\]]+',
            priority=10,
        ),
    ],
}


class RegexService:
    """正则识别服务"""
    
    def __init__(self):
        self.patterns = BUILTIN_PATTERNS.copy()
        # 预编译正则
        self._compiled: Dict[str, List[tuple]] = {}
        self._compile_patterns()
    
    def _compile_patterns(self):
        """预编译正则表达式"""
        for entity_type, patterns in self.patterns.items():
            self._compiled[entity_type] = [
                (re.compile(p.pattern, re.IGNORECASE), p.priority, p.validator)
                for p in patterns
            ]
    
    def add_pattern(self, entity_type: str, pattern: str, priority: int = 5):
        """添加自定义正则模式"""
        if entity_type not in self.patterns:
            self.patterns[entity_type] = []
        
        self.patterns[entity_type].append(RegexPattern(pattern=pattern, priority=priority))
        
        # 重新编译
        self._compiled[entity_type] = [
            (re.compile(p.pattern, re.IGNORECASE), p.priority, p.validator)
            for p in self.patterns[entity_type]
        ]
    
    def extract(
        self,
        text: str,
        entity_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        从文本中提取匹配正则的实体
        
        Args:
            text: 待识别文本
            entity_types: 要识别的实体类型列表，None表示全部
            
        Returns:
            识别到的实体列表
        """
        entities = []
        seen_positions = set()  # 去重用
        
        types_to_check = entity_types or list(self._compiled.keys())
        
        for entity_type in types_to_check:
            if entity_type not in self._compiled:
                continue
            
            for compiled_pattern, priority, validator in self._compiled[entity_type]:
                for match in compiled_pattern.finditer(text):
                    start, end = match.start(), match.end()
                    matched_text = match.group()
                    
                    # 跳过已识别的位置
                    pos_key = (start, end)
                    if pos_key in seen_positions:
                        continue
                    
                    # 可选的校验
                    if validator and not validator(matched_text):
                        continue
                    
                    seen_positions.add(pos_key)
                    entities.append({
                        'id': f'regex_{entity_type}_{start}_{end}',
                        'text': matched_text,
                        'type': entity_type,
                        'start': start,
                        'end': end,
                        'confidence': 0.99,  # 正则匹配置信度很高
                        'source': 'regex',
                        'priority': priority,
                    })
        
        # 按位置排序
        entities.sort(key=lambda x: (x['start'], -x['priority']))
        
        # 处理重叠的匹配，保留优先级高的
        final_entities = []
        last_end = -1
        
        for entity in entities:
            if entity['start'] >= last_end:
                final_entities.append(entity)
                last_end = entity['end']
        
        return final_entities
    
    def get_supported_types(self) -> List[str]:
        """获取支持正则识别的类型"""
        return list(self.patterns.keys())


# 单例
regex_service = RegexService()
