"""
图像识别 Pipeline 配置 API
1. OCR + HaS：文字类敏感信息
2. HaS Image：端侧 YOLO 分割（8081 微服务），21 类隐私区域
"""
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum
from app.core.config import settings
from app.core.persistence import load_json, save_json
from app.core.has_image_categories import HAS_IMAGE_CATEGORIES, preset_type_color

router = APIRouter()


class PipelineMode(str, Enum):
    OCR_HAS = "ocr_has"
    HAS_IMAGE = "has_image"


class PipelineTypeConfig(BaseModel):
    """Pipeline 下的类型配置"""
    id: str = Field(..., description="唯一ID")
    name: str = Field(..., description="显示名称")
    description: Optional[str] = Field(None, description="语义描述/视觉提示")
    examples: List[str] = Field(default_factory=list, description="示例文本")
    color: str = Field(default="#6B7280", description="前端显示颜色")
    enabled: bool = Field(default=True, description="是否启用")
    order: int = Field(default=100, description="排序权重")


class PipelineConfig(BaseModel):
    """Pipeline 配置"""
    mode: PipelineMode = Field(..., description="Pipeline 模式")
    name: str = Field(..., description="显示名称")
    description: str = Field(..., description="描述")
    enabled: bool = Field(default=True, description="是否启用")
    types: List[PipelineTypeConfig] = Field(default_factory=list, description="该 Pipeline 下的类型配置")


# =============================================================================
# 预置 OCR + HaS Pipeline 类型
# 基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》
#
# 职责：PaddleOCR-VL 提取文字 + HaS 语义识别
# 适合：文字类敏感信息（人名、证件号、地址、金额等）
# =============================================================================
PRESET_OCR_HAS_TYPES: List[PipelineTypeConfig] = [
    # --- 直接标识符 ---
    PipelineTypeConfig(
        id="PERSON", name="姓名", description="自然人姓名、曾用名、昵称、绰号等",
        examples=["张三", "李明华", "老王", "John Smith"], color="#3B82F6", order=1,
    ),
    PipelineTypeConfig(
        id="ID_CARD", name="身份证号", description="18位/15位居民身份证号码",
        examples=["110101199003071234", "11010119900307123X"], color="#EF4444", order=2,
    ),
    PipelineTypeConfig(
        id="PASSPORT", name="护照号/通行证", description="护照、港澳通行证、台湾通行证号码",
        examples=["E12345678", "G87654321", "C12345678"], color="#DC2626", order=3,
    ),
    PipelineTypeConfig(
        id="PHONE", name="电话号码", description="手机号、固话、传真、400电话等",
        examples=["13812345678", "021-12345678", "400-123-4567"], color="#F97316", order=4,
    ),
    PipelineTypeConfig(
        id="EMAIL", name="电子邮箱", description="个人/工作/企业电子邮件地址",
        examples=["user@example.com", "hr@company.cn"], color="#06B6D4", order=5,
    ),
    PipelineTypeConfig(
        id="BANK_CARD", name="银行卡号", description="借记卡、信用卡卡号（16-19位）",
        examples=["6222020200012345678", "4367421234567890"], color="#EC4899", order=6,
    ),
    PipelineTypeConfig(
        id="BANK_ACCOUNT", name="银行账号", description="银行存款账号、对公账号、结算账号等数字账号",
        examples=["账号：1234567890123456789", "对公账号：11001234567890"], color="#DB2777", order=7,
    ),
    PipelineTypeConfig(
        id="BANK_NAME", name="开户行/银行名称", description="开户银行全称、支行名称、银行机构名",
        examples=["开户行：中国工商银行北京朝阳支行", "招商银行深圳南山支行", "中国建设银行XX分行营业部"],
        color="#7C3AED", order=7,
    ),
    PipelineTypeConfig(
        id="SOCIAL_SECURITY", name="社保号/公积金号", description="社保卡号、医保号、公积金账号",
        examples=["社保卡号：12345678901234567", "公积金账号：1234567890"], color="#B91C1C", order=8,
    ),
    PipelineTypeConfig(
        id="QQ_WECHAT_ID", name="社交账号", description="QQ号、微信号、微博、抖音等社交平台账号",
        examples=["QQ：123456789", "微信号：zhang_san_123"], color="#8B5CF6", order=9,
    ),
    
    # --- 准标识符 ---
    PipelineTypeConfig(
        id="COMPANY", name="公司/企业名称", 
        description="商业企业名称，含全称、简称、曾用名、品牌名。法律文书中常以甲方、乙方、丙方、发包方、承包方、出借人、借款人、出卖人、买受人、委托方、受托方、供应商、承揽方、转让方、受让方等代称出现。",
        examples=["深圳市腾讯计算机系统有限公司", "腾讯", "甲方", "乙方", "丙方", 
                  "发包方", "承包方", "出借人（公司）", "借款人（公司）", "出卖人", "买受人",
                  "委托方", "受托方", "供应商", "承揽方", "转让方", "受让方",
                  "XX有限责任公司", "XX股份有限公司", "XX集团", "XX合伙企业"],
        color="#059669", order=10,
    ),
    PipelineTypeConfig(
        id="ORG", name="机构/单位名称", description="政府机关、法院、检察院、公安局、律所、银行、医院、学校、社会团体等非企业机构（含简称）",
        examples=["某市中级人民法院", "某区人民检察院", "某市公安局XX分局", "某某律师事务所", 
                  "中国工商银行", "XX大学附属医院", "XX省高级人民法院"],
        color="#10B981", order=11,
    ),
    PipelineTypeConfig(
        id="ADDRESS", name="详细地址", description="省市区街道门牌号、小区楼栋、写字楼等完整地址",
        examples=["北京市朝阳区建国路88号", "住所地：XX大厦2001室"], color="#6366F1", order=11,
    ),
    PipelineTypeConfig(
        id="BIRTH_DATE", name="出生日期", description="出生年月日",
        examples=["1990年3月7日", "出生于1985-06-15"], color="#84CC16", order=12,
    ),
    PipelineTypeConfig(
        id="DATE", name="日期/时间", description="事件日期、签订日期、裁判日期等",
        examples=["2024年1月1日", "2024-01-01", "签订日期：2024/3/20"], color="#22D3EE", order=13,
    ),
    PipelineTypeConfig(
        id="LICENSE_PLATE", name="车牌号", description="机动车号牌",
        examples=["京A12345", "沪B67890", "粤AD12345"], color="#14B8A6", order=14,
    ),
    PipelineTypeConfig(
        id="CASE_NUMBER", name="案件编号", description="法院案号、仲裁案号、公证书编号",
        examples=["(2024)京01民初123号", "(2024)京仲裁字第001号"], color="#8B5CF6", order=15,
    ),
    PipelineTypeConfig(
        id="CONTRACT_NO", name="合同/文书编号", description="合同号、协议号、订单号、发票号、保单号等",
        examples=["HT-2024-001", "保单号：PICC2024001234"], color="#64748B", order=16,
    ),
    PipelineTypeConfig(
        id="COMPANY_CODE", name="信用代码/注册号", description="统一社会信用代码、营业执照注册号",
        examples=["91110000100000000X", "注册号：110000001234567"], color="#059669", order=17,
    ),
    
    # --- 敏感属性 ---
    PipelineTypeConfig(
        id="AMOUNT", name="金额/财务数据", description="涉案金额、工资、借款、赔偿、违约金、利息等",
        examples=["人民币10万元", "500,000元", "借款本金50万元", "违约金10%"], color="#F43F5E", order=20,
    ),
    PipelineTypeConfig(
        id="PROPERTY", name="财产/资产", description="房产证号、不动产权证号、股权、存款等",
        examples=["不动产权证号：京(2024)朝阳区001号", "持有30%股权"], color="#FB7185", order=21,
    ),
    
    # --- 法律文书特有 ---
    PipelineTypeConfig(
        id="LEGAL_PARTY", name="当事人", description="原告、被告、申请人、第三人、债权人、债务人等",
        examples=["原告张三", "被告某公司", "第三人赵六", "被执行人"], color="#F59E0B", order=30,
    ),
    PipelineTypeConfig(
        id="LAWYER", name="律师/代理人", description="律师、委托代理人、辩护人及所属律所",
        examples=["北京某律所律师张三", "辩护人：王某某"], color="#A855F7", order=31,
    ),
    PipelineTypeConfig(
        id="JUDGE", name="法官/书记员", description="审判长、审判员、书记员、人民陪审员、法官助理",
        examples=["审判长：张某某", "书记员：李某", "法官助理：孙某"], color="#0EA5E9", order=32,
    ),
    PipelineTypeConfig(
        id="WITNESS", name="证人/鉴定人", description="证人、鉴定人、评估人、翻译人员",
        examples=["证人张某", "鉴定人：王某某"], color="#78716C", order=33,
    ),
    
    # --- PaddleOCR-VL 视觉能力（OCR可识别印章文字） ---
    PipelineTypeConfig(
        id="SEAL", name="印章/公章", description="PaddleOCR-VL可精确识别印章内的文字内容（公章、合同章、法院印章、财务章等）",
        examples=["XX有限公司公章", "XX市中级人民法院", "合同专用章"], color="#DC143C", order=90,
    ),
]

# HaS Image 官方 21 类：id 为英文 Category，name/description 中文
PRESET_HAS_IMAGE_TYPES: List[PipelineTypeConfig] = [
    PipelineTypeConfig(
        id=c.id,
        name=c.name_zh,
        description=c.description_zh,
        examples=[],
        color=preset_type_color(c.class_id),
        order=c.class_id,
    )
    for c in HAS_IMAGE_CATEGORIES
]


# 预置 Pipeline 配置
PRESET_PIPELINES: Dict[str, PipelineConfig] = {
    "ocr_has": PipelineConfig(
        mode=PipelineMode.OCR_HAS,
        name="OCR + HaS (本地)",
        description="使用 PaddleOCR-VL 提取文字 + HaS 本地模型识别敏感信息。适合文字多的场景：微信聊天记录、PDF扫描件、合同文档等。完全离线，速度快。",
        enabled=True,
        types=PRESET_OCR_HAS_TYPES,
    ),
    "has_image": PipelineConfig(
        mode=PipelineMode.HAS_IMAGE,
        name="HaS Image (端侧)",
        description="本地 YOLO11 实例分割（8081 微服务），21 类隐私区域检测，与 OCR+HaS 并行后去重合并。",
        enabled=True,
        types=PRESET_HAS_IMAGE_TYPES,
    ),
}


def merge_pipeline_disk_snapshot(raw: Optional[dict]) -> Dict[str, PipelineConfig]:
    """
    将磁盘/快照中的 pipeline JSON 合并到预置配置上（不写盘）。
    用于启动加载与单元测试。
    """
    if isinstance(raw, dict):
        raw = {k: v for k, v in raw.items() if k != "glm_vision"}
    else:
        raw = None
    if not raw:
        return {k: v.model_copy(deep=True) for k, v in PRESET_PIPELINES.items()}
    pipelines: Dict[str, PipelineConfig] = {k: v.model_copy(deep=True) for k, v in PRESET_PIPELINES.items()}
    for key, value in raw.items():
        if key == "glm_vision":
            continue
        try:
            if isinstance(value, dict) and value.get("mode") == "glm_vision":
                value = {**value, "mode": "has_image"}
            loaded = PipelineConfig(**value)
        except Exception:
            continue
        if key in pipelines:
            base = pipelines[key]
            pipelines[key] = base.model_copy(update={
                "enabled": loaded.enabled,
                "types": loaded.types,
            })
        else:
            pipelines[key] = loaded
    return pipelines


def _load_pipelines() -> Dict[str, PipelineConfig]:
    raw = load_json(settings.PIPELINE_STORE_PATH, default=None)
    return merge_pipeline_disk_snapshot(raw if isinstance(raw, dict) else None)


def _persist_pipelines() -> None:
    save_json(settings.PIPELINE_STORE_PATH, pipelines_db)


# 内存存储（启动时从磁盘恢复）
pipelines_db: Dict[str, PipelineConfig] = _load_pipelines()
_persist_pipelines()


@router.get("/vision-pipelines", response_model=List[PipelineConfig])
async def get_pipelines(enabled_only: bool = False):
    """获取所有 Pipeline 配置"""
    pipelines = list(pipelines_db.values())
    if enabled_only:
        pipelines = [p for p in pipelines if p.enabled]
    return pipelines


@router.get("/vision-pipelines/{mode}", response_model=PipelineConfig)
async def get_pipeline(mode: str):
    """获取指定 Pipeline 配置"""
    if mode not in pipelines_db:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    return pipelines_db[mode]


@router.post("/vision-pipelines/{mode}/toggle")
async def toggle_pipeline(mode: str):
    """切换 Pipeline 启用状态"""
    if mode not in pipelines_db:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    pipelines_db[mode].enabled = not pipelines_db[mode].enabled
    return {"enabled": pipelines_db[mode].enabled}


@router.get("/vision-pipelines/{mode}/types", response_model=List[PipelineTypeConfig])
async def get_pipeline_types(mode: str, enabled_only: bool = True):
    """获取指定 Pipeline 的类型配置"""
    if mode not in pipelines_db:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    types = pipelines_db[mode].types
    if enabled_only:
        types = [t for t in types if t.enabled]
    return sorted(types, key=lambda t: t.order)


@router.post("/vision-pipelines/{mode}/types", response_model=PipelineTypeConfig)
async def add_pipeline_type(mode: str, request: PipelineTypeConfig):
    """添加 Pipeline 类型"""
    if mode not in pipelines_db:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    
    # 检查 ID 是否已存在
    existing_ids = [t.id for t in pipelines_db[mode].types]
    if request.id in existing_ids:
        raise HTTPException(status_code=400, detail="类型 ID 已存在")
    
    pipelines_db[mode].types.append(request)
    _persist_pipelines()
    return request


@router.put("/vision-pipelines/{mode}/types/{type_id}", response_model=PipelineTypeConfig)
async def update_pipeline_type(mode: str, type_id: str, request: PipelineTypeConfig):
    """更新 Pipeline 类型"""
    if mode not in pipelines_db:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    
    for i, t in enumerate(pipelines_db[mode].types):
        if t.id == type_id:
            pipelines_db[mode].types[i] = request
            _persist_pipelines()
            return request
    
    raise HTTPException(status_code=404, detail="类型不存在")


@router.post("/vision-pipelines/{mode}/types/{type_id}/toggle")
async def toggle_pipeline_type(mode: str, type_id: str):
    """切换 Pipeline 类型启用状态"""
    if mode not in pipelines_db:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    
    for t in pipelines_db[mode].types:
        if t.id == type_id:
            t.enabled = not t.enabled
            _persist_pipelines()
            return {"enabled": t.enabled}
    
    raise HTTPException(status_code=404, detail="类型不存在")


@router.delete("/vision-pipelines/{mode}/types/{type_id}")
async def delete_pipeline_type(mode: str, type_id: str):
    """删除 Pipeline 类型"""
    if mode not in pipelines_db:
        raise HTTPException(status_code=404, detail="Pipeline 不存在")
    
    # 检查是否是预置类型
    preset_ids = [t.id for t in PRESET_PIPELINES.get(mode, PipelineConfig(
        mode=PipelineMode.OCR_HAS, name="", description="", types=[]
    )).types]
    
    if type_id in preset_ids:
        raise HTTPException(status_code=400, detail="预置类型不能删除，只能禁用")
    
    pipelines_db[mode].types = [t for t in pipelines_db[mode].types if t.id != type_id]
    _persist_pipelines()
    return {"message": "删除成功"}


@router.post("/vision-pipelines/reset")
async def reset_pipelines():
    """重置所有 Pipeline 配置为默认"""
    global pipelines_db
    pipelines_db = {k: v.model_copy(deep=True) for k, v in PRESET_PIPELINES.items()}
    _persist_pipelines()
    return {"message": "已重置为默认配置"}


def get_pipeline_types_for_mode(mode: str) -> List[PipelineTypeConfig]:
    """获取指定模式下启用的类型配置"""
    if mode not in pipelines_db:
        return []
    return [t for t in pipelines_db[mode].types if t.enabled]
