// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { t } from '@/i18n';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import { localizeErrorMessage } from '@/utils/localizeError';
import type { BatchWizardPersistedConfig } from '@/services/batchPipeline';
import { putItemReviewDraft } from '@/services/jobsApi';
import {
  buildTextSegments,
  type TextSegment,
} from '@/utils/textRedactionSegments';
import type {
  BatchRow,
  ReviewEntity,
  ReviewPageSummary,
  ReviewVisionPageQuality,
  Step,
  TextEntityType,
} from '../types';
import { RECOGNITION_DONE_STATUSES } from '../types';
import { buildReviewPageSummaries } from '../lib/review-page-summary';
import { useBatchReviewData } from './use-batch-review-data';

export interface BatchReviewState {
  reviewIndex: number;
  setReviewIndex: React.Dispatch<React.SetStateAction<number>>;
  reviewEntities: ReviewEntity[];
  reviewBoxes: EditorBox[];
  visibleReviewBoxes: EditorBox[];
  visibleReviewEntities: ReviewEntity[];
  reviewPageContent: string;
  reviewCurrentPage: number;
  reviewTotalPages: number;
  reviewAllPagesVisited: boolean;
  reviewRequiredPagesVisited: boolean;
  visitedReviewPagesCount: number;
  reviewPageSummaries: ReviewPageSummary[];
  reviewHitPageCount: number;
  reviewUnvisitedHitPageCount: number;
  reviewRequiredPageCount: number;
  reviewUnvisitedRequiredPageCount: number;
  currentReviewVisionQuality: ReviewVisionPageQuality | null;
  reviewPages: string[];
  setReviewPages: React.Dispatch<React.SetStateAction<string[]>>;
  reviewLoading: boolean;
  reviewLoadError: string | null;
  reviewExecuteLoading: boolean;
  setReviewExecuteLoading: React.Dispatch<React.SetStateAction<boolean>>;
  reviewDraftSaving: boolean;
  reviewDraftError: string | null;
  reviewImagePreviewLoading: boolean;
  reviewOrigImageBlobUrl: string;
  reviewTextUndoStack: ReviewEntity[][];
  reviewTextRedoStack: ReviewEntity[][];
  reviewImageUndoStack: EditorBox[][];
  reviewImageRedoStack: EditorBox[][];
  reviewTextContent: string;
  reviewTextContentRef: React.RefObject<HTMLDivElement | null>;
  reviewTextScrollRef: React.RefObject<HTMLDivElement | null>;
  reviewDraftDirtyRef: React.MutableRefObject<boolean>;
  reviewLastSavedJsonRef: React.MutableRefObject<string>;

  // Derived
  reviewFile: BatchRow | null;
  doneRows: BatchRow[];
  reviewFileReadOnly: boolean;
  reviewItemId: string | undefined;
  selectedReviewEntityCount: number;
  selectedReviewBoxCount: number;
  totalReviewBoxCount: number;
  reviewImagePreviewSrc: string;
  displayPreviewMap: Record<string, string>;
  textPreviewSegments: TextSegment[];
  reviewedOutputCount: number;
  allReviewConfirmed: boolean;
  pendingReviewCount: number;

  // Actions
  applyReviewEntities: (
    updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[]),
  ) => void;
  toggleReviewEntitySelected: (entityId: string) => void;
  setReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>>;
  setVisibleReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>>;
  setReviewCurrentPage: (page: number) => void;
  handleReviewBoxesCommit: (prevBoxes: EditorBox[], nextBoxes: EditorBox[]) => void;
  toggleReviewBoxSelected: (boxId: string) => void;
  undoReviewText: () => void;
  redoReviewText: () => void;
  undoReviewImage: () => void;
  redoReviewImage: () => void;
  buildCurrentReviewDraftPayload: () => {
    entities: Array<Record<string, unknown>>;
    bounding_boxes: Array<Record<string, unknown>>;
  };
  flushCurrentReviewDraft: () => Promise<boolean>;
  navigateReviewIndex: (nextIndex: number) => Promise<void>;
  loadReviewData: (fileId: string, isImage: boolean) => Promise<void>;
  rerunCurrentItemRecognition: () => Promise<void>;
  rerunRecognitionLoading: boolean;
}

function cloneBoxes(boxes: EditorBox[]): EditorBox[] {
  return boxes.map((box) => ({ ...box }));
}

function normalizeBoxPage(box: EditorBox, fallbackPage: number): EditorBox {
  return { ...box, page: Number(box.page || fallbackPage) };
}

export function useBatchReview(
  step: Step,
  rows: BatchRow[],
  activeJobId: string | null,
  itemIdByFileIdRef: React.MutableRefObject<Record<string, string>>,
  cfg: BatchWizardPersistedConfig,
  isPreviewMode: boolean,
  textTypes: TextEntityType[],
  setMsg: (msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null) => void,
): BatchReviewState {
  const [reviewIndex, setReviewIndex] = useState(0);
  const [reviewEntities, setReviewEntities] = useState<ReviewEntity[]>([]);
  const [reviewBoxes, setReviewBoxes] = useState<EditorBox[]>([]);
  const [reviewCurrentPage, setReviewCurrentPageState] = useState(1);
  const [reviewTotalPages, setReviewTotalPages] = useState(1);
  // Tracks which pages the user has actually viewed in this file. We gate the
  // "confirm redaction" button behind visiting every page — users were
  // confirming a multi-page PDF after only seeing page 1.
  const [visitedReviewPages, setVisitedReviewPages] = useState<Set<number>>(() => new Set([1]));
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewLoadError, setReviewLoadError] = useState<string | null>(null);
  const [reviewExecuteLoading, setReviewExecuteLoading] = useState(false);
  const [reviewDraftSaving, setReviewDraftSaving] = useState(false);
  const [reviewDraftError, setReviewDraftError] = useState<string | null>(null);
  const [reviewImagePreview, setReviewImagePreview] = useState('');
  const [reviewOrigImageBlobUrl, setReviewOrigImageBlobUrl] = useState('');
  const [reviewTextUndoStack, setReviewTextUndoStack] = useState<ReviewEntity[][]>([]);
  const [reviewTextRedoStack, setReviewTextRedoStack] = useState<ReviewEntity[][]>([]);
  const [reviewImageUndoStack, setReviewImageUndoStack] = useState<EditorBox[][]>([]);
  const [reviewImageRedoStack, setReviewImageRedoStack] = useState<EditorBox[][]>([]);
  const [reviewTextContent, setReviewTextContent] = useState('');
  const [reviewPages, setReviewPages] = useState<string[]>([]);
  const [reviewVisionQualityByPage, setReviewVisionQualityByPage] = useState<
    Record<number, ReviewVisionPageQuality>
  >({});
  const [previewEntityMap, setPreviewEntityMap] = useState<Record<string, string>>({});
  const reviewTextContentRef = useRef<HTMLDivElement | null>(null);
  const reviewTextScrollRef = useRef<HTMLDivElement | null>(null);
  const reviewAutosaveTimerRef = useRef<number | null>(null);
  const reviewLastSavedJsonRef = useRef('');
  const reviewDraftInitializedRef = useRef(false);
  const reviewDraftDirtyRef = useRef(false);

  const doneRows = useMemo(
    () => rows.filter((row) => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus)),
    [rows],
  );
  const reviewFile = doneRows[reviewIndex] ?? null;
  const reviewedOutputCount = useMemo(
    () => doneRows.filter((row) => row.reviewConfirmed === true).length,
    [doneRows],
  );
  const pendingReviewCount = Math.max(0, doneRows.length - reviewedOutputCount);
  const allReviewConfirmed = doneRows.length > 0 && pendingReviewCount === 0;
  const reviewItemId = reviewFile ? itemIdByFileIdRef.current[reviewFile.file_id] : undefined;
  const reviewFileReadOnly =
    reviewFile?.analyzeStatus === 'redacting' ||
    reviewFile?.reviewConfirmed === true ||
    (reviewFile?.analyzeStatus === 'completed' && reviewFile?.has_output === true);

  useEffect(() => {
    setReviewCurrentPageState((prev) => Math.min(Math.max(1, prev), Math.max(1, reviewTotalPages)));
  }, [reviewTotalPages]);

  // Reset the visited set whenever the active file changes so the gate applies
  // fresh to the new document.
  useEffect(() => {
    setVisitedReviewPages(new Set([1]));
  }, [reviewFile?.file_id]);

  const setReviewCurrentPage = useCallback(
    (page: number) => {
      setReviewCurrentPageState((prev) => {
        const next = Number.isFinite(page) ? Math.trunc(page) : prev;
        const clamped = Math.min(Math.max(1, next), Math.max(1, reviewTotalPages));
        setVisitedReviewPages((visited) => {
          if (visited.has(clamped)) return visited;
          const updated = new Set(visited);
          updated.add(clamped);
          return updated;
        });
        return clamped;
      });
    },
    [reviewTotalPages],
  );

  const reviewAllPagesVisited =
    reviewTotalPages <= 1 || visitedReviewPages.size >= reviewTotalPages;

  const reviewPageSummaries = useMemo<ReviewPageSummary[]>(() => {
    return buildReviewPageSummaries({
      totalPages: reviewTotalPages,
      currentPage: reviewCurrentPage,
      visitedPages: visitedReviewPages,
      isImageMode: reviewFile?.isImageMode === true,
      entities: reviewEntities,
      boxes: reviewBoxes,
    });
  }, [
    reviewBoxes,
    reviewCurrentPage,
    reviewEntities,
    reviewFile?.isImageMode,
    reviewTotalPages,
    visitedReviewPages,
  ]);
  const reviewHitPageCount = useMemo(
    () => reviewPageSummaries.filter((page) => page.hitCount > 0).length,
    [reviewPageSummaries],
  );
  const reviewUnvisitedHitPageCount = useMemo(
    () => reviewPageSummaries.filter((page) => page.hitCount > 0 && !page.visited).length,
    [reviewPageSummaries],
  );
  const reviewRequiredPageCount = useMemo(
    () => reviewPageSummaries.filter((page) => page.hitCount > 0 || page.issueCount > 0).length,
    [reviewPageSummaries],
  );
  const reviewUnvisitedRequiredPageCount = useMemo(
    () =>
      reviewPageSummaries.filter(
        (page) => (page.hitCount > 0 || page.issueCount > 0) && !page.visited,
      ).length,
    [reviewPageSummaries],
  );
  const reviewRequiredPagesVisited =
    reviewRequiredPageCount === 0 || reviewUnvisitedRequiredPageCount === 0;

  const visibleReviewBoxes = useMemo(
    () => reviewBoxes.filter((box) => Number(box.page || 1) === reviewCurrentPage),
    [reviewBoxes, reviewCurrentPage],
  );
  const currentReviewVisionQuality = reviewVisionQualityByPage[reviewCurrentPage] ?? null;

  const isTextPaginated = !!reviewFile && reviewFile.isImageMode !== true && reviewTotalPages > 1;
  const pageStartOffset = useMemo(() => {
    if (!isTextPaginated || reviewPages.length !== reviewTotalPages) return 0;
    return reviewPages
      .slice(0, reviewCurrentPage - 1)
      .reduce((sum, page) => sum + (page?.length || 0) + 2, 0);
  }, [isTextPaginated, reviewPages, reviewTotalPages, reviewCurrentPage]);
  const reviewPageContent = useMemo(() => {
    if (isTextPaginated && reviewPages.length === reviewTotalPages) {
      return reviewPages[reviewCurrentPage - 1] ?? '';
    }
    return reviewTextContent;
  }, [isTextPaginated, reviewPages, reviewTotalPages, reviewCurrentPage, reviewTextContent]);
  const visibleReviewEntities = useMemo(() => {
    if (!isTextPaginated) return reviewEntities;
    return reviewEntities
      .filter((entity) => Number(entity.page || 1) === reviewCurrentPage)
      .map((entity) => ({
        ...entity,
        start: entity.start - pageStartOffset,
        end: entity.end - pageStartOffset,
      }));
  }, [isTextPaginated, reviewEntities, reviewCurrentPage, pageStartOffset]);
  const pageFilteredReviewEntities = useMemo(() => {
    if (!isTextPaginated) return reviewEntities;
    return reviewEntities.filter((entity) => Number(entity.page || 1) === reviewCurrentPage);
  }, [isTextPaginated, reviewEntities, reviewCurrentPage]);

  const mergeVisibleReviewBoxes = useCallback(
    (allBoxes: EditorBox[], nextVisible: EditorBox[]) => {
      const currentPageIds = new Set(
        allBoxes.filter((box) => Number(box.page || 1) === reviewCurrentPage).map((box) => box.id),
      );
      const normalizedNext = nextVisible.map((box) => normalizeBoxPage(box, reviewCurrentPage));
      const otherPages = allBoxes.filter((box) => !currentPageIds.has(box.id));
      return [...otherPages, ...normalizedNext];
    },
    [reviewCurrentPage],
  );

  const pushReviewTextHistory = useCallback((prev: ReviewEntity[]) => {
    setReviewTextUndoStack((stack) => [...stack, prev.map((entity) => ({ ...entity }))]);
    setReviewTextRedoStack([]);
  }, []);

  const applyReviewEntities = useCallback(
    (updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[])) => {
      setReviewEntities((prev) => {
        const next = typeof updater === 'function' ? updater(prev) : updater;
        pushReviewTextHistory(prev);
        reviewDraftDirtyRef.current = true;
        return next;
      });
    },
    [pushReviewTextHistory],
  );

  const undoReviewText = useCallback(() => {
    setReviewTextUndoStack((stack) => {
      if (!stack.length) return stack;
      const prev = stack[stack.length - 1];
      setReviewTextRedoStack((redo) => [...redo, reviewEntities.map((entity) => ({ ...entity }))]);
      setReviewEntities(prev.map((entity) => ({ ...entity })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewEntities]);

  const redoReviewText = useCallback(() => {
    setReviewTextRedoStack((stack) => {
      if (!stack.length) return stack;
      const next = stack[stack.length - 1];
      setReviewTextUndoStack((undo) => [...undo, reviewEntities.map((entity) => ({ ...entity }))]);
      setReviewEntities(next.map((entity) => ({ ...entity })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewEntities]);

  const undoReviewImage = useCallback(() => {
    setReviewImageUndoStack((stack) => {
      if (!stack.length) return stack;
      const prev = stack[stack.length - 1];
      setReviewImageRedoStack((redo) => [...redo, cloneBoxes(reviewBoxes)]);
      setReviewBoxes(cloneBoxes(prev));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewBoxes]);

  const redoReviewImage = useCallback(() => {
    setReviewImageRedoStack((stack) => {
      if (!stack.length) return stack;
      const next = stack[stack.length - 1];
      setReviewImageUndoStack((undo) => [...undo, cloneBoxes(reviewBoxes)]);
      setReviewBoxes(cloneBoxes(next));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewBoxes]);

  const toggleReviewEntitySelected = useCallback(
    (entityId: string) => {
      applyReviewEntities((prev) =>
        prev.map((entity) =>
          entity.id === entityId ? { ...entity, selected: !entity.selected } : entity,
        ),
      );
    },
    [applyReviewEntities],
  );

  const setVisibleReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>> = useCallback(
    (updater) => {
      setReviewBoxes((prevAll) => {
        const prevVisible = prevAll.filter((box) => Number(box.page || 1) === reviewCurrentPage);
        const nextVisible =
          typeof updater === 'function' ? updater(cloneBoxes(prevVisible)) : updater;
        reviewDraftDirtyRef.current = true;
        return mergeVisibleReviewBoxes(prevAll, cloneBoxes(nextVisible));
      });
    },
    [mergeVisibleReviewBoxes, reviewCurrentPage],
  );

  const handleReviewBoxesCommit = useCallback(
    (prevBoxes: EditorBox[], nextBoxes: EditorBox[]) => {
      setReviewBoxes((prevAll) => {
        const prevAllForHistory = mergeVisibleReviewBoxes(prevAll, cloneBoxes(prevBoxes));
        const nextAll = mergeVisibleReviewBoxes(prevAllForHistory, cloneBoxes(nextBoxes));
        setReviewImageUndoStack((stack) => [...stack, cloneBoxes(prevAllForHistory)]);
        setReviewImageRedoStack([]);
        reviewDraftDirtyRef.current = true;
        return nextAll;
      });
    },
    [mergeVisibleReviewBoxes],
  );

  const toggleReviewBoxSelected = useCallback((boxId: string) => {
    setReviewBoxes((prev) =>
      prev.map((box) => (box.id === boxId ? { ...box, selected: !box.selected } : box)),
    );
    reviewDraftDirtyRef.current = true;
  }, []);

  const buildCurrentReviewDraftPayload = useCallback(() => {
    const entities = reviewEntities.map((entity) => ({
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
    }));
    const bounding_boxes = reviewBoxes.map((box) => ({
      id: box.id,
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
      page: Number(box.page || 1),
      type: box.type,
      text: box.text,
      selected: box.selected,
      source: box.source,
      confidence: box.confidence,
      evidence_source: box.evidence_source,
      source_detail: box.source_detail,
      warnings: box.warnings,
    }));
    return { entities, bounding_boxes };
  }, [reviewEntities, reviewBoxes]);

  const flushCurrentReviewDraft = useCallback(async () => {
    if (isPreviewMode) return true;
    const jid = activeJobId;
    const linkedItemId = reviewFile ? itemIdByFileIdRef.current[reviewFile.file_id] : undefined;
    if (!jid || !linkedItemId) return true;
    if (!reviewDraftInitializedRef.current && !reviewDraftDirtyRef.current) return true;
    if (reviewAutosaveTimerRef.current !== null) {
      window.clearTimeout(reviewAutosaveTimerRef.current);
      reviewAutosaveTimerRef.current = null;
    }
    const payload = buildCurrentReviewDraftPayload();
    const json = JSON.stringify(payload);
    if (json === reviewLastSavedJsonRef.current) return true;
    setReviewDraftSaving(true);
    setReviewDraftError(null);
    try {
      await putItemReviewDraft(jid, linkedItemId, payload);
      reviewLastSavedJsonRef.current = JSON.stringify(payload);
      reviewDraftDirtyRef.current = false;
      return true;
    } catch (error) {
      setReviewDraftError(localizeErrorMessage(error, 'batchWizard.autoSaveFailed'));
      return false;
    } finally {
      setReviewDraftSaving(false);
    }
  }, [
    activeJobId,
    buildCurrentReviewDraftPayload,
    isPreviewMode,
    reviewAutosaveTimerRef,
    reviewFile,
    itemIdByFileIdRef,
  ]);

  const navigateReviewIndex = useCallback(
    async (nextIndex: number) => {
      if (nextIndex < 0 || nextIndex >= doneRows.length || nextIndex === reviewIndex) return;
      if (reviewLoading) return;
      const ok = await flushCurrentReviewDraft();
      if (!ok) {
        setMsg({ text: t('batchWizard.reviewSaveBeforeNavigateFailed'), tone: 'err' });
        return;
      }
      setReviewIndex(nextIndex);
    },
    [doneRows.length, flushCurrentReviewDraft, reviewIndex, reviewLoading, setMsg],
  );

  const displayPreviewMap = previewEntityMap;
  const textPreviewSegments = useMemo(
    () => buildTextSegments(reviewPageContent, previewEntityMap),
    [reviewPageContent, previewEntityMap],
  );
  const selectedReviewEntityCount = useMemo(
    () =>
      (isTextPaginated ? pageFilteredReviewEntities : reviewEntities).filter(
        (entity) => entity.selected !== false,
      ).length,
    [isTextPaginated, pageFilteredReviewEntities, reviewEntities],
  );
  const selectedReviewBoxCount = useMemo(
    () => visibleReviewBoxes.filter((box) => box.selected !== false).length,
    [visibleReviewBoxes],
  );
  const totalReviewBoxCount = reviewBoxes.length;
  const reviewImagePreviewSrc = useMemo(() => {
    if (!reviewImagePreview) return '';
    return reviewImagePreview.startsWith('data:')
      ? reviewImagePreview
      : `data:image/png;base64,${reviewImagePreview}`;
  }, [reviewImagePreview]);

  const reviewData = useBatchReviewData({
    step,
    reviewFile,
    activeJobId,
    itemIdByFileIdRef,
    cfg,
    isPreviewMode,
    textTypes,
    reviewEntities,
    reviewBoxes,
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
    setReviewCurrentPage: setReviewCurrentPageState,
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
  });

  return {
    reviewIndex,
    setReviewIndex,
    reviewEntities,
    reviewBoxes,
    visibleReviewBoxes,
    visibleReviewEntities,
    reviewPageContent,
    reviewCurrentPage,
    reviewTotalPages,
    reviewAllPagesVisited,
    reviewRequiredPagesVisited,
    visitedReviewPagesCount: visitedReviewPages.size,
    reviewPageSummaries,
    reviewHitPageCount,
    reviewUnvisitedHitPageCount,
    reviewRequiredPageCount,
    reviewUnvisitedRequiredPageCount,
    currentReviewVisionQuality,
    reviewPages,
    setReviewPages,
    reviewLoading,
    reviewLoadError,
    reviewExecuteLoading,
    setReviewExecuteLoading,
    reviewDraftSaving,
    reviewDraftError,
    reviewImagePreviewLoading: reviewData.reviewImagePreviewLoading,
    reviewOrigImageBlobUrl,
    reviewTextUndoStack,
    reviewTextRedoStack,
    reviewImageUndoStack,
    reviewImageRedoStack,
    reviewTextContent,
    reviewTextContentRef,
    reviewTextScrollRef,
    reviewDraftDirtyRef,
    reviewLastSavedJsonRef,

    reviewFile,
    doneRows,
    reviewFileReadOnly,
    reviewItemId,
    selectedReviewEntityCount,
    selectedReviewBoxCount,
    totalReviewBoxCount,
    reviewImagePreviewSrc,
    displayPreviewMap,
    textPreviewSegments,
    reviewedOutputCount,
    allReviewConfirmed,
    pendingReviewCount,

    applyReviewEntities,
    toggleReviewEntitySelected,
    setReviewBoxes,
    setVisibleReviewBoxes,
    setReviewCurrentPage,
    handleReviewBoxesCommit,
    toggleReviewBoxSelected,
    undoReviewText,
    redoReviewText,
    undoReviewImage,
    redoReviewImage,
    buildCurrentReviewDraftPayload,
    flushCurrentReviewDraft,
    navigateReviewIndex,
    loadReviewData: reviewData.loadReviewData,
    rerunCurrentItemRecognition: reviewData.rerunCurrentItemRecognition,
    rerunRecognitionLoading: reviewData.rerunRecognitionLoading,
  };
}
