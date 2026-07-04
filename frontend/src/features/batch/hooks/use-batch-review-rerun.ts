// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useRef, useState } from 'react';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';
import { authFetch, VISION_TIMEOUT } from '@/services/api-client';
import { batchGetFileRaw } from '@/services/batchPipeline';
import type { ReviewEntity } from '../types';
import { fetchCachedBatchPreviewMap, normalizeReviewEntity } from './use-batch-wizard-utils';
import {
  normalizePage,
  normalizeReviewBox,
  normalizeVisionQualityByPage,
} from './use-batch-review-normalize';
import type { ReviewDataDeps } from './use-batch-review-data';

type ReviewRerunDeps = Pick<
  ReviewDataDeps,
  | 'reviewFile'
  | 'cfg'
  | 'reviewEntities'
  | 'reviewBoxes'
  | 'visibleReviewBoxes'
  | 'reviewTotalPages'
  | 'reviewDraftDirtyRef'
  | 'setPreviewEntityMap'
  | 'setReviewEntities'
  | 'setReviewBoxes'
  | 'setReviewCurrentPage'
  | 'setReviewTotalPages'
  | 'setReviewVisionQualityByPage'
  | 'setReviewTextUndoStack'
  | 'setReviewTextRedoStack'
  | 'setReviewImageUndoStack'
  | 'setReviewImageRedoStack'
  | 'setMsg'
>;

export function useReviewRerun(deps: ReviewRerunDeps): {
  rerunCurrentItemRecognition: () => Promise<void>;
  rerunRecognitionLoading: boolean;
} {
  const {
    reviewFile,
    cfg,
    reviewEntities,
    reviewBoxes,
    visibleReviewBoxes,
    reviewTotalPages,
    reviewDraftDirtyRef,
    setPreviewEntityMap,
    setReviewEntities,
    setReviewBoxes,
    setReviewCurrentPage,
    setReviewTotalPages,
    setReviewVisionQualityByPage,
    setReviewTextUndoStack,
    setReviewTextRedoStack,
    setReviewImageUndoStack,
    setReviewImageRedoStack,
    setMsg,
  } = deps;

  const rerunAbortRef = useRef<AbortController | null>(null);
  const [rerunRecognitionLoading, setRerunRecognitionLoading] = useState(false);

  useEffect(
    () => () => {
      rerunAbortRef.current?.abort();
    },
    [],
  );

  const rerunCurrentItemRecognition = useCallback(async () => {
    if (!reviewFile) return;
    const isImage = reviewFile.isImageMode === true;
    const hasManualDraft =
      reviewDraftDirtyRef.current ||
      reviewEntities.length > 0 ||
      reviewBoxes.length > 0 ||
      visibleReviewBoxes.length > 0;
    if (
      hasManualDraft &&
      typeof window !== 'undefined' &&
      !window.confirm(t('batchWizard.step4.rerunRecognitionConfirm'))
    ) {
      setMsg({ text: t('batchWizard.step4.rerunRecognitionCancelled'), tone: 'neutral' });
      return;
    }

    rerunAbortRef.current?.abort();
    const controller = new AbortController();
    rerunAbortRef.current = controller;

    setRerunRecognitionLoading(true);
    try {
      if (isImage) {
        let pages = Math.max(1, reviewTotalPages);
        try {
          const info = await batchGetFileRaw(reviewFile.file_id);
          pages = Math.max(1, normalizePage(info.page_count, pages));
        } catch {
          /* fallback to current known total pages */
        }

        setReviewBoxes([]);
        setReviewImageUndoStack([]);
        setReviewImageRedoStack([]);
        setReviewTotalPages(pages);
        let maxBoxPage = 1;
        for (let page = 1; page <= pages; page += 1) {
          let res: Response | null = null;
          for (let attempt = 1; attempt <= 2; attempt += 1) {
            const timer = window.setTimeout(() => controller.abort(), VISION_TIMEOUT);
            try {
              res = await authFetch(
                `/api/v1/redaction/${reviewFile.file_id}/vision?page=${page}&include_result_image=false&force=true`,
                {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    selected_ocr_has_types: cfg.ocrHasTypes,
                    selected_visual_feature_types: Array.from(new Set(cfg.visualFeatureTypes)),
                  }),
                  signal: controller.signal,
                },
              );
            } finally {
              window.clearTimeout(timer);
            }

            if (controller.signal.aborted) return;
            if (res.ok) break;
            if (attempt >= 2) throw new Error(t('error.visionDetectionFailed'));
          }

          if (controller.signal.aborted) return;
          if (!res || !res.ok) throw new Error(t('error.visionDetectionFailed'));
          const data = (await res.json()) as {
            bounding_boxes?: Array<Record<string, unknown>>;
            warnings?: unknown[];
            pipeline_status?: Record<string, Record<string, unknown>>;
          };
          if (controller.signal.aborted) return;

          const pageBoxes = (data.bounding_boxes || []).map((box, index) =>
            normalizeReviewBox(box, index, page),
          );
          setReviewVisionQualityByPage((prev) => ({
            ...prev,
            [page]: {
              warnings: Array.isArray(data.warnings)
                ? data.warnings.filter((warning): warning is string => typeof warning === 'string')
                : [],
              pipeline_status:
                normalizeVisionQualityByPage({
                  [page]: {
                    pipeline_status: data.pipeline_status ?? {},
                    warnings: data.warnings ?? [],
                  },
                })[page]?.pipeline_status ?? {},
            },
          }));
          maxBoxPage = pageBoxes.reduce(
            (max, box) => Math.max(max, normalizePage(box.page, 1)),
            maxBoxPage,
          );
          const currentTotalPages = Math.max(pages, maxBoxPage);
          setReviewBoxes((prev) => [...prev, ...pageBoxes]);
          setReviewTotalPages(currentTotalPages);
          setReviewCurrentPage((prev) => Math.min(Math.max(1, prev), currentTotalPages));
        }

        if (controller.signal.aborted) return;
      } else {
        const nerRes = await authFetch(`/api/v1/files/${reviewFile.file_id}/ner/hybrid`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entity_type_ids: cfg.selectedEntityTypeIds }),
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (!nerRes.ok) throw new Error('NER recognition failed');
        const nerData = await nerRes.json();
        if (controller.signal.aborted) return;
        const entities: ReviewEntity[] = (
          (nerData.entities || []) as Record<string, unknown>[]
        ).map((entity, index) =>
          normalizeReviewEntity({
            id: String(entity.id || `ent_${index}`),
            text: String(entity.text ?? ''),
            type: String(entity.type ?? 'CUSTOM'),
            start: Number(entity.start ?? 0),
            end: Number(entity.end ?? 0),
            selected: true,
            source: (entity.source as ReviewEntity['source']) || 'llm',
            page: Number(entity.page ?? 1),
            confidence: typeof entity.confidence === 'number' ? entity.confidence : 1,
            coref_id: entity.coref_id as string | undefined,
            replacement: entity.replacement as string | undefined,
          }),
        );
        setReviewEntities(entities);
        setReviewTextUndoStack([]);
        setReviewTextRedoStack([]);
        const map = await fetchCachedBatchPreviewMap(entities, cfg.replacementMode);
        if (controller.signal.aborted) return;
        setPreviewEntityMap(map);
      }
      reviewDraftDirtyRef.current = true;
    } catch (error) {
      if (controller.signal.aborted) return;
      setMsg({ text: localizeErrorMessage(error, 'batchWizard.actionFailed'), tone: 'err' });
    } finally {
      if (!controller.signal.aborted) setRerunRecognitionLoading(false);
    }
  }, [
    reviewFile,
    reviewEntities.length,
    reviewBoxes.length,
    visibleReviewBoxes.length,
    reviewTotalPages,
    cfg.selectedEntityTypeIds,
    cfg.ocrHasTypes,
    cfg.visualFeatureTypes,
    cfg.replacementMode,
    reviewDraftDirtyRef,
    setMsg,
    setPreviewEntityMap,
    setReviewBoxes,
    setReviewCurrentPage,
    setReviewEntities,
    setReviewImageRedoStack,
    setReviewImageUndoStack,
    setReviewTextRedoStack,
    setReviewTextUndoStack,
    setReviewTotalPages,
    setReviewVisionQualityByPage,
  ]);

  return { rerunCurrentItemRecognition, rerunRecognitionLoading };
}
