"""
脱敏处理 API 路由
处理文档脱敏、对比等操作
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.models.schemas import (
    RedactionRequest,
    RedactionResult,
    CompareData,
    VisionResult,
    APIResponse,
    PreviewEntityMapRequest,
    PreviewEntityMapResponse,
)
from app.services.redactor import Redactor, build_preview_entity_map
from app.services.vision_service import VisionService
from app.core.persistence import to_jsonable
from app.api.files import file_store, persist_file_store

router = APIRouter()


class VisionDetectRequest(BaseModel):
    """视觉识别请求体"""
    selected_ocr_has_types: Optional[List[str]] = None
    selected_has_image_types: Optional[List[str]] = None


@router.post("/redaction/execute", response_model=RedactionResult)
async def execute_redaction(request: RedactionRequest):
    """
    执行文档脱敏
    
    根据提供的实体列表和配置，对文档进行脱敏处理:
    - 文本类文档: 替换敏感文本
    - 图片类文档: 添加黑色遮罩
    """
    file_id = request.file_id
    
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    redactor = Redactor()
    result = await redactor.redact(
        file_info=file_info,
        entities=request.entities,
        bounding_boxes=request.bounding_boxes,
        config=request.config,
    )
    
    # 更新文件存储：脱敏条数 + 本次实际提交的实体/框（识别阶段可能未写入 file_store，导致历史一直为 0）
    file_store[file_id]["output_path"] = result.get("output_path")
    file_store[file_id]["entity_map"] = result.get("entity_map", {})
    file_store[file_id]["redacted_count"] = int(result.get("redacted_count", 0))
    if request.bounding_boxes:
        file_store[file_id]["bounding_boxes"] = {1: to_jsonable(request.bounding_boxes)}
    if request.entities:
        file_store[file_id]["entities"] = to_jsonable(request.entities)
    persist_file_store()
    
    return RedactionResult(
        file_id=file_id,
        output_file_id=result["output_file_id"],
        redacted_count=result["redacted_count"],
        entity_map=result.get("entity_map", {}),
        download_url=f"/api/v1/files/{file_id}/download?redacted=true",
    )


@router.post("/redaction/preview-map", response_model=PreviewEntityMapResponse)
async def preview_entity_map(body: PreviewEntityMapRequest):
    """根据当前勾选实体与替换模式，返回与 execute 一致的 entity_map（不写文件）。"""
    em = build_preview_entity_map(body.entities, body.config)
    return PreviewEntityMapResponse(entity_map=em)


@router.get("/redaction/{file_id}/compare", response_model=CompareData)
async def get_comparison(file_id: str):
    """
    获取脱敏前后对比数据
    
    返回原始内容和脱敏后内容，用于前端展示对比视图
    """
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    if "output_path" not in file_info:
        raise HTTPException(status_code=400, detail="文件尚未脱敏")
    
    redactor = Redactor()
    compare_data = await redactor.get_comparison(file_info)
    
    return CompareData(
        file_id=file_id,
        original_content=compare_data["original"],
        redacted_content=compare_data["redacted"],
        changes=compare_data.get("changes", []),
    )


@router.post("/redaction/{file_id}/vision", response_model=VisionResult)
async def detect_sensitive_regions(
    file_id: str, 
    page: int = 1,
    request: Optional[VisionDetectRequest] = None,
):
    """
    对图片/扫描件进行视觉识别
    
    并行：OCR + HaS（文字）与 HaS Image（8081 YOLO，21 类隐私区域），合并去重。
    """
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_info = file_store[file_id]
    
    # 获取两个 Pipeline 的类型配置
    from app.api.vision_pipeline import get_pipeline_types_for_mode, pipelines_db
    
    # 获取系统配置中启用的类型
    all_ocr_has_types = get_pipeline_types_for_mode("ocr_has")
    all_has_image_types = get_pipeline_types_for_mode("has_image")

    selected_ocr_has_ids: Optional[set[str]] = None
    selected_has_image_ids: Optional[set[str]] = None
    if request is None:
        selected_has_image_ids = set()
    else:
        if request.selected_ocr_has_types is not None:
            selected_ocr_has_ids = set(request.selected_ocr_has_types or [])
        if request.selected_has_image_types is not None:
            selected_has_image_ids = set(request.selected_has_image_types or [])
        else:
            selected_has_image_ids = set()

    if selected_ocr_has_ids is not None:
        ocr_has_types = [t for t in all_ocr_has_types if t.id in selected_ocr_has_ids]
    else:
        ocr_has_types = all_ocr_has_types

    if selected_has_image_ids is not None:
        has_image_types = [t for t in all_has_image_types if t.id in selected_has_image_ids]
    else:
        has_image_types = all_has_image_types

    ocr_has_enabled = pipelines_db.get("ocr_has", None) and pipelines_db["ocr_has"].enabled and len(ocr_has_types) > 0
    has_image_enabled = (
        pipelines_db.get("has_image", None)
        and pipelines_db["has_image"].enabled
        and len(has_image_types) > 0
    )

    if pipelines_db.get("ocr_has") and pipelines_db["ocr_has"].enabled and len(ocr_has_types) == 0:
        print(
            "[API] OCR+HaS 跳过：前端传入的类型列表为空（selected_ocr_has_types=[] 表示不跑文字 OCR）。"
            "若希望识别文字，请在侧栏勾选至少一类 OCR+HaS 类型，或清除 localStorage 键 ocrHasTypes 后刷新。"
        )
    
    print(f"[API] OCR+HaS selected: {[t.id for t in ocr_has_types] if ocr_has_types else []}")
    print(f"[API] HaS Image selected: {[t.id for t in has_image_types] if has_image_types else []}")

    vision_service = VisionService()
    bounding_boxes, result_image = await vision_service.detect_with_dual_pipeline(
        file_path=file_info["file_path"],
        file_type=file_info["file_type"],
        page=page,
        ocr_has_types=ocr_has_types if ocr_has_enabled else None,
        has_image_types=has_image_types if has_image_enabled else None,
    )
    
    # 存储识别结果
    if "bounding_boxes" not in file_store[file_id]:
        file_store[file_id]["bounding_boxes"] = {}
    file_store[file_id]["bounding_boxes"][page] = bounding_boxes
    persist_file_store()
    
    return VisionResult(
        file_id=file_id,
        page=page,
        bounding_boxes=bounding_boxes,
        result_image=result_image,
    )


@router.get("/redaction/entity-types")
async def get_entity_types():
    """获取支持的实体类型列表"""
    from app.models.schemas import EntityType
    
    entity_types = [
        {"value": EntityType.PERSON.value, "label": "人名", "color": "#F59E0B"},
        {"value": EntityType.ORG.value, "label": "机构/公司", "color": "#3B82F6"},
        {"value": EntityType.ID_CARD.value, "label": "身份证号", "color": "#EF4444"},
        {"value": EntityType.PHONE.value, "label": "电话号码", "color": "#10B981"},
        {"value": EntityType.ADDRESS.value, "label": "地址", "color": "#8B5CF6"},
        {"value": EntityType.BANK_CARD.value, "label": "银行卡号", "color": "#EC4899"},
        {"value": EntityType.CASE_NUMBER.value, "label": "案件编号", "color": "#6366F1"},
        {"value": EntityType.DATE.value, "label": "日期", "color": "#14B8A6"},
        {"value": EntityType.MONEY.value, "label": "金额", "color": "#F97316"},
        {"value": EntityType.CUSTOM.value, "label": "自定义", "color": "#6B7280"},
    ]
    
    return {"entity_types": entity_types}


@router.get("/redaction/replacement-modes")
async def get_replacement_modes():
    """获取支持的替换模式列表"""
    from app.models.schemas import ReplacementMode
    
    modes = [
        {
            "value": ReplacementMode.SMART.value,
            "label": "智能替换",
            "description": "将敏感信息替换为语义化的标识，如 '当事人甲'、'公司A'",
        },
        {
            "value": ReplacementMode.STRUCTURED.value,
            "label": "结构化语义标签",
            "description": "用结构化标签替换敏感信息，保留层级语义与指代关系",
        },
        {
            "value": ReplacementMode.MASK.value,
            "label": "掩码替换",
            "description": "将敏感信息替换为 *** 或部分隐藏，如 '张**'、'138****1234'",
        },
        {
            "value": ReplacementMode.CUSTOM.value,
            "label": "自定义替换",
            "description": "手动指定每个敏感信息的替换文本",
        },
    ]
    
    return {"replacement_modes": modes}
