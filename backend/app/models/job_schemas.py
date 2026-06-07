"""
Job (task-center) request/response models: create, list, detail,
progress, review-draft, and related bodies.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .entity_schemas import BoundingBox, Entity

JobExportSummaryDeliveryStatus = Literal["ready_for_delivery", "action_required", "no_selection"]
JobExportFileDeliveryStatus = Literal["ready_for_delivery", "action_required", "not_selected"]

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
    "JobExportReportFile",
    "JobExportReportJob",
    "JobExportReportRedactedZip",
    "JobExportReportResponse",
    "JobExportReportSummary",
    "JobExportReportVisualEvidence",
    "JobExportReportVisualReview",
    "JobExportReportZipSkipped",
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
    processing: int = 0
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
    job_type: Literal["text_batch", "image_batch", "smart_batch", "structured_batch"]
    items: list[JobItemMini] = Field(default_factory=list)
    progress: JobProgress = Field(default_factory=JobProgress)
    wizard_furthest_step: int | None = Field(
        default=None,
        description="Furthest configured wizard step stored in job config.",
    )
    first_awaiting_review_item_id: str | None = Field(
        default=None,
        description="First item that is ready for review.",
    )
    batch_step1_configured: bool = Field(
        default=False,
        description="Whether recognition selections have been configured.",
    )


class NavHints(BaseModel):
    """任务导航提示"""
    model_config = ConfigDict(extra="allow")

    item_count: int = 0
    first_awaiting_review_item_id: str | None = None
    batch_step1_configured: bool = False
    wizard_furthest_step: int | None = None
    redacted_count: int = Field(default=0, description="Items with a usable redacted output.")
    awaiting_review_count: int = Field(default=0, description="Backward-compatible alias for reviewable_count.")
    reviewable_count: int = Field(default=0, description="Items currently ready for manual review.")
    processing_count: int = Field(default=0, description="Items still pending, queued, processing, or redacting.")
    export_ready_count: int = Field(default=0, description="Items that are currently export-ready.")
    export_blocked_count: int = Field(default=0, description="Items that still prevent whole-job export.")
    can_review_now: bool = Field(default=False, description="True when at least one item can be reviewed now.")
    can_export_now: bool = Field(default=False, description="True when every item is ready for export.")
    metadata_degraded: bool = False
    metadata_degraded_count: int = 0


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
    """Job item response."""
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
    progress_stage: str | None = None
    progress_current: int = 0
    progress_total: int = 0
    progress_message: str | None = None
    progress_updated_at: str | None = None
    performance: dict[str, Any] = Field(default_factory=dict)
    queue_wait_ms: int | None = None
    recognition_duration_ms: int | None = None
    redaction_duration_ms: int | None = None
    recognition_pages: list[dict[str, Any]] = Field(default_factory=list)
    recognition_page_concurrency: int | None = None
    recognition_page_concurrency_configured: int | None = None
    recognition_page_duration_sum_ms: int | None = None
    recognition_parallelism_ratio: float | None = None


class JobListResponse(BaseModel):
    """Job list response."""
    jobs: list[JobResponse]
    total: int
    page: int = 1
    page_size: int = 20
    stats: dict[str, int] = Field(
        default_factory=dict,
        description="Filtered-list aggregate counters, independent of pagination.",
    )


class JobProgressResponse(BaseModel):
    """Job progress response."""
    model_config = ConfigDict(extra="ignore")

    status: str
    total_items: int = 0
    pending: int = 0
    processing: int = 0
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
    """Job detail response with items."""
    items: list[JobItemResponse] = Field(default_factory=list)


class JobDeleteResponse(BaseModel):
    """Job delete response."""
    id: str
    deleted: bool = True
    deleted_item_count: int = 0
    detached_file_count: int = 0


class JobExportReportJob(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "id": "job_01HXAMPLE",
                    "job_type": "smart_batch",
                    "status": "completed",
                    "skip_item_review": False,
                    "config": {"selected_modes": ["text", "image"]},
                }
            ]
        },
    )

    id: str = Field(description="Job id that owns this export report.", examples=["job_01HXAMPLE"])
    job_type: str = Field(description="Batch job type.", examples=["smart_batch"])
    status: str = Field(description="Current job status.", examples=["completed"])
    skip_item_review: bool = Field(
        default=False,
        description="True when item review was intentionally skipped for this job.",
        examples=[False],
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Job configuration captured for traceability.",
        examples=[{"selected_modes": ["text", "image"]}],
    )


class JobExportReportVisualEvidence(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "total_boxes": 2,
                    "selected_boxes": 1,
                    "visual_feature_model": 1,
                    "local_fallback": 0,
                    "ocr_has": 0,
                    "table_structure": 0,
                    "fallback_detector": 0,
                    "source_counts": {"visual_features": 1},
                    "evidence_source_counts": {},
                    "source_detail_counts": {},
                    "warnings_by_key": {},
                }
            ]
        },
    )

    total_boxes: int = Field(
        default=0,
        description="Total bounding boxes present in backend metadata for the file set represented by this object.",
    )
    selected_boxes: int = Field(
        default=0,
        description="Bounding boxes with selected != false; source and warning counters below are based on these boxes.",
    )
    visual_feature_model: int = Field(default=0, description="Selected boxes attributed to the primary HaS image model.")
    local_fallback: int = Field(default=0, description="Selected boxes attributed to local fallback evidence.")
    ocr_has: int = Field(default=0, description="Selected boxes attributed to OCR/HaS evidence.")
    table_structure: int = Field(default=0, description="Selected boxes attributed to table-structure evidence.")
    fallback_detector: int = Field(default=0, description="Selected boxes attributed to fallback detector evidence.")
    source_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Selected bounding-box counts keyed by normalized source.",
        examples=[{"visual_features": 1, "ocr_has": 2}],
    )
    evidence_source_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Selected bounding-box counts keyed by normalized evidence_source.",
        examples=[{"local_fallback": 1}],
    )
    source_detail_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Selected bounding-box counts keyed by normalized source_detail.",
        examples=[{"seal_detector": 1, "table_structure": 1}],
    )
    warnings_by_key: dict[str, int] = Field(
        default_factory=dict,
        description="Selected bounding-box warning counts keyed by normalized warning key.",
        examples=[{"manual-review": 1, "near-page-edge": 1}],
    )


class JobExportReportVisualReview(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "blocking": False,
                    "review_hint": True,
                    "issue_count": 2,
                    "issue_pages": ["5"],
                    "issue_pages_count": 1,
                    "issue_labels": ["edge_seal", "seam_seal"],
                    "by_issue": {"edge_seal": 1, "seam_seal": 1},
                }
            ]
        },
    )

    blocking: bool = Field(
        default=False,
        description=(
            "Reserved for future visual-review blockers. Current visual-review hints are advisory only; "
            "blocking is always false and does not affect delivery_status."
        ),
        examples=[False],
    )
    review_hint: bool = Field(
        default=False,
        description=(
            "Advisory hint set when selected visual boxes contain quality signals worth manual review; "
            "this alone is not a delivery blocker and does not change delivery_status."
        ),
        examples=[True],
    )
    issue_count: int = Field(
        default=0,
        description="Total advisory visual-review issue count for this file.",
        examples=[2],
    )
    issue_pages: list[str] = Field(
        default_factory=list,
        description="1-based page labels that contain advisory visual-review issues.",
        examples=[["1", "3"]],
    )
    issue_pages_count: int = Field(default=0, description="Number of pages listed in issue_pages.", examples=[1])
    issue_labels: list[str] = Field(
        default_factory=list,
        description="Sorted visual-review issue labels present in this file.",
        examples=[["edge_seal", "low_confidence"]],
    )
    by_issue: dict[str, int] = Field(
        default_factory=dict,
        description="Issue counts keyed by visual-review issue label.",
        examples=[{"edge_seal": 1, "low_confidence": 2}],
    )


class JobExportReportFile(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "item_id": "item_ready",
                    "file_id": "file_ready",
                    "filename": "contract.pdf",
                    "file_type": "pdf",
                    "file_size": 1048576,
                    "status": "completed",
                    "has_output": True,
                    "review_confirmed": True,
                    "entity_count": 12,
                    "page_count": 5,
                    "selected_for_export": True,
                    "delivery_status": "ready_for_delivery",
                    "error": None,
                    "ready_for_delivery": True,
                    "action_required": False,
                    "blocking": False,
                    "blocking_reasons": [],
                    "redacted_export_skip_reason": None,
                    "visual_review_hint": True,
                    "visual_evidence": {
                        "total_boxes": 2,
                        "selected_boxes": 1,
                        "visual_feature_model": 1,
                        "local_fallback": 0,
                        "ocr_has": 0,
                        "table_structure": 0,
                        "fallback_detector": 0,
                        "source_counts": {"visual_features": 1},
                        "evidence_source_counts": {},
                        "source_detail_counts": {},
                        "warnings_by_key": {},
                    },
                    "visual_review": {
                        "blocking": False,
                        "review_hint": True,
                        "issue_count": 2,
                        "issue_pages": ["5"],
                        "issue_pages_count": 1,
                        "issue_labels": ["edge_seal", "seam_seal"],
                        "by_issue": {"edge_seal": 1, "seam_seal": 1},
                    },
                },
                {
                    "item_id": "item_pending",
                    "file_id": "file_pending",
                    "filename": "pending.pdf",
                    "file_type": "pdf",
                    "file_size": 524288,
                    "status": "awaiting_review",
                    "has_output": False,
                    "review_confirmed": False,
                    "entity_count": 4,
                    "page_count": 2,
                    "selected_for_export": True,
                    "delivery_status": "action_required",
                    "error": None,
                    "ready_for_delivery": False,
                    "action_required": True,
                    "blocking": True,
                    "blocking_reasons": ["missing_redacted_output", "review_not_confirmed"],
                    "redacted_export_skip_reason": "missing_redacted_output",
                    "visual_review_hint": False,
                    "visual_evidence": {
                        "total_boxes": 0,
                        "selected_boxes": 0,
                        "visual_feature_model": 0,
                        "local_fallback": 0,
                        "ocr_has": 0,
                        "table_structure": 0,
                        "fallback_detector": 0,
                        "source_counts": {},
                        "evidence_source_counts": {},
                        "source_detail_counts": {},
                        "warnings_by_key": {},
                    },
                    "visual_review": {
                        "blocking": False,
                        "review_hint": False,
                        "issue_count": 0,
                        "issue_pages": [],
                        "issue_pages_count": 0,
                        "issue_labels": [],
                        "by_issue": {},
                    },
                },
            ]
        },
    )

    item_id: str = Field(description="Job item id for this file.")
    file_id: str = Field(description="File id in the file store.")
    filename: str = Field(description="Original filename displayed to the user.", examples=["contract.pdf"])
    file_type: str = Field(description="Stored file type/category, when known.", examples=["pdf"])
    file_size: int = Field(default=0, description="Original file size in bytes.")
    status: str = Field(description="Current job item processing status.", examples=["completed"])
    has_output: bool = Field(default=False, description="True when a redacted output path is recorded for this file.")
    review_confirmed: bool = Field(
        default=False,
        description="True when review is confirmed, or review is skipped and a redacted output exists.",
    )
    entity_count: int = Field(default=0, description="Detected entity count from backend file metadata.")
    page_count: int | None = Field(default=None, description="Page count for paged documents, when known.")
    selected_for_export: bool = Field(
        default=False,
        description="True when this file is part of the requested export-report selection.",
        examples=[True],
    )
    delivery_status: JobExportFileDeliveryStatus = Field(
        default="action_required",
        description=(
            "Canonical per-file delivery status for new clients. "
            "ready_for_delivery means the selected file can ship; action_required means the selected file blocks delivery; "
            "not_selected means this file belongs to the job but is outside the report selection. "
            "Visual-review hints are advisory and do not change this status."
        ),
        examples=["ready_for_delivery"],
    )
    error: str | None = Field(default=None, description="Latest job item error message, if any.")
    ready_for_delivery: bool = Field(
        default=False,
        description="Backward-compatible boolean alias: true when delivery_status is ready_for_delivery.",
    )
    action_required: bool = Field(
        default=True,
        description="Backward-compatible boolean alias for files that are not ready_for_delivery.",
    )
    blocking: bool = Field(
        default=True,
        description="Backward-compatible boolean alias matching action_required for delivery blockers.",
    )
    blocking_reasons: list[str] = Field(
        default_factory=list,
        description="Machine-readable reasons that prevent redacted delivery for this file.",
        examples=[["missing_redacted_output", "review_not_confirmed"]],
    )
    redacted_export_skip_reason: str | None = Field(
        default=None,
        description="Reason this file would be skipped by a redacted ZIP, or null when the redacted output can be included.",
        examples=["missing_redacted_output"],
    )
    visual_review_hint: bool = Field(
        default=False,
        description=(
            "Backward-compatible alias for visual_review.review_hint. Advisory only; "
            "not a delivery blocker and not included in delivery_status calculations."
        ),
        examples=[True],
    )
    visual_evidence: JobExportReportVisualEvidence = Field(
        default_factory=JobExportReportVisualEvidence,
        description=(
            "Auditable bounding-box evidence/source summary for this file. "
            "Counters are informational and do not affect delivery_status."
        ),
    )
    visual_review: JobExportReportVisualReview = Field(
        default_factory=JobExportReportVisualReview,
        description="Advisory visual-review quality signals for this file; currently non-blocking.",
    )


class JobExportReportSummary(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "total_files": 2,
                    "selected_files": 2,
                    "redacted_selected_files": 1,
                    "unredacted_selected_files": 1,
                    "review_confirmed_selected_files": 1,
                    "failed_selected_files": 0,
                    "detected_entities": 16,
                    "redaction_coverage": 0.5,
                    "delivery_status": "action_required",
                    "action_required_files": 1,
                    "action_required": True,
                    "blocking_files": 1,
                    "blocking": True,
                    "ready_for_delivery": False,
                    "by_status": {"completed": 1, "awaiting_review": 1},
                    "zip_redacted_included_files": 1,
                    "zip_redacted_skipped_files": 1,
                    "visual_review_hint": True,
                    "visual_review_issue_files": 1,
                    "visual_review_issue_count": 2,
                    "visual_review_issue_pages_count": 1,
                    "visual_review_issue_labels": ["edge_seal", "seam_seal"],
                    "visual_review_by_issue": {"edge_seal": 1, "seam_seal": 1},
                    "visual_evidence": {
                        "total_boxes": 2,
                        "selected_boxes": 1,
                        "visual_feature_model": 1,
                        "local_fallback": 0,
                        "ocr_has": 0,
                        "table_structure": 0,
                        "fallback_detector": 0,
                        "source_counts": {"visual_features": 1},
                        "evidence_source_counts": {},
                        "source_detail_counts": {},
                        "warnings_by_key": {},
                    },
                }
            ]
        },
    )

    total_files: int = Field(default=0, description="Total files attached to the job.")
    selected_files: int = Field(default=0, description="Files included in this export-report selection.")
    redacted_selected_files: int = Field(default=0, description="Selected files that have a recorded redacted output.")
    unredacted_selected_files: int = Field(default=0, description="Selected files without a recorded redacted output.")
    review_confirmed_selected_files: int = Field(default=0, description="Selected files with confirmed review state.")
    failed_selected_files: int = Field(default=0, description="Selected files whose job item status is failed.")
    detected_entities: int = Field(default=0, description="Detected entity count across selected files.")
    redaction_coverage: float = Field(default=0, description="redacted_selected_files / selected_files, or 0 for an empty selection.")
    delivery_status: JobExportSummaryDeliveryStatus = Field(
        default="no_selection",
        description=(
            "Canonical selected-set delivery status for new clients. "
            "ready_for_delivery means every selected file can ship; action_required means at least one selected file blocks delivery; "
            "no_selection means no files were selected for this report. "
            "Visual-review hints are advisory and do not change this status."
        ),
        examples=["action_required"],
    )
    action_required_files: int = Field(default=0, description="Selected files that are not ready_for_delivery.")
    action_required: bool = Field(
        default=False,
        description="Backward-compatible boolean alias: true when delivery_status is action_required.",
    )
    blocking_files: int = Field(default=0, description="Backward-compatible count matching action_required_files.")
    blocking: bool = Field(
        default=False,
        description="Backward-compatible boolean alias matching action_required.",
    )
    ready_for_delivery: bool = Field(
        default=False,
        description="Backward-compatible boolean alias: true when delivery_status is ready_for_delivery.",
    )
    by_status: dict[str, int] = Field(default_factory=dict, description="Selected file counts keyed by job item status.")
    zip_redacted_included_files: int = Field(default=0, description="Selected files that would be included in the redacted ZIP.")
    zip_redacted_skipped_files: int = Field(default=0, description="Selected files that would be skipped by the redacted ZIP.")
    visual_review_hint: bool = Field(
        default=False,
        description=(
            "True when selected files contain advisory visual-review issues; this alone is not a delivery blocker "
            "and does not make delivery_status action_required."
        ),
        examples=[True],
    )
    visual_review_issue_files: int = Field(default=0, description="Selected files with advisory visual-review issues.")
    visual_review_issue_count: int = Field(default=0, description="Total advisory visual-review issue count across selected files.")
    visual_review_issue_pages_count: int = Field(
        default=0,
        description="Total count of file/page pairs that contain advisory visual-review issues.",
    )
    visual_review_issue_labels: list[str] = Field(
        default_factory=list,
        description="Sorted advisory visual-review issue labels across selected files.",
        examples=[["edge_seal", "low_confidence"]],
    )
    visual_review_by_issue: dict[str, int] = Field(
        default_factory=dict,
        description="Advisory visual-review issue counts across selected files, keyed by issue label.",
        examples=[{"edge_seal": 1, "low_confidence": 2}],
    )
    visual_evidence: JobExportReportVisualEvidence = Field(
        default_factory=JobExportReportVisualEvidence,
        description=(
            "Auditable selected-set bounding-box evidence/source summary. "
            "Counters are informational and visual-review hints remain advisory."
        ),
    )


class JobExportReportZipSkipped(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {"file_id": "file_pending", "reason": "missing_redacted_output"}
            ]
        },
    )

    file_id: str = Field(description="File id skipped from the redacted ZIP.", examples=["file_pending"])
    reason: str = Field(
        description="Machine-readable skip reason.",
        examples=["missing_redacted_output"],
    )


class JobExportReportRedactedZip(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "included_count": 1,
                    "skipped_count": 1,
                    "skipped": [{"file_id": "file_pending", "reason": "missing_redacted_output"}],
                }
            ]
        },
    )

    included_count: int = Field(default=0, description="Selected files included in the redacted ZIP.", examples=[1])
    skipped_count: int = Field(default=0, description="Selected files skipped from the redacted ZIP.", examples=[1])
    skipped: list[JobExportReportZipSkipped] = Field(
        default_factory=list,
        description="Per-file redacted ZIP skip reasons.",
    )


class JobExportReportResponse(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "generated_at": "2026-05-05T00:00:00+00:00",
                    "job": {
                        "id": "job_01HXAMPLE",
                        "job_type": "smart_batch",
                        "status": "completed",
                        "skip_item_review": False,
                        "config": {"selected_modes": ["text", "image"]},
                    },
                    "summary": {
                        "total_files": 2,
                        "selected_files": 2,
                        "redacted_selected_files": 1,
                        "unredacted_selected_files": 1,
                        "review_confirmed_selected_files": 1,
                        "failed_selected_files": 0,
                        "detected_entities": 16,
                        "redaction_coverage": 0.5,
                        "delivery_status": "action_required",
                        "action_required_files": 1,
                        "action_required": True,
                        "blocking_files": 1,
                        "blocking": True,
                        "ready_for_delivery": False,
                        "by_status": {"completed": 1, "awaiting_review": 1},
                        "zip_redacted_included_files": 1,
                        "zip_redacted_skipped_files": 1,
                        "visual_review_hint": True,
                        "visual_review_issue_files": 1,
                        "visual_review_issue_count": 2,
                        "visual_review_issue_pages_count": 1,
                        "visual_review_issue_labels": ["edge_seal", "seam_seal"],
                        "visual_review_by_issue": {"edge_seal": 1, "seam_seal": 1},
                        "visual_evidence": {
                            "total_boxes": 2,
                            "selected_boxes": 1,
                            "visual_feature_model": 1,
                            "local_fallback": 0,
                            "ocr_has": 0,
                            "table_structure": 0,
                            "fallback_detector": 0,
                            "source_counts": {"visual_features": 1},
                            "evidence_source_counts": {},
                            "source_detail_counts": {},
                            "warnings_by_key": {},
                        },
                    },
                    "redacted_zip": {
                        "included_count": 1,
                        "skipped_count": 1,
                        "skipped": [{"file_id": "file_pending", "reason": "missing_redacted_output"}],
                    },
                    "files": [
                        {
                            "item_id": "item_ready",
                            "file_id": "file_ready",
                            "filename": "contract.pdf",
                            "file_type": "pdf",
                            "file_size": 1048576,
                            "status": "completed",
                            "has_output": True,
                            "review_confirmed": True,
                            "entity_count": 12,
                            "page_count": 5,
                            "selected_for_export": True,
                            "delivery_status": "ready_for_delivery",
                            "error": None,
                            "ready_for_delivery": True,
                            "action_required": False,
                            "blocking": False,
                            "blocking_reasons": [],
                            "redacted_export_skip_reason": None,
                            "visual_review_hint": True,
                            "visual_evidence": {
                                "total_boxes": 2,
                                "selected_boxes": 1,
                                "visual_feature_model": 1,
                                "local_fallback": 0,
                                "ocr_has": 0,
                                "table_structure": 0,
                                "fallback_detector": 0,
                                "source_counts": {"visual_features": 1},
                                "evidence_source_counts": {},
                                "source_detail_counts": {},
                                "warnings_by_key": {},
                            },
                            "visual_review": {
                                "blocking": False,
                                "review_hint": True,
                                "issue_count": 2,
                                "issue_pages": ["5"],
                                "issue_pages_count": 1,
                                "issue_labels": ["edge_seal", "seam_seal"],
                                "by_issue": {"edge_seal": 1, "seam_seal": 1},
                            },
                        }
                    ],
                }
            ]
        },
    )

    generated_at: str = Field(description="ISO timestamp when the report was generated.")
    job: JobExportReportJob = Field(description="Traceable job metadata for this report.")
    summary: JobExportReportSummary = Field(description="Selected-set readiness, ZIP, and visual-review summary.")
    redacted_zip: JobExportReportRedactedZip = Field(description="Predicted redacted ZIP inclusion and skip details.")
    files: list[JobExportReportFile] = Field(
        default_factory=list,
        description=(
            "All files in the job. Use selected_for_export and delivery_status to distinguish selected files, "
            "actionable blockers, and not_selected files."
        ),
    )


class ReviewDraftResponse(BaseModel):
    """Review draft response."""
    model_config = ConfigDict(extra="ignore")

    exists: bool
    entities: list = Field(default_factory=list)
    bounding_boxes: list = Field(default_factory=list)
    updated_at: str | None = None
    degraded: bool = False
    retry_after_ms: int | None = None


# ─── Job Request Models ───

class JobCreateBody(BaseModel):
    job_type: Literal["text_batch", "image_batch", "smart_batch", "structured_batch"]
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
    """Request body for POST /jobs/batch-details 鈥?fetch multiple job details at once."""
    ids: list[str] = Field(..., min_length=0, max_length=50)


class BatchDetailsResponse(BaseModel):
    """Response for POST /jobs/batch-details."""
    jobs: list[JobDetailResponse] = Field(default_factory=list)

