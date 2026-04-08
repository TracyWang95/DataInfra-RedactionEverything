"""
Prometheus 监控指标 — 识别/匿名化延迟、错误率、队列深度。

/metrics 端点由 main.py 挂载。
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.requests import Request
from starlette.responses import Response

# ──────────────────────────────────────────────
# 文件处理
# ──────────────────────────────────────────────
FILE_UPLOAD_TOTAL = Counter(
    "redaction_file_upload_total",
    "Total file uploads",
    ["file_type"],
)

FILE_PARSE_DURATION = Histogram(
    "redaction_file_parse_seconds",
    "File parsing duration",
    ["file_type"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)

# ──────────────────────────────────────────────
# NER 识别
# ──────────────────────────────────────────────
NER_DURATION = Histogram(
    "redaction_ner_seconds",
    "NER recognition duration",
    ["backend"],  # has / regex / hybrid
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120],
)

NER_ENTITY_COUNT = Histogram(
    "redaction_ner_entity_count",
    "Number of entities found per NER call",
    buckets=[0, 5, 10, 25, 50, 100, 500, 1000],
)

NER_ERRORS = Counter(
    "redaction_ner_errors_total",
    "NER errors",
    ["error_type"],  # timeout / network / model
)

# ──────────────────────────────────────────────
# 视觉识别
# ──────────────────────────────────────────────
VISION_DURATION = Histogram(
    "redaction_vision_seconds",
    "Vision detection duration",
    ["pipeline"],  # ocr_has / has_image
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

# ──────────────────────────────────────────────
# 匿名化执行
# ──────────────────────────────────────────────
REDACTION_DURATION = Histogram(
    "redaction_execute_seconds",
    "Redaction execution duration",
    ["file_type"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)

REDACTION_COUNT = Counter(
    "redaction_executed_total",
    "Total redaction executions",
    ["replacement_mode"],
)

# ──────────────────────────────────────────────
# Job 队列
# ──────────────────────────────────────────────
JOB_QUEUE_DEPTH = Gauge(
    "redaction_job_queue_depth",
    "Current number of jobs in schedulable state",
)

JOB_ITEM_PROCESSED = Counter(
    "redaction_job_item_processed_total",
    "Job items processed",
    ["status"],  # completed / failed
)

# ──────────────────────────────────────────────
# HTTP 请求
# ──────────────────────────────────────────────
HTTP_REQUEST_DURATION = Histogram(
    "redaction_http_request_seconds",
    "HTTP request duration",
    ["method", "path_template", "status_code"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)


async def metrics_endpoint(request: Request) -> Response:
    """GET /metrics — Prometheus scrape 端点"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
