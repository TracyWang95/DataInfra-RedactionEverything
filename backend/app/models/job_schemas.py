"""
Job (task-center) request/response models: create, list, detail,
progress, review-draft, and related bodies.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .entity_schemas import BoundingBox, Entity

__all__ = [
    "JobItemMini",
    "JobProgress",
    "JobEmbedSummary",
    "NavHints",
    "JobResponse",
    "JobItemResponse",
    "JobListResponse",
    "JobProgressResponse",
    "JobDetailResponse",
    "JobDeleteResponse",
    "ReviewDraftResponse",
    "JobCreateBody",
    "JobItemAddBody",
    "JobUpdateBody",
    "ReviewDraftBody",
    "ReviewCommitBody",
    "BatchDetailsBody",
    "BatchDetailsResponse",
]


class JobItemMini(BaseModel):
    """列表嵌套用：与任务详情 CTA 解析一致的最小 item 字段"""

    model_config = ConfigDict(extra="ignore")

    id: str
    status: str


class JobProgress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_items: int = 0
    pending: int = 0
    queued: int = 0
    parsing: int = 0
    ner: int = 0
    vision: int = 0
    awaiting_review: int = 0
    review_approved: int = 0
    redacting: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class JobEmbedSummary(BaseModel):
    """GET /files?embed_job=1 时按 job_id 去重注入，减少前端逐条 getJob"""

    model_config = ConfigDict(extra="ignore")

    status: str
    job_type: Literal["text_batch", "image_batch", "smart_batch"]
    items: list[JobItemMini] = Field(default_factory=list)
    progress: JobProgress = Field(default_factory=JobProgress)
    wizard_furthest_step: int | None = Field(
        default=None,
        description="来自任务 config，供历史页主 CTA 与任务中心「继续上传」一致",
    )
    first_awaiting_review_item_id: str | None = Field(
        default=None,
        description="与 /jobs 列表 nav_hints 一致，待审 deep-link 用",
    )
    batch_step1_configured: bool = Field(
        default=False,
        description="config 已含识别项选择，与 nav_hints.batch_step1_configured 一致",
    )


class NavHints(BaseModel):
    """任务导航提示"""
    model_config = ConfigDict(extra="allow")

    item_count: int = 0
    first_awaiting_review_item_id: str | None = None
    batch_step1_configured: bool = False
    wizard_furthest_step: int | None = None


class JobResponse(BaseModel):
    """任务摘要响应（_job_to_summary 返回值）"""
    model_config = ConfigDict(extra="ignore")

    id: str
    job_type: str
    title: str
    status: str
    priority: int = 0
    skip_item_review: bool = False
    config: dict = Field(default_factory=dict)
    config_json: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
    progress: JobProgress = Field(default_factory=JobProgress)
    nav_hints: NavHints | None = None


class JobItemResponse(BaseModel):
    """任务项响应"""
    model_config = ConfigDict(extra="ignore")

    id: str
    job_id: str
    file_id: str
    sort_order: int = 0
    status: str
    error_message: str | None = None
    reviewed_at: str | None = None
    reviewer: str | None = None
    review_draft_json: str | None = None
    created_at: str
    updated_at: str
    filename: str | None = None
    file_type: str | None = None
    has_output: bool = False
    entity_count: int = 0
    has_review_draft: bool = False
    review_draft_updated_at: str | None = None


class JobListResponse(BaseModel):
    """任务列表响应"""
    jobs: list[JobResponse]
    total: int
    page: int = 1
    page_size: int = 20


class JobProgressResponse(BaseModel):
    """任务进度响应（含 status 字段）"""
    model_config = ConfigDict(extra="ignore")

    status: str
    total_items: int = 0
    pending: int = 0
    queued: int = 0
    parsing: int = 0
    ner: int = 0
    vision: int = 0
    awaiting_review: int = 0
    review_approved: int = 0
    redacting: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class JobDetailResponse(JobResponse):
    """任务详情+项列表响应（继承 JobResponse，追加 items）"""
    items: list[JobItemResponse] = Field(default_factory=list)


class JobDeleteResponse(BaseModel):
    """任务删除响应"""
    id: str
    deleted: bool = True
    deleted_item_count: int = 0
    detached_file_count: int = 0


class ReviewDraftResponse(BaseModel):
    """审核草稿响应"""
    model_config = ConfigDict(extra="ignore")

    exists: bool
    entities: list = Field(default_factory=list)
    bounding_boxes: list = Field(default_factory=list)
    updated_at: str | None = None


# ─── Job Request Models ───

class JobCreateBody(BaseModel):
    job_type: Literal["text_batch", "image_batch", "smart_batch"]
    title: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    skip_item_review: bool = False
    priority: int = 0


class JobItemAddBody(BaseModel):
    file_id: str = Field(..., min_length=1)
    sort_order: int = 0


class JobUpdateBody(BaseModel):
    title: str | None = None
    config: dict[str, Any] | None = None
    skip_item_review: bool | None = None
    priority: int | None = None


class ReviewDraftBody(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    updated_at: str | None = None


class ReviewCommitBody(ReviewDraftBody):
    pass


class BatchDetailsBody(BaseModel):
    """Request body for POST /jobs/batch-details — fetch multiple job details at once."""
    ids: list[str] = Field(..., min_length=0, max_length=50)


class BatchDetailsResponse(BaseModel):
    """Response for POST /jobs/batch-details."""
    jobs: list[JobDetailResponse] = Field(default_factory=list)
