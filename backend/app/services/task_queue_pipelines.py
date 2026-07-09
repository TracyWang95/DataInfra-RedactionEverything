"""按任务类型拆分的执行流水线（识别 / 结构化 / 匿名化），以 mixin 形式提供。

从 task_queue.py 拆出。三个 mixin 只通过 self 调用核心队列提供的共享方法
（_get_store / _record_task_started / _record_item_performance /
_try_update_job_status / _refresh_job_status / enqueue），不直接触碰队列
内部数据结构，故对同一 SimpleTaskQueue 实例的状态与引用完全透明。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from app.services.task_queue_metrics import (
    _duration_breakdown_from_quality,
    _effective_vision_page_concurrency,
    _elapsed_ms,
    _file_type_value,
    _gpu_memory_metadata,
    _page_vision_quality_from_file_info,
    _page_vision_quality_from_result,
    _utc_iso,
    _vision_page_concurrency_reason,
)

if TYPE_CHECKING:
    from app.services.job_store import JobStore
    from app.services.task_queue import TaskItem

logger = logging.getLogger(__name__)
# Truncation length for stored error messages (name for repeated literal).
_ERROR_MSG_MAX_LEN = 500


class RecognitionPipelineMixin:
    """识别流水线：解析 -> NER/Vision -> 完成识别（可选入队匿名化）。"""

    async def _run_recognition(self, task: TaskItem) -> None:
        from app.services.job_store import JobItemStatus, JobStatus

        started = time.perf_counter()
        store = self._get_store()
        self._record_task_started(task, store)
        job = store.get_job(task.job_id)
        if not job:
            logger.warning("job %s not found, skip", task.job_id[:8])
            return

        item = store.get_item(task.item_id)
        if not item:
            logger.warning("item %s not found, skip", task.item_id[:8])
            return

        # 跳过已完成 / 已取消的（PENDING 和 PROCESSING 允许重试）
        skip_statuses = (
            JobItemStatus.AWAITING_REVIEW.value,
            JobItemStatus.COMPLETED.value,
            JobItemStatus.CANCELLED.value if hasattr(JobItemStatus, "CANCELLED") else "__none__",
        )
        if item["status"] in skip_statuses:
            logger.info("item %s already %s, skip", task.item_id[:8], item["status"])
            return

        # 检查 job 是否已被取消
        if job.get("status") == JobStatus.CANCELLED.value:
            logger.info("job %s cancelled, skip item %s", task.job_id[:8], task.item_id[:8])
            return

        cfg = json.loads(job.get("config_json") or "{}")

        try:
            # 标记处理中
            store.update_item_status(task.item_id, JobItemStatus.PROCESSING)
            self._try_update_job_status(store, task.job_id, JobStatus.PROCESSING)

            # 1) 解析
            parse_started = time.perf_counter()
            await self._parse_file(task)
            parse_ms = _elapsed_ms(parse_started)
            self._record_item_performance(store, task.item_id, {"recognition": {"parse_ms": parse_ms}})
            logger.info(
                "[queue] item=%s parse elapsed=%.2fs",
                task.item_id[:8],
                parse_ms / 1000,
            )

            # 2) NER 鎴?Vision
            stage_started = time.perf_counter()
            await self._run_ner_or_vision(task, cfg)
            recognition_stage_ms = _elapsed_ms(stage_started)
            self._record_item_performance(store, task.item_id, {"recognition": {"model_ms": recognition_stage_ms}})
            logger.info(
                "[queue] item=%s recognition stage elapsed=%.2fs",
                task.item_id[:8],
                recognition_stage_ms / 1000,
            )

            # 3) 完成识别
            self._mark_recognition_complete(task, job, store)

        except (FileNotFoundError, OSError) as e:
            err_msg = str(e)[:_ERROR_MSG_MAX_LEN]
            logger.error("[queue] item=%s recognition I/O error: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                logger.warning("failed to mark item %s as FAILED (item not found or invalid transition)", task.item_id[:8])
        except TimeoutError as e:
            err_msg = str(e)[:_ERROR_MSG_MAX_LEN] or "recognition timed out"
            logger.error("[queue] item=%s recognition timeout: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                logger.warning("failed to mark item %s as FAILED (item not found or invalid transition)", task.item_id[:8])
        except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as e:
            err_msg = str(e)[:_ERROR_MSG_MAX_LEN]
            logger.error("[queue] item=%s recognition failed: %s: %s", task.item_id[:8], type(e).__name__, err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                logger.warning("failed to mark item %s as FAILED (item not found or invalid transition)", task.item_id[:8])
        except Exception as e:
            err_msg = str(e)[:_ERROR_MSG_MAX_LEN]
            logger.exception("[queue] item=%s recognition failed (unexpected): %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except Exception:
                logger.exception("failed to mark item %s as FAILED", task.item_id[:8])
        finally:
            total_ms = _elapsed_ms(started)
            self._record_item_performance(
                store,
                task.item_id,
                {"recognition": {"finished_at": _utc_iso(), "duration_ms": total_ms}},
            )
            logger.info(
                "[queue] item=%s recognition total elapsed=%.2fs",
                task.item_id[:8],
                total_ms / 1000,
            )
            store.touch_job_updated(task.job_id)
            self._refresh_job_status(store, task.job_id)

    async def _parse_file(self, task: TaskItem) -> None:
        """Parse the uploaded file."""
        from app.services.file_operations import parse_file

        logger.info("[queue] item=%s parse", task.item_id[:8])
        await parse_file(task.file_id)

    async def _run_ner(self, task: TaskItem, entity_type_ids: list) -> None:
        """Run text recognition."""
        from app.services.file_operations import hybrid_ner

        store = self._get_store()
        store.update_item_progress(
            task.item_id,
            stage="ner",
            current=1,
            total=1,
            message="text_recognition_running",
        )
        logger.info("[queue] item=%s NER (%d types)", task.item_id[:8], len(entity_type_ids))
        ner_started = time.perf_counter()
        await hybrid_ner(task.file_id, entity_type_ids)
        self._record_item_performance(
            store,
            task.item_id,
            {
                "recognition": {
                    "mode": "text",
                    "ner_ms": _elapsed_ms(ner_started),
                    "entity_type_count": len(entity_type_ids),
                }
            },
        )
        store.update_item_progress(
            task.item_id,
            stage="ner",
            current=1,
            total=1,
            message="text_recognition_complete",
        )

    async def _run_vision(self, task: TaskItem, cfg: dict) -> None:
        """Run OCR and visual feature recognition for images or scanned pages."""
        from app.core.config import settings
        from app.services.file_operations import get_file_info, vision_detect
        from app.services.vision_config import resolve_optional_type_list

        fi = get_file_info(task.file_id) or {}
        ocr_types = resolve_optional_type_list(cfg, "ocr_has_types", "selected_ocr_has_types")
        configured_visual_types = resolve_optional_type_list(
            cfg,
            "visual_feature_types",
            "visualFeatureTypes",
            "selected_visual_feature_types",
        )
        visual_feature_types = configured_visual_types
        pages = int(fi.get("page_count") or 1)
        vision_started = time.perf_counter()
        logger.info(
            "[queue] item=%s vision (ocr=%s, visual_features=%s, pages=%d)",
            task.item_id[:8],
            len(ocr_types) if ocr_types is not None else "default",
            len(visual_feature_types) if visual_feature_types is not None else "default",
            pages,
        )
        # Pass empty lists as-is (user explicitly deselected a pipeline).
        # Missing keys stay None so orchestrator defaults still apply.
        page_timeout = float(settings.BATCH_RECOGNITION_PAGE_TIMEOUT)
        configured_page_concurrency = int(settings.BATCH_RECOGNITION_PAGE_CONCURRENCY)
        gpu_memory = None
        if pages > 1 and configured_page_concurrency > 1:
            try:
                from app.core.gpu_memory import query_gpu_memory

                gpu_memory = query_gpu_memory()
            except Exception:
                logger.debug("unable to query GPU memory for vision concurrency", exc_info=True)
        page_concurrency = _effective_vision_page_concurrency(
            fi,
            pages,
            configured_page_concurrency,
            gpu_memory=gpu_memory,
        )
        page_concurrency_reason = _vision_page_concurrency_reason(
            pages,
            configured_page_concurrency,
            page_concurrency,
            gpu_memory,
        )
        sparse_probe: dict[str, Any] = {"ran": False}
        if pages > 1 and _file_type_value(fi.get("file_type")) == "pdf_scanned":
            try:
                from app.services.vision_service import prime_pdf_text_layer_sparse_probe

                sparse_probe = await prime_pdf_text_layer_sparse_probe(
                    str(fi.get("file_path") or ""),
                    fi.get("file_type"),
                    page=1,
                )
            except Exception:
                sparse_probe = {"ran": False, "error": "probe_failed"}
                logger.debug("unable to prime scanned PDF text-layer sparse probe", exc_info=True)
        page_sem = asyncio.Semaphore(page_concurrency)
        store = self._get_store()
        store.update_item_progress(
            task.item_id,
            stage="vision",
            current=0,
            total=pages,
            message=f"Vision recognition queued for {pages} page(s)",
        )
        self._record_item_performance(
            store,
            task.item_id,
            {
                "recognition": {
                    "mode": "vision",
                    "page_count": pages,
                    "page_concurrency": page_concurrency,
                    "page_concurrency_configured": configured_page_concurrency,
                    "page_concurrency_reason": page_concurrency_reason,
                    "gpu_memory": _gpu_memory_metadata(gpu_memory),
                    "pdf_text_layer_sparse_probe": sparse_probe,
                    "pages": {},
                }
            },
        )
        active_pages = 0
        max_active_pages = 0

        async def run_page(
            p: int,
            *,
            selected_ocr_types: list[str] | None,
            selected_visual_feature_types: list[str] | None,
            merge_existing: bool = False,
            signature_ocr_types: list[str] | None = None,
            signature_visual_feature_types: list[str] | None = None,
            stage_label: str = "视觉识别",
        ) -> None:
            nonlocal active_pages, max_active_pages
            async with page_sem:
                page_started = time.perf_counter()
                page_started_at = _utc_iso()
                active_pages += 1
                max_active_pages = max(max_active_pages, active_pages)
                active_at_start = active_pages
                store.update_item_progress(
                    task.item_id,
                    stage="vision",
                    current=p,
                    total=pages,
                    message=f"{stage_label} page {p}/{pages}",
                )
                logger.info(
                    "[queue] item=%s %s page %d/%d START (page_concurrency=%d active_pages=%d)",
                    task.item_id[:8], stage_label, p, pages, page_concurrency, active_at_start,
                )
                self._record_item_performance(
                    store,
                    task.item_id,
                    {
                        "recognition": {
                            "pages": {
                                str(p): {
                                    "page": p,
                                    "started_at": page_started_at,
                                    "active_pages_at_start": active_at_start,
                                    "page_concurrency": page_concurrency,
                                }
                            }
                        }
                    },
                )
                try:
                    result = await asyncio.wait_for(
                        vision_detect(
                            task.file_id,
                            p,
                            ocr_has_types=selected_ocr_types,
                            visual_feature_types=selected_visual_feature_types,
                            merge_existing=merge_existing,
                            signature_ocr_has_types=signature_ocr_types,
                            signature_visual_feature_types=signature_visual_feature_types,
                        ),
                        timeout=page_timeout,
                    )
                except TimeoutError as exc:
                    page_ms = _elapsed_ms(page_started)
                    active_pages = max(0, active_pages - 1)
                    self._record_item_performance(
                        store,
                        task.item_id,
                        {
                            "recognition": {
                                "pages": {
                                    str(p): {
                                        "finished_at": _utc_iso(),
                                        "duration_ms": page_ms,
                                        "status": "timeout",
                                        "active_pages_at_end": active_pages,
                                    }
                                }
                            }
                        },
                    )
                    raise TimeoutError(
                        f"{stage_label} page {p}/{pages} timed out after {page_timeout:.0f}s"
                    ) from exc
                except Exception:
                    page_ms = _elapsed_ms(page_started)
                    active_pages = max(0, active_pages - 1)
                    self._record_item_performance(
                        store,
                        task.item_id,
                        {
                            "recognition": {
                                "pages": {
                                    str(p): {
                                        "finished_at": _utc_iso(),
                                        "duration_ms": page_ms,
                                        "status": "failed",
                                        "active_pages_at_end": active_pages,
                                    }
                                }
                            }
                        },
                    )
                    raise
                else:
                    page_ms = _elapsed_ms(page_started)
                    active_pages = max(0, active_pages - 1)
                    active_at_end = active_pages
                    quality = _page_vision_quality_from_result(result)
                    if not any(quality.values()):
                        quality = _page_vision_quality_from_file_info(get_file_info(task.file_id) or {}, p)
                    self._record_item_performance(
                        store,
                        task.item_id,
                        {
                            "recognition": {
                                "pages": {
                                    str(p): {
                                        "page": p,
                                        "finished_at": _utc_iso(),
                                        "duration_ms": page_ms,
                                        "status": "completed",
                                        "active_pages_at_end": active_at_end,
                                        "duration_breakdown_ms": _duration_breakdown_from_quality(quality),
                                        "cache_status": dict(quality.get("cache_status") or {}),
                                        "pipeline_status": dict(quality.get("pipeline_status") or {}),
                                        "warnings": list(quality.get("warnings") or []),
                                    }
                                }
                            }
                        },
                    )
                    logger.info(
                        "[queue] item=%s %s page %d/%d DONE elapsed=%.2fs active_pages=%d",
                        task.item_id[:8],
                        stage_label,
                        p,
                        pages,
                        page_ms / 1000,
                        active_at_end,
                    )

        async def run_page_stage(
            *,
            selected_ocr_types: list[str] | None,
            selected_visual_feature_types: list[str] | None,
            merge_existing: bool = False,
            signature_ocr_types: list[str] | None = None,
            signature_visual_feature_types: list[str] | None = None,
            stage_label: str = "视觉识别",
        ) -> None:
            page_tasks = {
                asyncio.create_task(
                    run_page(
                        p,
                        selected_ocr_types=selected_ocr_types,
                        selected_visual_feature_types=selected_visual_feature_types,
                        merge_existing=merge_existing,
                        signature_ocr_types=signature_ocr_types,
                        signature_visual_feature_types=signature_visual_feature_types,
                        stage_label=stage_label,
                    )
                ): p
                for p in range(1, max(1, pages) + 1)
            }
            try:
                for page_task in asyncio.as_completed(page_tasks):
                    await page_task
            except Exception:
                for page_task in page_tasks:
                    page_task.cancel()
                raise

        try:
            if pages > 1 and visual_feature_types != []:
                # Merge-pass concurrency: default 1 = historical serial behaviour;
                # capped by the effective page concurrency so the GPU-saturation
                # downgrade above also applies here.
                visual_merge_concurrency = max(
                    1,
                    min(
                        int(settings.BATCH_VISUAL_MERGE_PAGE_CONCURRENCY),
                        page_concurrency,
                    ),
                )
                logger.info(
                    "[queue] item=%s vision multi-page scheduling: OCR first (concurrency=%d), then visual features merge pass (concurrency=%d)",
                    task.item_id[:8],
                    page_concurrency,
                    visual_merge_concurrency,
                )
                await run_page_stage(
                    selected_ocr_types=ocr_types,
                    selected_visual_feature_types=[],
                    stage_label="OCR+HaS识别",
                )
                page_sem = asyncio.Semaphore(visual_merge_concurrency)
                await run_page_stage(
                    selected_ocr_types=[],
                    selected_visual_feature_types=visual_feature_types,
                    merge_existing=True,
                    signature_ocr_types=ocr_types,
                    signature_visual_feature_types=visual_feature_types,
                    stage_label="视觉特征识别",
                )
            else:
                await run_page_stage(
                    selected_ocr_types=ocr_types,
                    selected_visual_feature_types=visual_feature_types,
                )
            store.update_item_progress(
                task.item_id,
                stage="vision",
                current=pages,
                total=pages,
                message="vision_recognition_complete",
            )
            self._record_item_performance(
                store,
                task.item_id,
                {
                    "recognition": {
                        "vision_ms": _elapsed_ms(vision_started),
                        "max_active_pages": max_active_pages,
                    }
                },
            )
            logger.info(
                "[queue] item=%s vision total elapsed=%.2fs pages=%d page_concurrency=%d max_active_pages=%d",
                task.item_id[:8],
                time.perf_counter() - vision_started,
                pages,
                page_concurrency,
                max_active_pages,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"vision recognition timed out after {page_timeout:.0f}s per page"
            ) from exc

    async def _run_ner_or_vision(self, task: TaskItem, cfg: dict) -> None:
        """Choose text or vision recognition based on file type."""
        from app.services.file_operations import get_file_info

        fi = get_file_info(task.file_id) or {}
        ft = str(fi.get("file_type", ""))
        is_img = ft == "image" or bool(fi.get("is_scanned"))

        if is_img:
            await self._run_vision(task, cfg)
        else:
            entity_type_ids = list(cfg.get("entity_type_ids") or [])
            await self._run_ner(task, entity_type_ids)

    def _mark_recognition_complete(self, task: TaskItem, job: dict, store: JobStore) -> None:
        """Mark recognition complete and optionally enqueue redaction."""
        from app.services.job_store import JobItemStatus
        from app.services.task_queue import TaskItem

        skip_review = bool(job.get("skip_item_review"))
        store.update_item_status(task.item_id, JobItemStatus.AWAITING_REVIEW)

        if skip_review:
            # skip_item_review=true: 直接入队匿名化，不等人工审阅
            # 使用 enqueue() 而非直接 put_nowait()，确保去重逻辑一致
            logger.info("[queue] item=%s skip review, enqueue redaction", task.item_id[:8])
            self.enqueue(TaskItem(
                job_id=task.job_id, item_id=task.item_id,
                file_id=task.file_id, task_type="redaction",
            ))
        else:
            logger.info("[queue] item=%s awaiting_review", task.item_id[:8])


class StructuredPipelineMixin:
    """结构化数据集导出流水线。"""

    async def _run_structured(self, task: TaskItem) -> None:
        from app.services.job_store import JobItemStatus, JobStatus
        from app.services.structured_service import run_structured_job_item

        started = time.perf_counter()
        store = self._get_store()
        self._record_task_started(task, store)
        job = store.get_job(task.job_id)
        if not job:
            return
        item = store.get_item(task.item_id)
        if not item or item["status"] == JobItemStatus.COMPLETED.value:
            return
        if job.get("status") == JobStatus.CANCELLED.value:
            return

        cfg = json.loads(job.get("config_json") or "{}")
        owner_id = str(job.get("owner_id") or "local_user")
        export_format = str(cfg.get("export_format") or "csv")
        try:
            store.update_item_status(task.item_id, JobItemStatus.PROCESSING)
            self._try_update_job_status(store, task.job_id, JobStatus.PROCESSING)
            result = await run_structured_job_item(
                job_id=task.job_id,
                item_id=task.item_id,
                dataset_id=task.file_id,
                owner_id=owner_id,
                export_format=export_format,
                store=store,
            )
            self._record_item_performance(
                store,
                task.item_id,
                {
                    "structured": {
                        "finished_at": _utc_iso(),
                        "duration_ms": result.get("duration_ms") or _elapsed_ms(started),
                        "export": result.get("export"),
                        "profile": result.get("profile"),
                    }
                },
            )
            store.update_item_status(task.item_id, JobItemStatus.COMPLETED)
            logger.info("[queue] item=%s structured export completed", task.item_id[:8])
        except (RuntimeError, ValueError, KeyError, OSError) as exc:
            err_msg = str(exc)[:_ERROR_MSG_MAX_LEN]
            logger.error("[queue] item=%s structured failed: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                pass
        except Exception as exc:
            err_msg = str(exc)[:_ERROR_MSG_MAX_LEN]
            logger.exception("[queue] item=%s structured failed (unexpected): %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except Exception:
                pass
        finally:
            self._record_item_performance(
                store,
                task.item_id,
                {"structured": {"last_seen_duration_ms": _elapsed_ms(started)}},
            )
            store.touch_job_updated(task.job_id)
            self._refresh_job_status(store, task.job_id)


class RedactionPipelineMixin:
    """匿名化（脱敏）流水线。"""

    async def _run_redaction(self, task: TaskItem) -> None:
        from app.models.schemas import RedactionConfig, ReplacementMode
        from app.services.file_operations import execute_redaction_request, get_file_info
        from app.services.job_store import JobItemStatus

        started = time.perf_counter()
        store = self._get_store()
        self._record_task_started(task, store)
        job = store.get_job(task.job_id)
        if not job:
            return

        item = store.get_item(task.item_id)
        if not item or item["status"] == JobItemStatus.COMPLETED.value:
            return

        cfg = json.loads(job.get("config_json") or "{}")

        try:
            store.update_item_status(task.item_id, JobItemStatus.PROCESSING)

            fi = get_file_info(task.file_id)
            if not fi:
                raise RuntimeError(f"file not found: {task.file_id}")
            if fi.get("output_path"):
                # 已匿名化
                self._record_item_performance(
                    store,
                    task.item_id,
                    {
                        "redaction": {
                            "finished_at": _utc_iso(),
                            "duration_ms": _elapsed_ms(started),
                            "skipped_existing_output": True,
                        }
                    },
                )
                store.update_item_status(task.item_id, JobItemStatus.COMPLETED)
                return

            from app.models.schemas import BoundingBox, Entity
            raw_ents = fi.get("entities") or []
            entities = []
            for e in raw_ents:
                if isinstance(e, Entity):
                    entities.append(e)
                elif isinstance(e, dict):
                    entities.append(Entity.model_validate(e))

            raw_boxes = fi.get("bounding_boxes")
            boxes = []
            if isinstance(raw_boxes, list):
                for b in raw_boxes:
                    if isinstance(b, dict):
                        boxes.append(BoundingBox.model_validate(b))
            elif isinstance(raw_boxes, dict):
                for pk, arr in raw_boxes.items():
                    page_num = int(pk) if str(pk).isdigit() else 1
                    if isinstance(arr, list):
                        for b in arr:
                            if isinstance(b, dict):
                                d = {**b, "page": b.get("page", page_num)}
                                boxes.append(BoundingBox.model_validate(d))

            rm = cfg.get("replacement_mode") or "structured"
            try:
                replacement_mode = ReplacementMode(str(rm))
            except ValueError:
                replacement_mode = ReplacementMode.STRUCTURED

            config = RedactionConfig(
                replacement_mode=replacement_mode,
                entity_types=list(cfg.get("entity_type_ids") or []),
                custom_replacements=dict(cfg.get("custom_replacements") or {}),
                image_redaction_method=cfg.get("image_redaction_method"),
                image_redaction_strength=int(cfg.get("image_redaction_strength") or 75),
                image_fill_color=str(cfg.get("image_fill_color") or "#000000"),
                watermark_text=(str(cfg.get("watermark_text") or "").strip() or None),
            )
            await execute_redaction_request(task.file_id, entities, boxes, config)
            self._record_item_performance(
                store,
                task.item_id,
                {
                    "redaction": {
                        "finished_at": _utc_iso(),
                        "duration_ms": _elapsed_ms(started),
                        "entity_count": len(entities),
                        "bounding_box_count": len(boxes),
                    }
                },
            )
            store.update_item_status(task.item_id, JobItemStatus.COMPLETED)
            logger.info("[queue] item=%s redaction completed", task.item_id[:8])

        except (FileNotFoundError, OSError) as e:
            err_msg = str(e)[:_ERROR_MSG_MAX_LEN]
            logger.error("[queue] item=%s redaction I/O error: %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                pass
        except (RuntimeError, ValueError, KeyError) as e:
            err_msg = str(e)[:_ERROR_MSG_MAX_LEN]
            logger.error("[queue] item=%s redaction failed: %s: %s", task.item_id[:8], type(e).__name__, err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except (KeyError, ValueError):
                pass
        except Exception as e:
            err_msg = str(e)[:_ERROR_MSG_MAX_LEN]
            logger.exception("[queue] item=%s redaction failed (unexpected): %s", task.item_id[:8], err_msg)
            try:
                store.update_item_status(task.item_id, JobItemStatus.FAILED, error_message=err_msg)
            except Exception:
                pass
        finally:
            self._record_item_performance(
                store,
                task.item_id,
                {"redaction": {"last_seen_duration_ms": _elapsed_ms(started)}},
            )
            store.touch_job_updated(task.job_id)
            self._refresh_job_status(store, task.job_id)
