
import {
  useCallback,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import { localizeErrorMessage } from '@/utils/localizeError';
import type { BatchWizardPersistedConfig } from '@/services/batchPipeline';
import { putItemReviewDraft } from '@/services/jobsApi';
import {
  buildTextSegments,
  mergePreviewMapWithDocumentSlices,
} from '@/utils/textRedactionSegments';
import type { BatchRow, ReviewEntity, Step, TextEntityType } from '../types';
import { RECOGNITION_DONE_STATUSES } from '../types';
import { useBatchReviewData } from './use-batch-review-data';

export interface BatchReviewState {
  reviewIndex: number;
  setReviewIndex: React.Dispatch<React.SetStateAction<number>>;
  reviewEntities: ReviewEntity[];
  reviewBoxes: EditorBox[];
  reviewLoading: boolean;
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
  reviewImagePreviewSrc: string;
  displayPreviewMap: Record<string, string>;
  textPreviewSegments: ReturnType<typeof buildTextSegments>;
  reviewedOutputCount: number;
  allReviewConfirmed: boolean;
  pendingReviewCount: number;

  // Actions
  applyReviewEntities: (updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[])) => void;
  toggleReviewEntitySelected: (entityId: string) => void;
  setReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>>;
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
  // ── Core review state ──
  const [reviewIndex, setReviewIndex] = useState(0);
  const [reviewEntities, setReviewEntities] = useState<ReviewEntity[]>([]);
  const [reviewBoxes, setReviewBoxes] = useState<EditorBox[]>([]);
  const [reviewLoading, setReviewLoading] = useState(false);
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
  const [previewEntityMap, setPreviewEntityMap] = useState<Record<string, string>>({});
  const reviewTextContentRef = useRef<HTMLDivElement | null>(null);
  const reviewTextScrollRef = useRef<HTMLDivElement | null>(null);
  const reviewAutosaveTimerRef = useRef<number | null>(null);
  const reviewLastSavedJsonRef = useRef('');
  const reviewDraftInitializedRef = useRef(false);
  const reviewDraftDirtyRef = useRef(false);

  // ── Derived ──
  const doneRows = useMemo(() => rows.filter(r => RECOGNITION_DONE_STATUSES.has(r.analyzeStatus)), [rows]);
  const reviewFile = doneRows[reviewIndex] ?? null;
  const reviewedOutputCount = useMemo(() => rows.filter(r => r.reviewConfirmed === true).length, [rows]);
  const pendingReviewCount = Math.max(0, rows.length - reviewedOutputCount);
  const allReviewConfirmed = rows.length > 0 && pendingReviewCount === 0;
  const reviewItemId = reviewFile ? itemIdByFileIdRef.current[reviewFile.file_id] : undefined;
  const reviewFileReadOnly = reviewFile?.analyzeStatus === 'completed' || reviewFile?.analyzeStatus === 'redacting';

  // ── Undo / Redo ──
  const pushReviewTextHistory = useCallback((prev: ReviewEntity[]) => {
    setReviewTextUndoStack(stack => [...stack, prev.map(e => ({ ...e }))]);
    setReviewTextRedoStack([]);
  }, []);

  const applyReviewEntities = useCallback((updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[])) => {
    setReviewEntities(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      pushReviewTextHistory(prev);
      reviewDraftDirtyRef.current = true;
      return next;
    });
  }, [pushReviewTextHistory]);

  const undoReviewText = useCallback(() => {
    setReviewTextUndoStack(stack => {
      if (!stack.length) return stack;
      const prev = stack[stack.length - 1];
      setReviewTextRedoStack(redo => [...redo, reviewEntities.map(e => ({ ...e }))]);
      setReviewEntities(prev.map(e => ({ ...e })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewEntities]);

  const redoReviewText = useCallback(() => {
    setReviewTextRedoStack(stack => {
      if (!stack.length) return stack;
      const next = stack[stack.length - 1];
      setReviewTextUndoStack(undo => [...undo, reviewEntities.map(e => ({ ...e }))]);
      setReviewEntities(next.map(e => ({ ...e })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewEntities]);

  const undoReviewImage = useCallback(() => {
    setReviewImageUndoStack(stack => {
      if (!stack.length) return stack;
      const prev = stack[stack.length - 1];
      setReviewImageRedoStack(redo => [...redo, reviewBoxes.map(b => ({ ...b }))]);
      setReviewBoxes(prev.map(b => ({ ...b })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewBoxes]);

  const redoReviewImage = useCallback(() => {
    setReviewImageRedoStack(stack => {
      if (!stack.length) return stack;
      const next = stack[stack.length - 1];
      setReviewImageUndoStack(undo => [...undo, reviewBoxes.map(b => ({ ...b }))]);
      setReviewBoxes(next.map(b => ({ ...b })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewBoxes]);

  const toggleReviewEntitySelected = useCallback((entityId: string) => {
    applyReviewEntities(prev => prev.map(e => (e.id === entityId ? { ...e, selected: !e.selected } : e)));
  }, [applyReviewEntities]);

  const handleReviewBoxesCommit = useCallback((prevBoxes: EditorBox[], nextBoxes: EditorBox[]) => {
    setReviewImageUndoStack(stack => [...stack, prevBoxes.map(b => ({ ...b }))]);
    setReviewImageRedoStack([]);
    setReviewBoxes(nextBoxes.map(b => ({ ...b })));
    reviewDraftDirtyRef.current = true;
  }, []);

  const toggleReviewBoxSelected = useCallback((boxId: string) => {
    setReviewBoxes(prev => prev.map(b => (b.id === boxId ? { ...b, selected: !b.selected } : b)));
    reviewDraftDirtyRef.current = true;
  }, []);

  // ── Draft management ──
  const buildCurrentReviewDraftPayload = useCallback(() => {
    const entities = reviewEntities.map(e => ({
      id: e.id, text: e.text, type: e.type, start: e.start, end: e.end,
      page: e.page ?? 1, confidence: e.confidence ?? 1, selected: e.selected,
      source: e.source, coref_id: e.coref_id, replacement: e.replacement,
    }));
    const bounding_boxes = reviewBoxes.map(b => ({
      id: b.id, x: b.x, y: b.y, width: b.width, height: b.height,
      page: 1, type: b.type, text: b.text, selected: b.selected,
      source: b.source, confidence: b.confidence,
    }));
    return { entities, bounding_boxes };
  }, [reviewEntities, reviewBoxes]);

  const flushCurrentReviewDraft = useCallback(async () => {
    if (isPreviewMode) return true;
    const jid = activeJobId;
    const linkedItemId = reviewFile ? itemIdByFileIdRef.current[reviewFile.file_id] : undefined;
    if (!jid || !linkedItemId || !reviewDraftInitializedRef.current) return true;
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
    } catch (e) {
      setReviewDraftError(localizeErrorMessage(e, 'batchWizard.autoSaveFailed'));
      return false;
    } finally {
      setReviewDraftSaving(false);
    }
  }, [activeJobId, buildCurrentReviewDraftPayload, isPreviewMode, reviewFile]);

  // ── Navigate review index ──
  const navigateReviewIndex = useCallback(async (nextIndex: number) => {
    if (nextIndex < 0 || nextIndex >= doneRows.length || nextIndex === reviewIndex) return;
    if (reviewLoading) return;
    await flushCurrentReviewDraft();
    setReviewIndex(nextIndex);
  }, [doneRows.length, flushCurrentReviewDraft, reviewIndex, reviewLoading]);

  // ── Derived display values ──
  const displayPreviewMap = useMemo(() => mergePreviewMapWithDocumentSlices(reviewTextContent, reviewEntities, previewEntityMap), [reviewTextContent, reviewEntities, previewEntityMap]);
  const textPreviewSegments = useMemo(() => buildTextSegments(reviewTextContent, displayPreviewMap), [reviewTextContent, displayPreviewMap]);
  const selectedReviewEntityCount = useMemo(() => reviewEntities.filter(e => e.selected !== false).length, [reviewEntities]);
  const selectedReviewBoxCount = useMemo(() => reviewBoxes.filter(b => b.selected !== false).length, [reviewBoxes]);
  const reviewImagePreviewSrc = useMemo(() => {
    if (!reviewImagePreview) return '';
    return reviewImagePreview.startsWith('data:') ? reviewImagePreview : `data:image/png;base64,${reviewImagePreview}`;
  }, [reviewImagePreview]);

  // ── Data loading (effects + callbacks delegated to sub-hook) ──
  const reviewData = useBatchReviewData({
    step, reviewFile, activeJobId, itemIdByFileIdRef, cfg, isPreviewMode,
    textTypes, reviewEntities, reviewBoxes, reviewItemId,
    reviewLoading, reviewTextContent, previewEntityMap,
    reviewDraftInitializedRef, reviewDraftDirtyRef,
    reviewLastSavedJsonRef, reviewAutosaveTimerRef,
    setReviewLoading, setPreviewEntityMap, setReviewImagePreview,
    setReviewDraftError, setReviewEntities, setReviewBoxes,
    setReviewTextContent, setReviewOrigImageBlobUrl,
    setReviewTextUndoStack, setReviewTextRedoStack,
    setReviewImageUndoStack, setReviewImageRedoStack,
    buildCurrentReviewDraftPayload, flushCurrentReviewDraft, setMsg,
  });

  return {
    reviewIndex,
    setReviewIndex,
    reviewEntities,
    reviewBoxes,
    reviewLoading,
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

    // Derived
    reviewFile,
    doneRows,
    reviewFileReadOnly,
    reviewItemId,
    selectedReviewEntityCount,
    selectedReviewBoxCount,
    reviewImagePreviewSrc,
    displayPreviewMap,
    textPreviewSegments,
    reviewedOutputCount,
    allReviewConfirmed,
    pendingReviewCount,

    // Actions
    applyReviewEntities,
    toggleReviewEntitySelected,
    setReviewBoxes,
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
