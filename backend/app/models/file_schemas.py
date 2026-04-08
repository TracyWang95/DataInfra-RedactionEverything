"""
File upload, listing, parsing, NER result, and batch-download models.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime

from .common import FileType
from .entity_schemas import Entity
from .job_schemas import JobEmbedSummary

__all__ = [
    "FileUploadResponse",
    "FileListItem",
    "FileListResponse",
    "ParseResult",
    "NERResult",
    "BatchDownloadRequest",
]


class FileUploadResponse(BaseModel):
    """文件上传响应"""
    file_id: str
    filename: str
    file_type: FileType
    file_size: int
    page_count: int = 1
    message: str = "文件上传成功"
    created_at: Optional[datetime] = None


class FileListItem(BaseModel):
    """文件列表项（处理历史）"""
    file_id: str
    original_filename: str
    file_size: int
    file_type: FileType
    created_at: Optional[str] = None
    has_output: bool = False
    entity_count: int = 0
    upload_source: Literal["playground", "batch"] = Field(
        default="playground",
        description="playground=Playground 单文件；batch=批量向导或任务工单上传",
    )
    job_id: Optional[str] = Field(
        default=None,
        description="若上传时绑定任务中心 Job，则为该 Job UUID，可与 /api/v1/jobs/{id} 关联",
    )
    batch_group_id: Optional[str] = Field(
        default=None,
        description="批量向导同一会话上传的文件共享此 ID；Playground 单文件上传为 null",
    )
    batch_group_count: Optional[int] = Field(
        default=None,
        description="该批次在系统中的文件总数（仅 batch_group_id 非空时有意义）",
    )
    item_status: Optional[str] = Field(
        default=None,
        description="关联 job_item 的 pipeline 状态（awaiting_review / completed 等），用于三态匿名化显示",
    )
    item_id: Optional[str] = Field(
        default=None,
        description="关联 job_item 的 ID，用于构建审阅跳转 URL",
    )
    job_embed: Optional[JobEmbedSummary] = Field(
        default=None,
        description="embed_job=1 且存在 job_id 时返回，供历史页主 CTA 与任务中心一致",
    )


class FileListResponse(BaseModel):
    """文件列表响应（支持分页）"""
    files: list[FileListItem]
    total: int
    page: int = 1
    page_size: int = 20


class ParseResult(BaseModel):
    """文件解析结果"""
    file_id: str
    file_type: FileType
    content: str = Field(default="", description="提取的文本内容")
    page_count: int = 1
    pages: list[str] = Field(default_factory=list, description="分页文本内容")
    is_scanned: bool = Field(default=False, description="是否为扫描件")


class NERResult(BaseModel):
    """NER 识别结果"""
    file_id: str
    entities: list[Entity]
    entity_count: int
    entity_summary: dict[str, int] = Field(default_factory=dict, description="各类型实体数量统计")
    warnings: list[str] = Field(default_factory=list, description="识别过程中的警告信息")


class BatchDownloadRequest(BaseModel):
    """批量打包下载"""
    file_ids: List[str] = Field(..., min_length=1, description="要打包的文件 ID 列表")
    redacted: bool = Field(default=False, description="为 True 时打包匿名化后的文件（需已匿名化）")
