"""
图像识别类型管理 API
用于视觉模型的敏感类型配置（与文本类型分离）

基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》国家标准设计
针对图像/扫描件中常见的敏感信息类型
"""
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from enum import Enum
import uuid

router = APIRouter()


class IdentifierCategory(str, Enum):
    """
    标识符类别 - 基于 GB/T 37964-2019
    """
    DIRECT = "direct"           # 直接标识符
    QUASI = "quasi"             # 准标识符
    SENSITIVE = "sensitive"     # 敏感属性


class VisionTypeConfig(BaseModel):
    """
    图像识别类型配置
    遵循 GB/T 37964-2019 标识符分类体系
    """
    id: str = Field(..., description="唯一ID")
    name: str = Field(..., description="显示名称")
    category: IdentifierCategory = Field(
        default=IdentifierCategory.QUASI,
        description="标识符类别（GB/T 37964-2019）"
    )
    description: Optional[str] = Field(None, description="语义描述")
    examples: List[str] = Field(default_factory=list, description="示例文本")
    color: str = Field(default="#6B7280", description="前端显示颜色")
    enabled: bool = Field(default=True, description="是否启用")
    order: int = Field(default=100, description="排序权重")
    risk_level: int = Field(default=3, description="重标识风险等级 1-5")


class CreateVisionTypeRequest(BaseModel):
    name: str
    description: Optional[str] = None
    examples: List[str] = []
    color: str = "#6B7280"


class UpdateVisionTypeRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    examples: Optional[List[str]] = None
    color: Optional[str] = None
    enabled: Optional[bool] = None
    order: Optional[int] = None


# =============================================================================
# 预置图像识别类型 - 基于 GB/T 37964-2019
# 针对扫描件、图片中常见的敏感信息区域
# =============================================================================

PRESET_VISION_TYPES: Dict[str, VisionTypeConfig] = {
    
    # =========================================================================
    # 直接标识符区域
    # =========================================================================
    
    "PERSON": VisionTypeConfig(
        id="PERSON",
        name="姓名/签名",
        category=IdentifierCategory.DIRECT,
        description="人名文字、手写签名、印章签名等。属于直接标识符。",
        examples=["张三", "李四", "签名区域", "印章"],
        color="#3B82F6",
        order=1,
        risk_level=5,
    ),
    "SIGNATURE": VisionTypeConfig(
        id="SIGNATURE",
        name="手写签名",
        category=IdentifierCategory.DIRECT,
        description="手写签名区域。属于直接标识符，具有法律效力。",
        examples=["签名", "签字", "手签"],
        color="#2563EB",
        order=2,
        risk_level=5,
    ),
    "FINGERPRINT": VisionTypeConfig(
        id="FINGERPRINT",
        name="指纹/手印",
        category=IdentifierCategory.DIRECT,
        description="指纹、手印区域。属于生物特征直接标识符。",
        examples=["指纹", "手印", "捺印"],
        color="#1D4ED8",
        order=3,
        risk_level=5,
    ),
    "SEAL": VisionTypeConfig(
        id="SEAL",
        name="印章",
        category=IdentifierCategory.DIRECT,
        description="个人印章、公章、合同章等。可识别个人或机构身份。",
        examples=["个人章", "公章", "合同专用章", "财务章"],
        color="#1E40AF",
        order=4,
        risk_level=4,
    ),
    "ID_CARD": VisionTypeConfig(
        id="ID_CARD",
        name="身份证号",
        category=IdentifierCategory.DIRECT,
        description="身份证号码文字区域。属于直接标识符，最高保护级别。",
        examples=["110101199003071234", "11010119900307123X"],
        color="#EF4444",
        order=5,
        risk_level=5,
    ),
    "ID_CARD_PHOTO": VisionTypeConfig(
        id="ID_CARD_PHOTO",
        name="证件照片",
        category=IdentifierCategory.DIRECT,
        description="身份证、护照等证件上的照片区域。属于生物特征直接标识符。",
        examples=["证件照", "头像照片"],
        color="#DC2626",
        order=6,
        risk_level=5,
    ),
    "PHONE": VisionTypeConfig(
        id="PHONE",
        name="电话号码",
        category=IdentifierCategory.DIRECT,
        description="手机号码、固定电话号码区域。属于直接标识符。",
        examples=["13812345678", "010-88889999", "021-12345678"],
        color="#F97316",
        order=7,
        risk_level=5,
    ),
    "EMAIL": VisionTypeConfig(
        id="EMAIL",
        name="电子邮箱",
        category=IdentifierCategory.DIRECT,
        description="电子邮件地址区域。属于直接标识符。",
        examples=["user@example.com", "zhangsan@company.cn"],
        color="#06B6D4",
        order=8,
        risk_level=4,
    ),
    "BANK_CARD": VisionTypeConfig(
        id="BANK_CARD",
        name="银行卡号",
        category=IdentifierCategory.DIRECT,
        description="银行卡号码区域。属于直接标识符，涉及财务安全。",
        examples=["6222020200012345678", "4367421234567890"],
        color="#EC4899",
        order=9,
        risk_level=5,
    ),
    "SOCIAL_SECURITY": VisionTypeConfig(
        id="SOCIAL_SECURITY",
        name="社保卡号",
        category=IdentifierCategory.DIRECT,
        description="社保卡、医保卡号码区域。属于直接标识符。",
        examples=["社保号", "医保号"],
        color="#B91C1C",
        order=10,
        risk_level=5,
    ),
    
    # =========================================================================
    # 准标识符区域
    # =========================================================================
    
    "ADDRESS": VisionTypeConfig(
        id="ADDRESS",
        name="地址",
        category=IdentifierCategory.QUASI,
        description="详细地址区域。精确地址可能成为直接标识符。",
        examples=["北京市朝阳区某某路123号", "住址：某某小区1栋101"],
        color="#6366F1",
        order=20,
        risk_level=4,
    ),
    "BIRTH_DATE": VisionTypeConfig(
        id="BIRTH_DATE",
        name="出生日期",
        category=IdentifierCategory.QUASI,
        description="出生年月日区域。属于准标识符。",
        examples=["1990年3月7日", "出生日期"],
        color="#84CC16",
        order=21,
        risk_level=3,
    ),
    "LICENSE_PLATE": VisionTypeConfig(
        id="LICENSE_PLATE",
        name="车牌号",
        category=IdentifierCategory.QUASI,
        description="机动车号牌区域。属于准标识符。",
        examples=["京A12345", "沪B67890"],
        color="#14B8A6",
        order=22,
        risk_level=3,
    ),
    "CASE_NUMBER": VisionTypeConfig(
        id="CASE_NUMBER",
        name="案件编号",
        category=IdentifierCategory.QUASI,
        description="法院案件编号区域。属于准标识符。",
        examples=["(2024)京01民初123号"],
        color="#8B5CF6",
        order=23,
        risk_level=3,
    ),
    "CONTRACT_NO": VisionTypeConfig(
        id="CONTRACT_NO",
        name="合同编号",
        category=IdentifierCategory.QUASI,
        description="合同、协议编号区域。属于准标识符。",
        examples=["合同编号：HT-2024-001"],
        color="#64748B",
        order=24,
        risk_level=2,
    ),
    
    # =========================================================================
    # 敏感属性区域
    # =========================================================================
    
    "AMOUNT": VisionTypeConfig(
        id="AMOUNT",
        name="金额",
        category=IdentifierCategory.SENSITIVE,
        description="金额数字区域，包括阿拉伯数字和大写金额。属于敏感属性。",
        examples=["人民币10万元", "￥500,000.00", "伍拾万元整"],
        color="#F43F5E",
        order=30,
        risk_level=3,
    ),
    "MEDICAL_INFO": VisionTypeConfig(
        id="MEDICAL_INFO",
        name="医疗信息",
        category=IdentifierCategory.SENSITIVE,
        description="诊断结果、病历信息等医疗敏感信息区域。",
        examples=["诊断", "病历", "处方"],
        color="#F87171",
        order=31,
        risk_level=4,
    ),
    "QR_CODE": VisionTypeConfig(
        id="QR_CODE",
        name="二维码",
        category=IdentifierCategory.QUASI,
        description="二维码区域，可能包含敏感链接或个人信息。",
        examples=["二维码", "条形码"],
        color="#A855F7",
        order=32,
        risk_level=3,
    ),
    "BARCODE": VisionTypeConfig(
        id="BARCODE",
        name="条形码",
        category=IdentifierCategory.QUASI,
        description="条形码区域，可能包含编码信息。",
        examples=["条形码", "一维码"],
        color="#7C3AED",
        order=33,
        risk_level=2,
    ),
}


vision_types_db: Dict[str, VisionTypeConfig] = PRESET_VISION_TYPES.copy()


@router.get("/vision-types", response_model=List[VisionTypeConfig])
async def get_vision_types(enabled_only: bool = True):
    """获取图像识别类型列表"""
    types = list(vision_types_db.values())
    if enabled_only:
        types = [t for t in types if t.enabled]
    return sorted(types, key=lambda t: t.order)


@router.post("/vision-types", response_model=VisionTypeConfig)
async def create_vision_type(request: CreateVisionTypeRequest):
    """创建新的图像识别类型"""
    type_id = f"vision_{uuid.uuid4().hex[:8]}"
    new_type = VisionTypeConfig(
        id=type_id,
        name=request.name,
        description=request.description,
        examples=request.examples,
        color=request.color,
        enabled=True,
        order=200,
    )
    vision_types_db[type_id] = new_type
    return new_type


@router.put("/vision-types/{type_id}", response_model=VisionTypeConfig)
async def update_vision_type(type_id: str, request: UpdateVisionTypeRequest):
    """更新图像识别类型"""
    if type_id not in vision_types_db:
        raise HTTPException(status_code=404, detail="类型不存在")
    existing = vision_types_db[type_id]
    update_data = request.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(existing, key, value)
    vision_types_db[type_id] = existing
    return existing


@router.delete("/vision-types/{type_id}")
async def delete_vision_type(type_id: str):
    """删除图像识别类型（预置不可删除）"""
    if type_id not in vision_types_db:
        raise HTTPException(status_code=404, detail="类型不存在")
    if type_id in PRESET_VISION_TYPES:
        raise HTTPException(status_code=400, detail="预置类型不能删除，只能禁用")
    del vision_types_db[type_id]
    return {"message": "删除成功"}


@router.post("/vision-types/{type_id}/toggle")
async def toggle_vision_type(type_id: str):
    """切换图像识别类型启用状态"""
    if type_id not in vision_types_db:
        raise HTTPException(status_code=404, detail="类型不存在")
    vision_types_db[type_id].enabled = not vision_types_db[type_id].enabled
    return {"enabled": vision_types_db[type_id].enabled}


@router.post("/vision-types/reset")
async def reset_vision_types():
    """重置图像识别类型为默认配置"""
    global vision_types_db
    vision_types_db = PRESET_VISION_TYPES.copy()
    return {"message": "已重置为默认配置"}


def get_enabled_vision_types() -> List[VisionTypeConfig]:
    return [t for t in vision_types_db.values() if t.enabled]
