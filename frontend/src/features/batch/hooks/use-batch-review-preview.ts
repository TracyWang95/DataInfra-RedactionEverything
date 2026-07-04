// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useMemo, useState } from 'react';
import { ReplacementMode } from '@/types';
import { batchPreviewImage } from '@/services/batchPipeline';
import { fetchCachedBatchPreviewMap } from './use-batch-wizard-utils';
import { normalizePage } from './use-batch-review-normalize';
import type { ReviewDataDeps } from './use-batch-review-data';

type ReviewTextPreviewMapDeps = Pick<
  ReviewDataDeps,
  | 'step'
  | 'reviewFile'
  | 'isPreviewMode'
  | 'cfg'
  | 'reviewEntities'
  | 'reviewTextContent'
  | 'reviewLoading'
  | 'previewEntityMap'
  | 'setPreviewEntityMap'
>;

export function useReviewTextPreviewMap(deps: ReviewTextPreviewMapDeps): void {
  const {
    step,
    reviewFile,
    isPreviewMode,
    cfg,
    reviewEntities,
    reviewTextContent,
    reviewLoading,
    previewEntityMap,
    setPreviewEntityMap,
  } = deps;

  useEffect(() => {
    if (isPreviewMode) return;
    if (step !== 4 || !reviewFile || reviewLoading || reviewFile.isImageMode) return;
    if (!reviewTextContent) {
      setPreviewEntityMap({});
      return;
    }
    if (reviewEntities.length === 0) return;
    if (reviewFile.has_output === true && Object.keys(previewEntityMap).length > 0) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const map = await fetchCachedBatchPreviewMap(reviewEntities, cfg.replacementMode);
        if (!controller.signal.aborted) setPreviewEntityMap(map);
      } catch {
        /* ignore aborted */
      }
    }, 300);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [
    step,
    reviewFile,
    reviewEntities,
    reviewTextContent,
    reviewLoading,
    cfg.replacementMode,
    previewEntityMap,
    isPreviewMode,
    setPreviewEntityMap,
  ]);
}

type ReviewImagePreviewDeps = Pick<
  ReviewDataDeps,
  | 'step'
  | 'reviewFile'
  | 'isPreviewMode'
  | 'cfg'
  | 'visibleReviewBoxes'
  | 'reviewCurrentPage'
  | 'reviewLoading'
  | 'setReviewImagePreview'
>;

export function useReviewImagePreview(deps: ReviewImagePreviewDeps): {
  reviewImagePreviewLoading: boolean;
} {
  const {
    step,
    reviewFile,
    isPreviewMode,
    cfg,
    visibleReviewBoxes,
    reviewCurrentPage,
    reviewLoading,
    setReviewImagePreview,
  } = deps;

  const [reviewImagePreviewLoading, setReviewImagePreviewLoading] = useState(false);

  // Content signature for the preview request. Step 4 polls row data every
  // 1.5s while files are unsettled, which rebuilds reviewFile/visibleReviewBoxes
  // with fresh identities; depending on objects would abort the in-flight
  // preview on every poll tick and starve it forever. Depending on this JSON
  // only re-fires (and cancels) when the actual request inputs change.
  const reviewImagePreviewFileId = reviewFile?.isImageMode ? reviewFile.file_id : null;
  const reviewImagePreviewBoxesJson = useMemo(
    () =>
      JSON.stringify(
        visibleReviewBoxes
          .filter((box) => box.selected !== false)
          .map((box) => ({
            id: box.id,
            x: box.x,
            y: box.y,
            width: box.width,
            height: box.height,
            page: normalizePage(box.page, reviewCurrentPage),
            type: box.type,
            text: box.text,
            selected: box.selected,
            source: box.source,
            confidence: box.confidence,
            evidence_source: box.evidence_source,
            source_detail: box.source_detail,
            warnings: box.warnings,
          })),
      ),
    [visibleReviewBoxes, reviewCurrentPage],
  );

  useEffect(() => {
    if (isPreviewMode) return;
    if (step !== 4 || !reviewImagePreviewFileId || reviewLoading) return;

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        setReviewImagePreviewLoading(true);
        const imageBase64 = await batchPreviewImage(
          {
            file_id: reviewImagePreviewFileId,
            page: reviewCurrentPage,
            bounding_boxes: JSON.parse(reviewImagePreviewBoxesJson),
            config: {
              replacement_mode: ReplacementMode.STRUCTURED,
              entity_types: [],
              custom_replacements: {},
              image_redaction_method: cfg.imageRedactionMethod ?? 'mosaic',
              image_redaction_strength: cfg.imageRedactionStrength ?? 75,
              image_fill_color: cfg.imageFillColor ?? '#000000',
            },
          },
          controller.signal,
        );
        if (!controller.signal.aborted) setReviewImagePreview(imageBase64);
      } catch {
        if (!controller.signal.aborted) setReviewImagePreview('');
      } finally {
        // Always release the loading flag — a gated reset can leave the
        // spinner stuck when the request is aborted mid-flight.
        setReviewImagePreviewLoading(false);
      }
    }, 250);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [
    step,
    reviewImagePreviewFileId,
    reviewImagePreviewBoxesJson,
    reviewCurrentPage,
    reviewLoading,
    cfg.imageRedactionMethod,
    cfg.imageRedactionStrength,
    cfg.imageFillColor,
    isPreviewMode,
    setReviewImagePreview,
  ]);

  return { reviewImagePreviewLoading };
}
