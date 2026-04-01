"""Celery 应用配置 — 使用 Redis 作为 Broker 和 Result Backend。"""
import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "legal_redaction",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks.job_tasks"],
)

celery_app.conf.update(
    # 序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
    # ——— 可靠性核心设置 ———
    # worker 崩溃前不 ack，任务自动回到队列
    task_acks_late=True,
    # worker 进程意外退出时拒绝（而非丢弃）任务，让 broker 重新入队
    task_reject_on_worker_lost=True,
    # 每个 worker 每次只预取 1 个任务，防止批量拉走后崩溃丢失多个任务
    worker_prefetch_multiplier=1,
    # ——— 单 GPU 串行 ———
    # 单张 4090 显卡，同一时刻只能跑一个识别/脱敏任务，避免 GPU OOM
    worker_concurrency=1,
    # ——— 超时设置 ———
    # 识别/脱敏单个文件最多 30 分钟，超时后标记失败（soft 先发 SIGTERM，hard 再发 SIGKILL）
    task_soft_time_limit=1800,
    task_time_limit=1860,
    # ——— 结果过期 ———
    result_expires=86400,  # 任务结果 24 小时后自动清理
)
