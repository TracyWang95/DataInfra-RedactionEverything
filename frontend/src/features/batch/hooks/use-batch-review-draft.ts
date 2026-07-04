// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { localizeErrorMessage } from '@/utils/localizeError';
import {
  batchGetFileRaw,
  flattenBoundingBoxesFromStore,
} from '@/services/batchPipeline';
import { buildFallbackPreviewEntityMap } from '@/utils/textRedactionSegments';
import { getItemReviewDraft } from '@/services/jobsApi';
import { getPreviewReviewPayload } from '../lib/batch-preview-fixtures';
import type { ReviewEntity } from '../types';
import { fetchCachedBatchPreviewMap, normalizeReviewEntity } from './use-batch-wizard-utils';
import {
  boxesToDraftPayload,
  normalizeEntityMap,
  normalizePage,
  normalizeReviewBox,
  normalizeVisionQualityByPage,
  sanitizeReviewBoxSelection,
} from './use-batch-review-normalize';
import type { ReviewDataDeps } from './use-batch-review-data';

type ReviewDraftDeps = Pick<
  ReviewDataDeps,
  | 'step'
  | 'reviewFile'
  | 'activeJobId'
  | 'itemIdByFileIdRef'
  | 'cfg'
  | 'isPreviewMode'
  | 'reviewItemId'
  | 'reviewDraftInitializedRef'
  | 'reviewDraftDirtyRef'
  | 'reviewLastSavedJsonRef'
  | 'reviewAutosaveTimerRef'
  | 'setReviewLoading'
  | 'setPreviewEntityMap'
  | 'setReviewImagePreview'
  | 'setReviewDraftError'
  | 'setReviewLoadError'
  | 'setReviewEntities'
  | 'setReviewBoxes'
  | 'setReviewCurrentPage'
  | 'setReviewTotalPages'
  | 'setReviewPages'
  | 'setReviewVisionQualityByPage'
  | 'setReviewTextContent'
  | 'setReviewOrigImageBlobUrl'
  | 'setReviewTextUndoStack'
  | 'setReviewTextRedoStack'
  | 'setReviewImageUndoStack'
  | 'setReviewImageRedoStack'
  | 'buildCurrentReviewDraftPayload'
  | 'flushCurrentReviewDraft'
  | 'setMsg'
>;

export function useReviewDraft(deps: ReviewDraftDeps): {
  loadReviewData: (fileId: string, isImage: boolean) => Promise<void>;
} {
  const {
    step,
    reviewFile,
    activeJobId,
    itemIdByFileIdRef,
    cfg,
    isPreviewMode,
    reviewItemId,
    reviewDraftInitializedRef,
    reviewDraftDirtyRef,
    reviewLastSavedJsonRef,
    reviewAutosaveTimerRef,
    setReviewLoading,
    setPreviewEntityMap,
    setReviewImagePreview,
    setReviewDraftError,
    setReviewLoadError,
    setReviewEntities,
    setReviewBoxes,
    setReviewCurrentPage,
    setReviewTotalPages,
    setReviewPages,
    setReviewVisionQualityByPage,
    setReviewTextContent,
    setReviewOrigImageBlobUrl,
    setReviewTextUndoStack,
    setReviewTextRedoStack,
    setReviewImageUndoStack,
    setReviewImageRedoStack,
    buildCurrentReviewDraftPayload,
    flushCurrentReviewDraft,
    setMsg,
  } = deps;

  const reviewLoadSeqRef = useRef(0);
  const autoLoadedReviewKeyRef = useRef('');
  const loadDataAbortRef = useRef<AbortController | null>(null);
  const reviewFileId = reviewFile?.file_id ?? '';
  const reviewFileIsImageMode = reviewFile?.isImageMode === true;

  useEffect(
    () => () => {
      loadDataAbortRef.current?.abort();
    },
    [],
  );

  useLayoutEffect(() => {
    if (step !== 4 || !reviewFileId) return;
    setReviewLoading(true);
  }, [step, reviewFileId, setReviewLoading]);

  const loadReviewData = useCallback(
    async (fileId: string, isImage: boolean) => {
      loadDataAbortRef.current?.abort();
      const controller = new AbortController();
      loadDataAbortRef.current = controller;

      const loadSeq = reviewLoadSeqRef.current + 1;
      reviewLoadSeqRef.current = loadSeq;

      setReviewLoading(true);
      setReviewLoadError(null);
      setPreviewEntityMap({});
      setReviewImagePreview('');
      setReviewDraftError(null);
      setReviewEntities([]);
      setReviewBoxes([]);
      setReviewTextContent('');
      setReviewCurrentPage(1);
      setReviewTotalPages(1);
      setReviewPages([]);
      setReviewVisionQualityByPage({});
      reviewDraftInitializedRef.current = false;
      reviewDraftDirtyRef.current = false;
      if (reviewAutosaveTimerRef.current !== null) {
        window.clearTimeout(reviewAutosaveTimerRef.current);
        reviewAutosaveTimerRef.current = null;
      }

      if (isPreviewMode) {
        const previewPayload = getPreviewReviewPayload(fileId);
        if (isImage) {
          const boxes = previewPayload.boxes.map((box) => ({
            ...box,
            page: normalizePage(box.page, 1),
          }));
          const maxPage = boxes.reduce((max, box) => Math.max(max, normalizePage(box.page, 1)), 1);
          setReviewTextContent('');
          setReviewEntities([]);
          setReviewBoxes(boxes);
          setReviewCurrentPage(1);
          setReviewTotalPages(maxPage);
          setReviewOrigImageBlobUrl(previewPayload.imageSrc);
          setReviewImagePreview(previewPayload.previewSrc);
          setReviewImageUndoStack([]);
          setReviewImageRedoStack([]);
          reviewLastSavedJsonRef.current = JSON.stringify({
            entities: [],
            bounding_boxes: boxesToDraftPayload(boxes),
          });
        } else {
          setReviewBoxes([]);
          setReviewCurrentPage(1);
          setReviewTotalPages(1);
          setReviewEntities(previewPayload.entities.map((entity) => ({ ...entity })));
          setReviewTextContent(previewPayload.content);
          setReviewTextUndoStack([]);
          setReviewTextRedoStack([]);
          setPreviewEntityMap(
            buildFallbackPreviewEntityMap(previewPayload.entities, cfg.replacementMode),
          );
          const map = await fetchCachedBatchPreviewMap(
            previewPayload.entities,
            cfg.replacementMode,
          );
          if (loadSeq !== reviewLoadSeqRef.current || controller.signal.aborted) return;
          setPreviewEntityMap(map);
          reviewLastSavedJsonRef.current = JSON.stringify({
            entities: previewPayload.entities,
            bounding_boxes: [],
          });
        }
        reviewDraftInitializedRef.current = true;
        setReviewLoadError(null);
        setReviewLoading(false);
        return;
      }

      try {
        const info = await batchGetFileRaw(fileId);
        if (loadSeq !== reviewLoadSeqRef.current || controller.signal.aborted) return;

        const linkedItemId = itemIdByFileIdRef.current[fileId];
        let draft: {
          exists?: boolean;
          entities?: Array<Record<string, unknown>>;
          bounding_boxes?: Array<Record<string, unknown>>;
        } | null = null;
        const isReadOnlyOutputRow =
          reviewFile?.reviewConfirmed === true ||
          reviewFile?.has_output === true ||
          reviewFile?.analyzeStatus === 'completed';
        const shouldLoadServerDraft =
          !isReadOnlyOutputRow || Boolean(reviewFile?.hasReviewDraft);
        if (activeJobId && linkedItemId && shouldLoadServerDraft) {
          try {
            const loadedDraft = await getItemReviewDraft(activeJobId, linkedItemId);
            if (loadSeq !== reviewLoadSeqRef.current || controller.signal.aborted) return;
            if (loadedDraft.exists) draft = loadedDraft;
          } catch {
            /* ignore */
          }
        }

        if (isImage) {
          const raw =
            draft?.bounding_boxes && draft.bounding_boxes.length > 0
              ? draft.bounding_boxes
              : flattenBoundingBoxesFromStore(info.bounding_boxes);
          const pageCountFromInfo = normalizePage(info.page_count, 1);
          const boxes = raw
            .map((box, index) => normalizeReviewBox(box, index, 1))
            .map((box) => sanitizeReviewBoxSelection(box, { visualFeatureTypes: cfg.visualFeatureTypes }));
          const maxBoxPage = boxes.reduce(
            (max, box) => Math.max(max, normalizePage(box.page, 1)),
            1,
          );
          const totalPages = Math.max(1, pageCountFromInfo, maxBoxPage);

          setReviewTextContent('');
          setReviewEntities([]);
          setReviewBoxes(boxes);
          setReviewCurrentPage(1);
          setReviewTotalPages(totalPages);
          setReviewVisionQualityByPage(normalizeVisionQualityByPage(info.vision_quality));
          setReviewImageUndoStack([]);
          setReviewImageRedoStack([]);
          reviewLastSavedJsonRef.current = JSON.stringify({
            entities: [],
            bounding_boxes: boxesToDraftPayload(boxes),
          });
        } else {
          const entities =
            (draft?.entities as ReviewEntity[] | undefined) ??
            (info.entities as ReviewEntity[]) ??
            [];
          const mapped = entities.map((entity, index) =>
            normalizeReviewEntity({
              id: entity.id || `ent_${index}`,
              text: entity.text,
              type: typeof entity.type === 'string' ? entity.type : String(entity.type ?? 'CUSTOM'),
              start: typeof entity.start === 'number' ? entity.start : Number(entity.start),
              end: typeof entity.end === 'number' ? entity.end : Number(entity.end),
              selected: entity.selected !== false,
              page: entity.page ?? 1,
              confidence: entity.confidence,
              source: entity.source,
              coref_id: entity.coref_id,
              replacement: entity.replacement,
            }),
          );
          setReviewBoxes([]);
          const contentStr = typeof info.content === 'string' ? info.content : '';
          const rawPages = Array.isArray(info.pages) ? (info.pages as unknown[]) : [];
          const pagesArr = rawPages.filter((page): page is string => typeof page === 'string');
          const pageCountFromInfo = normalizePage(info.page_count, 1);
          const textTotalPages = Math.max(1, pageCountFromInfo, pagesArr.length);
          setReviewCurrentPage(1);
          setReviewTotalPages(textTotalPages);
          setReviewPages(pagesArr);
          setReviewVisionQualityByPage({});
          setReviewEntities(mapped);
          setReviewTextContent(contentStr);
          setReviewTextUndoStack([]);
          setReviewTextRedoStack([]);
          const storedMap = normalizeEntityMap(info.entity_map);
          const fallbackMap = buildFallbackPreviewEntityMap(mapped, cfg.replacementMode);
          if (Object.keys(storedMap).length > 0) {
            setPreviewEntityMap(storedMap);
          } else {
            setPreviewEntityMap(fallbackMap);
          }
          const map =
            isReadOnlyOutputRow && Object.keys(storedMap).length > 0
              ? storedMap
              : await fetchCachedBatchPreviewMap(mapped, cfg.replacementMode);
          if (loadSeq !== reviewLoadSeqRef.current || controller.signal.aborted) return;
          setPreviewEntityMap(Object.keys(map).length > 0 ? map : fallbackMap);
          reviewLastSavedJsonRef.current = JSON.stringify({
            entities: mapped.map((entity) => ({
              id: entity.id,
              text: entity.text,
              type: entity.type,
              start: entity.start,
              end: entity.end,
              page: entity.page ?? 1,
              confidence: entity.confidence ?? 1,
              selected: entity.selected,
              source: entity.source,
              coref_id: entity.coref_id,
              replacement: entity.replacement,
            })),
            bounding_boxes: [],
          });
        }

        reviewDraftInitializedRef.current = true;
        setReviewLoadError(null);
      } catch (error) {
        if (loadSeq !== reviewLoadSeqRef.current || controller.signal.aborted) return;
        const message = localizeErrorMessage(error, 'batchWizard.step4.loadFailed');
        reviewDraftInitializedRef.current = false;
        reviewDraftDirtyRef.current = false;
        setReviewLoadError(message);
        setReviewDraftError(message);
        setMsg({ text: message, tone: 'err' });
      } finally {
        if (loadSeq === reviewLoadSeqRef.current && !controller.signal.aborted) {
          setReviewLoading(false);
        }
      }
    },
    [
      activeJobId,
      cfg.visualFeatureTypes,
      cfg.replacementMode,
      isPreviewMode,
      itemIdByFileIdRef,
      reviewFile?.analyzeStatus,
      reviewFile?.hasReviewDraft,
      reviewFile?.has_output,
      reviewFile?.reviewConfirmed,
      reviewAutosaveTimerRef,
      reviewDraftDirtyRef,
      reviewDraftInitializedRef,
      reviewLastSavedJsonRef,
      setPreviewEntityMap,
      setReviewBoxes,
      setReviewCurrentPage,
      setReviewDraftError,
      setReviewEntities,
      setReviewImagePreview,
      setReviewImageRedoStack,
      setReviewImageUndoStack,
      setMsg,
      setReviewLoadError,
      setReviewLoading,
      setReviewOrigImageBlobUrl,
      setReviewPages,
      setReviewTextContent,
      setReviewTextRedoStack,
      setReviewTextUndoStack,
      setReviewTotalPages,
      setReviewVisionQualityByPage,
    ],
  );

  useEffect(() => {
    if (step !== 4 || !reviewFileId) {
      autoLoadedReviewKeyRef.current = '';
      return;
    }
    const key = `${reviewFileId}:${reviewItemId ?? 'pending-item'}:${
      reviewFileIsImageMode ? 'image' : 'text'
    }`;
    if (autoLoadedReviewKeyRef.current === key) return;
    autoLoadedReviewKeyRef.current = key;
    void loadReviewData(reviewFileId, reviewFileIsImageMode);
  }, [step, reviewFileId, reviewFileIsImageMode, reviewItemId, loadReviewData]);

  useEffect(() => {
    if (isPreviewMode) return;
    if (step !== 4 || !reviewFile || !reviewDraftInitializedRef.current) return;
    if (!activeJobId || !reviewItemId) return;

    const payload = buildCurrentReviewDraftPayload();
    const json = JSON.stringify(payload);
    if (json === reviewLastSavedJsonRef.current) return;
    reviewDraftDirtyRef.current = true;

    if (reviewAutosaveTimerRef.current !== null) {
      window.clearTimeout(reviewAutosaveTimerRef.current);
    }
    reviewAutosaveTimerRef.current = window.setTimeout(() => {
      void flushCurrentReviewDraft();
    }, 900);

    return () => {
      if (reviewAutosaveTimerRef.current !== null) {
        window.clearTimeout(reviewAutosaveTimerRef.current);
        reviewAutosaveTimerRef.current = null;
      }
    };
  }, [
    step,
    reviewFile,
    reviewItemId,
    activeJobId,
    buildCurrentReviewDraftPayload,
    flushCurrentReviewDraft,
    isPreviewMode,
    reviewAutosaveTimerRef,
    reviewDraftDirtyRef,
    reviewDraftInitializedRef,
    reviewLastSavedJsonRef,
  ]);

  return { loadReviewData };
}
