"""Structured table de-identification request/response models."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StructuredSourceType = Literal["file", "db"]
StructuredSourceKind = Literal["csv", "xlsx", "jsonl", "sqlite", "mysql", "postgres"]
StructuredDatasetType = Literal["file_table", "db_table", "db_view", "sheet"]
StructuredShapeKind = Literal[
    "flat_table",
    "relational_multi_table",
    "event_log",
    "wide_feature_table",
    "json_kv_table",
]
StructuredRiskLevel = Literal["low", "medium", "high", "critical"]
StructuredPolicyAction = Literal[
    "keep",
    "mask",
    "hash",
    "tokenize",
    "generalize",
    "bucket",
    "suppress",
    "custom",
]
StructuredExportFormat = Literal["csv", "xlsx", "sqlite", "sql", "zip"]

__all__ = [
    "StructuredColumnPolicy",
    "StructuredColumnProfile",
    "StructuredConnectionCreate",
    "StructuredConnectionOut",
    "StructuredConnectionTestRequest",
    "StructuredConnectionTestResponse",
    "StructuredDatasetOut",
    "StructuredDatasetsResponse",
    "StructuredExportFormat",
    "StructuredJobCreate",
    "StructuredJobResponse",
    "StructuredPolicyBody",
    "StructuredPolicyResponse",
    "StructuredPreviewResponse",
    "StructuredProfileResponse",
    "StructuredSourceOut",
    "StructuredSourcesResponse",
]


class StructuredSourceOut(BaseModel):
    id: str
    source_type: StructuredSourceType
    kind: StructuredSourceKind
    name: str
    status: str = "ready"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class StructuredDatasetOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source_id: str | None = None
    connection_id: str | None = None
    name: str
    dataset_type: StructuredDatasetType
    source_kind: StructuredSourceKind
    shape_kind: StructuredShapeKind = "flat_table"
    schema_name: str | None = None
    table_name: str | None = None
    row_count_estimate: int | None = None
    column_count: int = 0
    columns_schema: list[dict[str, Any]] = Field(default_factory=list, alias="schema")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    profile_updated_at: str | None = None
    policy_updated_at: str | None = None
    policy_reviewed_at: str | None = None


class StructuredSourcesResponse(BaseModel):
    sources: list[StructuredSourceOut] = Field(default_factory=list)


class StructuredDatasetsResponse(BaseModel):
    datasets: list[StructuredDatasetOut] = Field(default_factory=list)


class StructuredConnectionTestRequest(BaseModel):
    engine: Literal["sqlite", "mysql", "postgres"]
    display_name: str = ""
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    sqlite_path: str | None = None


class StructuredConnectionCreate(StructuredConnectionTestRequest):
    pass


class StructuredConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    engine: str
    dataset_count: int = 0


class StructuredConnectionOut(BaseModel):
    id: str
    engine: Literal["sqlite", "mysql", "postgres"]
    display_name: str
    last_test_status: str | None = None
    last_tested_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class StructuredColumnProfile(BaseModel):
    name: str
    data_type: str = "string"
    null_rate: float = 0
    unique_rate: float = 0
    sample_values: list[Any] = Field(default_factory=list)
    entity_type: str = "CUSTOM"
    risk_level: StructuredRiskLevel = "low"
    confidence: float = 0
    reasons: list[str] = Field(default_factory=list)
    recommended_policy: StructuredPolicyAction = "keep"


class StructuredProfileResponse(BaseModel):
    dataset_id: str
    shape_kind: StructuredShapeKind
    row_count_estimate: int | None = None
    sampled_rows: int = 0
    columns: list[StructuredColumnProfile] = Field(default_factory=list)
    semantic_inference: dict[str, Any] = Field(default_factory=dict)


class StructuredColumnPolicy(BaseModel):
    column: str
    action: StructuredPolicyAction = "keep"
    entity_type: str = "CUSTOM"
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class StructuredPolicyBody(BaseModel):
    columns: list[StructuredColumnPolicy] = Field(default_factory=list)


class StructuredPolicyResponse(BaseModel):
    dataset_id: str
    columns: list[StructuredColumnPolicy] = Field(default_factory=list)
    updated_at: str | None = None


class StructuredPreviewResponse(BaseModel):
    dataset_id: str
    columns: list[str] = Field(default_factory=list)
    original_rows: list[dict[str, Any]] = Field(default_factory=list)
    redacted_rows: list[dict[str, Any]] = Field(default_factory=list)
    policy: list[StructuredColumnPolicy] = Field(default_factory=list)


class StructuredJobCreate(BaseModel):
    title: str = ""
    dataset_ids: list[str] = Field(..., min_length=1, max_length=100)
    export_format: StructuredExportFormat = "csv"
    skip_review: bool = True
    auto_submit: bool = True


class StructuredJobResponse(BaseModel):
    job: dict[str, Any]
    datasets: list[StructuredDatasetOut] = Field(default_factory=list)
