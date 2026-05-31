// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import { fileApi, authenticatedBlobUrl } from '@/services/api';
import { authFetch, VISION_TIMEOUT } from '@/services/api-client';
import { ReplacementMode } from '@/types';
import {
  batchGetFileRaw,
  batchPreviewImage,
  flattenBoundingBoxesFromStore,
  type BatchWizardPersistedConfig,
} from '@/services/batchPipeline';
import { isDefaultExcludedPipelineTypeId } from '@/services/defaultRedactionPreset';
import { buildFallbackPreviewEntityMap } from '@/utils/textRedactionSegments';
import { getItemReviewDraft } from '@/services/jobsApi';
import { getPreviewReviewPayload } from '../lib/batch-preview-fixtures';
import type {
  BatchRow,
  ReviewEntity,
  ReviewVisionPageQuality,
  Step,
  TextEntityType,
} from '../types';
import { fetchCachedBatchPreviewMap, normalizeReviewEntity } from './use-batch-wizard-utils';

export interface ReviewDataDeps {
  step: Step;
  reviewFile: BatchRow | null;
  activeJobId: string | null;
  itemIdByFileIdRef: React.MutableRefObject<Record<string, string>>;
  cfg: BatchWizardPersistedConfig;
  isPreviewMode: boolean;
  textTypes: TextEntityType[];
  reviewEntities: ReviewEntity[];
  reviewBoxes: EditorBox[];
  visibleReviewBoxes: EditorBox[];
  reviewCurrentPage: number;
  reviewTotalPages: number;
  reviewItemId: string | undefined;
  reviewLoading: boolean;
  reviewTextContent: string;
  previewEntityMap: Record<string, string>;
  reviewDraftInitializedRef: React.MutableRefObject<boolean>;
  reviewDraftDirtyRef: React.MutableRefObject<boolean>;
  reviewLastSavedJsonRef: React.MutableRefObject<string>;
  reviewAutosaveTimerRef: React.MutableRefObject<number | null>;
  setReviewLoading: React.Dispatch<React.SetStateAction<boolean>>;
  setPreviewEntityMap: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  setReviewImagePreview: React.Dispatch<React.SetStateAction<string>>;
  setReviewDraftError: React.Dispatch<React.SetStateAction<string | null>>;
  setReviewLoadError: React.Dispatch<React.SetStateAction<string | null>>;
  setReviewEntities: React.Dispatch<React.SetStateAction<ReviewEntity[]>>;
  setReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>>;
  setReviewCurrentPage: React.Dispatch<React.SetStateAction<number>>;
  setReviewTotalPages: React.Dispatch<React.SetStateAction<number>>;
  setReviewPages: React.Dispatch<React.SetStateAction<string[]>>;
  setReviewVisionQualityByPage: React.Dispatch<
    React.SetStateAction<Record<number, ReviewVisionPageQuality>>
  >;
  setReviewTextContent: React.Dispatch<React.SetStateAction<string>>;
  setReviewOrigImageBlobUrl: React.Dispatch<React.SetStateAction<string>>;
  setReviewTextUndoStack: React.Dispatch<React.SetStateAction<ReviewEntity[][]>>;
  setReviewTextRedoStack: React.Dispatch<React.SetStateAction<ReviewEntity[][]>>;
  setReviewImageUndoStack: React.Dispatch<React.SetStateAction<EditorBox[][]>>;
  setReviewImageRedoStack: React.Dispatch<React.SetStateAction<EditorBox[][]>>;
  buildCurrentReviewDraftPayload: () => {
    entities: Array<Record<string, unknown>>;
    bounding_boxes: Array<Record<string, unknown>>;
  };
  flushCurrentReviewDraft: () => Promise<boolean>;
  setMsg: (msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null) => void;
}

export interface ReviewDataState {
  loadReviewData: (fileId: string, isImage: boolean) => Promise<void>;
  rerunCurrentItemRecognition: () => Promise<void>;
  rerunRecognitionLoading: boolean;
  reviewImagePreviewLoading: boolean;
}

const IMAGE_BLOB_REVOKE_DELAY_MS = 30_000;

function revokeImageBlobUrlLater(url: string) {
  if (!url.startsWith('blob:')) return;
  window.setTimeout(() => URL.revokeObjectURL(url), IMAGE_BLOB_REVOKE_DELAY_MS);
}

interface PreviewImageResponse {
  image_base64?: string;
}

function toDataImageUrl(imageBase64: string | undefined): string {
  if (!imageBase64) return '';
  return imageBase64.startsWith('data:') ? imageBase64 : `data:image/png;base64,${imageBase64}`;
}

function normalizePage(page: unknown, fallback = 1): number {
  const n = Number(page);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : fallback;
}

function normalizeVisionQualityByPage(raw: unknown): Record<number, ReviewVisionPageQuality> {
  if (!raw || typeof raw !== 'object') return {};
  const normalized: Record<number, ReviewVisionPageQuality> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!value || typeof value !== 'object') continue;
    const page = normalizePage(key, 0);
    if (page <= 0) continue;
    const record = value as Record<string, unknown>;
    const warnings = Array.isArray(record.warnings)
      ? record.warnings.filter((warning): warning is string => typeof warning === 'string')
      : [];
    const pipelineStatus =
      record.pipeline_status && typeof record.pipeline_status === 'object'
        ? (record.pipeline_status as Record<string, Record<string, unknown>>)
        : {};
    normalized[page] = {
      warnings,
      pipeline_status: Object.fromEntries(
        Object.entries(pipelineStatus).map(([name, status]) => [
          name,
          {
            ran: Boolean(status.ran),
            skipped: Boolean(status.skipped),
            failed: Boolean(status.failed),
            region_count: typeof status.region_count === 'number' ? status.region_count : undefined,
            error: typeof status.error === 'string' ? status.error : null,
          },
        ]),
      ),
    };
  }
  return normalized;
}

function normalizeReviewBox(
  raw: Record<string, unknown>,
  index: number,
  pageFallback = 1,
): EditorBox {
  return {
    id: String(raw.id ?? `bbox_${index}`),
    x: Number(raw.x),
    y: Number(raw.y),
    width: Number(raw.width),
    height: Number(raw.height),
    page: normalizePage(raw.page, pageFallback),
    type: String(raw.type ?? 'CUSTOM'),
    text: raw.text ? String(raw.text) : undefined,
    selected: raw.selected !== false,
    confidence: typeof raw.confidence === 'number' ? raw.confidence : undefined,
    source: (raw.source as EditorBox['source']) || undefined,
    evidence_source:
      typeof raw.evidence_source === 'string'
        ? (raw.evidence_source as EditorBox['evidence_source'])
        : undefined,
    source_detail: raw.source_detail ? String(raw.source_detail) : undefined,
    warnings: Array.isArray(raw.warnings)
      ? raw.warnings.filter((warning): warning is string => typeof warning === 'string')
      : undefined,
  };
}

export function sanitizeReviewBoxSelection(
  box: EditorBox,
  cfg: Pick<BatchWizardPersistedConfig, 'hasImageTypes'>,
): EditorBox {
  const type = String(box.type ?? '');
  if (
    box.source === 'has_image' &&
    isDefaultExcludedPipelineTypeId('has_image', type) &&
    !cfg.hasImageTypes.includes(type)
  ) {
    return { ...box, selected: false };
  }
  return box;
}

function boxesToDraftPayload(boxes: EditorBox[]): Array<Record<string, unknown>> {
  return boxes.map((box) => ({
    id: box.id,
    x: box.x,
    y: box.y,
    width: box.width,
    height: box.height,
    page: normalizePage(box.page, 1),
    type: box.type,
    text: box.text,
    selected: box.selected,
    source: box.source,
    confidence: box.confidence,
    evidence_source: box.evidence_source,
    source_detail: box.source_detail,
    warnings: box.warnings,
  }));
}

function normalizeEntityMap(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const entries = Object.entries(raw as Record<string, unknown>)
    .filter(([key, value]) => key && typeof value === 'string' && value)
    .map(([key, value]) => [key, value as string]);
  return Object.fromEntries(entries);
}

export function useBatchReviewData(deps: ReviewDataDeps): ReviewDataState {
  const {
    step,
    reviewFile,
    activeJobId,
    itemIdByFileIdRef,
    cfg,
    isPreviewMode,
    textTypes: _textTypes,
    reviewEntities,
    reviewBoxes: _reviewBoxes,
    visibleReviewBoxes,
    reviewCurrentPage,
    reviewTotalPages,
    reviewItemId,
    reviewLoading,
    reviewTextContent,
    previewEntityMap,
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
  void _textTypes;
  void _reviewBoxes;

  const reviewLoadSeqRef = useRef(0);
  const autoLoadedReviewKeyRef = useRef('');
  const rerunAbortRef = useRef<AbortController | null>(null);
  const loadDataAbortRef = useRef<AbortController | null>(null);
  // Per-page cached scanned-PDF preview image to eliminate blank-flash on page
  // switch. Key = `${file_id}:${page}`. Cleared when the active file changes.
  const pageImageCacheRef = useRef<Map<string, string>>(new Map());
  const [rerunRecognitionLoading, setRerunRecognitionLoading] = useState(false);
  const [reviewImagePreviewLoading, setReviewImagePreviewLoading] = useState(false);
  const reviewFileId = reviewFile?.file_id ?? '';
  const reviewFileIsImageMode = reviewFile?.isImageMode === true;

  useEffect(() => {
    pageImageCacheRef.current.clear();
  }, [reviewFile?.file_id]);

  useEffect(
    () => () => {
      rerunAbortRef.current?.abort();
      loadDataAbortRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    let currentBlobUrl = '';

    if (!reviewFile || !reviewFile.isImageMode) {
      setReviewOrigImageBlobUrl('');
      return;
    }

    const rawFileType = String(reviewFile.file_type ?? '').toLowerCase();
    const isScannedPdf = rawFileType === 'pdf_scanned';
    const rawDownloadUrl = fileApi.getDownloadUrl(reviewFile.file_id, false);

    const loadFromRawDownload = () => {
      authenticatedBlobUrl(rawDownloadUrl)
        .then((blobUrl) => {
          if (!cancelled) {
            currentBlobUrl = blobUrl;
            setReviewOrigImageBlobUrl(blobUrl);
          } else if (blobUrl.startsWith('blob:')) {
            URL.revokeObjectURL(blobUrl);
          }
        })
        .catch(() => {
          if (!cancelled) setReviewOrigImageBlobUrl(rawDownloadUrl);
        });
    };

    if (isScannedPdf) {
      const cacheKey = `${reviewFile.file_id}:${reviewCurrentPage}`;
      const cached = pageImageCacheRef.current.get(cacheKey);
      const prefetch = (page: number) => {
        if (page < 1 || page > reviewTotalPages) return;
        const key = `${reviewFile.file_id}:${page}`;
        if (pageImageCacheRef.current.has(key)) return;
        authFetch(`/api/v1/redaction/${reviewFile.file_id}/preview-image?page=${page}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            bounding_boxes: [],
            config: {
              replacement_mode: 'structured',
              entity_types: [],
              custom_replacements: {},
            },
          }),
        })
          .then(async (res) => {
            if (!res.ok) return;
            const data = (await res.json()) as PreviewImageResponse;
            const url = toDataImageUrl(data.image_base64);
            if (url) pageImageCacheRef.current.set(key, url);
          })
          .catch(() => {
            /* silent */
          });
      };
      const scheduleNeighbors = () => {
        const defer =
          (window as unknown as { requestIdleCallback?: (cb: () => void) => number })
            .requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 300));
        defer(() => prefetch(reviewCurrentPage - 1));
        defer(() => prefetch(reviewCurrentPage + 1));
      };

      if (cached) {
        setReviewOrigImageBlobUrl(cached);
        scheduleNeighbors();
      } else {
        authFetch(
          `/api/v1/redaction/${reviewFile.file_id}/preview-image?page=${reviewCurrentPage}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              bounding_boxes: [],
              config: {
                replacement_mode: 'structured',
                entity_types: [],
                custom_replacements: {},
              },
            }),
          },
        )
          .then(async (res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = (await res.json()) as PreviewImageResponse;
            const imageUrl = toDataImageUrl(data.image_base64);
            if (!imageUrl) throw new Error('Missing image_base64');
            if (!cancelled) {
              pageImageCacheRef.current.set(cacheKey, imageUrl);
              setReviewOrigImageBlobUrl(imageUrl);
              scheduleNeighbors();
            }
          })
          .catch(() => {
            // Scanned PDF download URL can't render in <img>; keep previous image
          });
      }
    } else {
      loadFromRawDownload();
    }

    return () => {
      cancelled = true;
      revokeImageBlobUrlLater(currentBlobUrl);
    };
  }, [reviewFile, reviewCurrentPage, reviewTotalPages, setReviewOrigImageBlobUrl]);

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
            .map((box) => sanitizeReviewBoxSelection(box, { hasImageTypes: cfg.hasImageTypes }));
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
      cfg.hasImageTypes,
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

  const rerunCurrentItemRecognition = useCallback(async () => {
    if (!reviewFile) return;
    const isImage = reviewFile.isImageMode === true;
    const hasManualDraft =
      reviewDraftDirtyRef.current ||
      reviewEntities.length > 0 ||
      _reviewBoxes.length > 0 ||
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
                    selected_has_image_types: cfg.hasImageTypes,
                    selected_vlm_types: cfg.vlmTypes ?? [],
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
    _reviewBoxes.length,
    visibleReviewBoxes.length,
    reviewTotalPages,
    cfg.selectedEntityTypeIds,
    cfg.ocrHasTypes,
    cfg.hasImageTypes,
    cfg.vlmTypes,
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

  useEffect(() => {
    if (isPreviewMode) return;
    if (step !== 4 || !reviewFile || reviewLoading || !reviewFile.isImageMode) return;

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        setReviewImagePreviewLoading(true);
        const imageBase64 = await batchPreviewImage({
          file_id: reviewFile.file_id,
          page: reviewCurrentPage,
          bounding_boxes: visibleReviewBoxes
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
          config: {
            replacement_mode: ReplacementMode.STRUCTURED,
            entity_types: [],
            custom_replacements: {},
            image_redaction_method: cfg.imageRedactionMethod ?? 'mosaic',
            image_redaction_strength: cfg.imageRedactionStrength ?? 75,
            image_fill_color: cfg.imageFillColor ?? '#000000',
          },
        });
        if (!controller.signal.aborted) setReviewImagePreview(imageBase64);
      } catch {
        if (!controller.signal.aborted) setReviewImagePreview('');
      } finally {
        if (!controller.signal.aborted) setReviewImagePreviewLoading(false);
      }
    }, 250);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [
    step,
    reviewFile,
    visibleReviewBoxes,
    reviewCurrentPage,
    reviewLoading,
    cfg.imageRedactionMethod,
    cfg.imageRedactionStrength,
    cfg.imageFillColor,
    isPreviewMode,
    setReviewImagePreview,
  ]);

  return {
    loadReviewData,
    rerunCurrentItemRecognition,
    rerunRecognitionLoading,
    reviewImagePreviewLoading,
  };
}
