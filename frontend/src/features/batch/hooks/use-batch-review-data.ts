
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { localizeErrorMessage } from '@/utils/localizeError';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import { fileApi, authenticatedBlobUrl } from '@/services/api';
import { authFetch } from '@/services/api-client';
import { ReplacementMode } from '@/types';
import {
  batchGetFileRaw,
  batchPreviewImage,
  flattenBoundingBoxesFromStore,
  type BatchWizardPersistedConfig,
} from '@/services/batchPipeline';
import {
  getItemReviewDraft,
} from '@/services/jobsApi';
import { getPreviewReviewPayload } from '../lib/batch-preview-fixtures';
import type { BatchRow, ReviewEntity, Step, TextEntityType } from '../types';
import { fetchBatchPreviewMap, normalizeReviewEntity } from './use-batch-wizard-utils';

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
  setReviewEntities: React.Dispatch<React.SetStateAction<ReviewEntity[]>>;
  setReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>>;
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

export function useBatchReviewData(deps: ReviewDataDeps): ReviewDataState {
  const {
    step, reviewFile, activeJobId, itemIdByFileIdRef, cfg, isPreviewMode,
    textTypes, reviewEntities, reviewBoxes, reviewItemId,
    reviewLoading, reviewTextContent,
    reviewDraftInitializedRef, reviewDraftDirtyRef,
    reviewLastSavedJsonRef, reviewAutosaveTimerRef,
    setReviewLoading, setPreviewEntityMap, setReviewImagePreview,
    setReviewDraftError, setReviewEntities, setReviewBoxes,
    setReviewTextContent, setReviewOrigImageBlobUrl,
    setReviewTextUndoStack, setReviewTextRedoStack,
    setReviewImageUndoStack, setReviewImageRedoStack,
    buildCurrentReviewDraftPayload, flushCurrentReviewDraft, setMsg,
  } = deps;

  const reviewLoadSeqRef = useRef(0);
  const batchScrollCountersRef = useRef<Record<string, number>>({});
  const [rerunRecognitionLoading, setRerunRecognitionLoading] = useState(false);
  const [reviewImagePreviewLoading, setReviewImagePreviewLoading] = useState(false);

  // ── Reset scroll counters ──
  useEffect(() => { batchScrollCountersRef.current = {}; }, [reviewFile?.file_id]);

  // ── Load original image blob ──
  useEffect(() => {
    let cancelled = false;
    let currentBlobUrl = '';
    if (!reviewFile || !reviewFile.isImageMode) { setReviewOrigImageBlobUrl(''); return; }
    const raw = fileApi.getDownloadUrl(reviewFile.file_id, false);
    authenticatedBlobUrl(raw).then(u => {
      if (!cancelled) { currentBlobUrl = u; setReviewOrigImageBlobUrl(u); }
      else if (u.startsWith('blob:')) URL.revokeObjectURL(u);
    }).catch(() => { if (!cancelled) setReviewOrigImageBlobUrl(raw); });
    return () => { cancelled = true; if (currentBlobUrl.startsWith('blob:')) URL.revokeObjectURL(currentBlobUrl); };
  }, [reviewFile?.file_id, reviewFile?.isImageMode]);

  // ── Set loading on step/file change ──
  useLayoutEffect(() => {
    if (step !== 4 || !reviewFile) return;
    setReviewLoading(true);
  }, [step, reviewFile?.file_id, reviewFile?.isImageMode]);

  // ── Load review data ──
  const loadReviewData = useCallback(
    async (fileId: string, isImage: boolean) => {
      const loadSeq = reviewLoadSeqRef.current + 1;
      reviewLoadSeqRef.current = loadSeq;
      setReviewLoading(true);
      setPreviewEntityMap({});
      setReviewImagePreview('');
      setReviewDraftError(null);
      setReviewEntities([]);
      setReviewBoxes([]);
      setReviewTextContent('');
      reviewDraftInitializedRef.current = false;
      reviewDraftDirtyRef.current = false;
      if (reviewAutosaveTimerRef.current !== null) {
        window.clearTimeout(reviewAutosaveTimerRef.current);
        reviewAutosaveTimerRef.current = null;
      }
      if (isPreviewMode) {
        const previewPayload = getPreviewReviewPayload(fileId);
        if (isImage) {
          setReviewTextContent('');
          setReviewEntities([]);
          setReviewBoxes(previewPayload.boxes.map((box) => ({ ...box })));
          setReviewOrigImageBlobUrl(previewPayload.imageSrc);
          setReviewImagePreview(previewPayload.previewSrc);
          setReviewImageUndoStack([]);
          setReviewImageRedoStack([]);
          reviewLastSavedJsonRef.current = JSON.stringify({ entities: [], bounding_boxes: previewPayload.boxes });
        } else {
          setReviewBoxes([]);
          setReviewEntities(previewPayload.entities.map((entity) => ({ ...entity })));
          setReviewTextContent(previewPayload.content);
          setReviewTextUndoStack([]);
          setReviewTextRedoStack([]);
          const map = await fetchBatchPreviewMap(previewPayload.entities, cfg.replacementMode);
          if (loadSeq !== reviewLoadSeqRef.current) return;
          setPreviewEntityMap(map);
          reviewLastSavedJsonRef.current = JSON.stringify({ entities: previewPayload.entities, bounding_boxes: [] });
        }
        reviewDraftInitializedRef.current = true;
        setReviewLoading(false);
        return;
      }
      try {
        const info = await batchGetFileRaw(fileId);
        if (loadSeq !== reviewLoadSeqRef.current) return;
        const linkedItemId = itemIdByFileIdRef.current[fileId];
        let draft: { exists?: boolean; entities?: Array<Record<string, unknown>>; bounding_boxes?: Array<Record<string, unknown>> } | null = null;
        if (activeJobId && linkedItemId) {
          try {
            const loadedDraft = await getItemReviewDraft(activeJobId, linkedItemId);
            if (loadSeq !== reviewLoadSeqRef.current) return;
            if (loadedDraft.exists) draft = loadedDraft;
          } catch { /* ignore */ }
        }
        if (isImage) {
          setReviewTextContent('');
          const raw = draft?.bounding_boxes && draft.bounding_boxes.length > 0 ? draft.bounding_boxes : flattenBoundingBoxesFromStore(info.bounding_boxes);
          const boxes: EditorBox[] = raw.map((b, idx) => ({
            id: String(b.id ?? `bbox_${idx}`), x: Number(b.x), y: Number(b.y),
            width: Number(b.width), height: Number(b.height), type: String(b.type ?? 'CUSTOM'),
            text: b.text ? String(b.text) : undefined, selected: b.selected !== false,
            confidence: typeof b.confidence === 'number' ? b.confidence : undefined,
            source: (b.source as EditorBox['source']) || undefined,
          }));
          setReviewBoxes(boxes);
          setReviewEntities([]);
          setReviewImageUndoStack([]);
          setReviewImageRedoStack([]);
          reviewLastSavedJsonRef.current = JSON.stringify({ entities: [], bounding_boxes: boxes.map(b => ({ id: b.id, x: b.x, y: b.y, width: b.width, height: b.height, page: 1, type: b.type, text: b.text, selected: b.selected, source: b.source, confidence: b.confidence })) });
        } else {
          setReviewEntities([]);
          setReviewTextContent('');
          const ents = ((draft?.entities as ReviewEntity[] | undefined) ?? (info.entities as ReviewEntity[]) ?? []);
          const mapped = ents.map((e, i) =>
            normalizeReviewEntity({ id: e.id || `ent_${i}`, text: e.text, type: typeof e.type === 'string' ? e.type : String(e.type ?? 'CUSTOM'), start: typeof e.start === 'number' ? e.start : Number(e.start), end: typeof e.end === 'number' ? e.end : Number(e.end), selected: e.selected !== false, page: e.page ?? 1, confidence: e.confidence, source: e.source, coref_id: e.coref_id, replacement: e.replacement }),
          );
          setReviewBoxes([]);
          const contentStr = typeof info.content === 'string' ? info.content : '';
          setReviewEntities(mapped);
          setReviewTextContent(contentStr);
          setReviewTextUndoStack([]);
          setReviewTextRedoStack([]);
          const map = await fetchBatchPreviewMap(mapped, cfg.replacementMode);
          if (loadSeq !== reviewLoadSeqRef.current) return;
          setPreviewEntityMap(map);
          reviewLastSavedJsonRef.current = JSON.stringify({ entities: mapped.map(e => ({ id: e.id, text: e.text, type: e.type, start: e.start, end: e.end, page: e.page ?? 1, confidence: e.confidence ?? 1, selected: e.selected, source: e.source, coref_id: e.coref_id, replacement: e.replacement })), bounding_boxes: [] });
        }
        reviewDraftInitializedRef.current = true;
      } finally {
        if (loadSeq === reviewLoadSeqRef.current) setReviewLoading(false);
      }
    },
    [activeJobId, cfg.replacementMode, cfg.selectedEntityTypeIds, isPreviewMode, textTypes],
  );

  // Auto-load review data when step 4 and reviewFile changes
  useEffect(() => {
    if (step !== 4 || !reviewFile) return;
    const isImg = reviewFile.isImageMode === true;
    void loadReviewData(reviewFile.file_id, isImg);
  }, [step, reviewFile?.file_id, reviewFile?.isImageMode, loadReviewData]);

  // ── Re-run recognition ──
  const rerunCurrentItemRecognition = useCallback(async () => {
    if (!reviewFile) return;
    const isImage = reviewFile.isImageMode === true;
    setRerunRecognitionLoading(true);
    try {
      if (isImage) {
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), 400_000);
        let res: Response;
        try {
          res = await authFetch(`/api/v1/redaction/${reviewFile.file_id}/vision?page=1`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              selected_ocr_has_types: cfg.ocrHasTypes,
              selected_has_image_types: cfg.hasImageTypes,
            }),
            signal: controller.signal,
          });
        } finally {
          window.clearTimeout(timer);
        }
        if (!res.ok) throw new Error('Vision detection failed');
        const data = await res.json();
        const boxes: EditorBox[] = ((data.bounding_boxes || []) as Record<string, unknown>[]).map((b, idx) => ({
          id: String(b.id ?? `bbox_${idx}`),
          x: Number(b.x),
          y: Number(b.y),
          width: Number(b.width),
          height: Number(b.height),
          type: String(b.type ?? 'CUSTOM'),
          text: b.text ? String(b.text) : undefined,
          selected: true,
          confidence: typeof b.confidence === 'number' ? b.confidence : undefined,
          source: (b.source as EditorBox['source']) || undefined,
        }));
        setReviewBoxes(boxes);
        setReviewImageUndoStack([]);
        setReviewImageRedoStack([]);
      } else {
        const nerRes = await authFetch(`/api/v1/files/${reviewFile.file_id}/ner/hybrid`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entity_type_ids: cfg.selectedEntityTypeIds }),
        });
        if (!nerRes.ok) throw new Error('NER recognition failed');
        const nerData = await nerRes.json();
        const entities: ReviewEntity[] = ((nerData.entities || []) as Record<string, unknown>[]).map(
          (e, idx) => normalizeReviewEntity({
            id: String(e.id || `ent_${idx}`),
            text: String(e.text ?? ''),
            type: String(e.type ?? 'CUSTOM'),
            start: Number(e.start ?? 0),
            end: Number(e.end ?? 0),
            selected: true,
            source: (e.source as ReviewEntity['source']) || 'llm',
            page: Number(e.page ?? 1),
            confidence: typeof e.confidence === 'number' ? e.confidence : 1,
            coref_id: e.coref_id as string | undefined,
            replacement: e.replacement as string | undefined,
          }),
        );
        setReviewEntities(entities);
        setReviewTextUndoStack([]);
        setReviewTextRedoStack([]);
        const map = await fetchBatchPreviewMap(entities, cfg.replacementMode);
        setPreviewEntityMap(map);
      }
      reviewDraftDirtyRef.current = true;
    } catch (e) {
      setMsg({ text: localizeErrorMessage(e, 'batchWizard.actionFailed'), tone: 'err' });
    } finally {
      setRerunRecognitionLoading(false);
    }
  }, [reviewFile, cfg.selectedEntityTypeIds, cfg.ocrHasTypes, cfg.hasImageTypes, cfg.replacementMode]);

  // ── Autosave ──
  useEffect(() => {
    if (isPreviewMode) return;
    if (step !== 4 || !reviewFile || !reviewDraftInitializedRef.current) return;
    if (!activeJobId || !reviewItemId) return;
    const payload = buildCurrentReviewDraftPayload();
    const json = JSON.stringify(payload);
    if (json === reviewLastSavedJsonRef.current) return;
    reviewDraftDirtyRef.current = true;
    if (reviewAutosaveTimerRef.current !== null) window.clearTimeout(reviewAutosaveTimerRef.current);
    reviewAutosaveTimerRef.current = window.setTimeout(() => { void flushCurrentReviewDraft(); }, 900);
    return () => { if (reviewAutosaveTimerRef.current !== null) { window.clearTimeout(reviewAutosaveTimerRef.current); reviewAutosaveTimerRef.current = null; } };
  }, [step, reviewFile?.file_id, reviewItemId, activeJobId, buildCurrentReviewDraftPayload, flushCurrentReviewDraft, isPreviewMode]);

  // ── Preview map refresh ──
  useEffect(() => {
    if (isPreviewMode) return;
    if (step !== 4 || !reviewFile || reviewLoading || reviewFile.isImageMode) return;
    if (!reviewTextContent || reviewEntities.length === 0) { setPreviewEntityMap({}); return; }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const map = await fetchBatchPreviewMap(reviewEntities, cfg.replacementMode);
      if (!cancelled) setPreviewEntityMap(map);
    }, 300);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [step, reviewFile?.file_id, reviewEntities, reviewTextContent, reviewLoading, cfg.replacementMode, isPreviewMode]);

  // ── Image preview ──
  useEffect(() => {
    if (isPreviewMode) return;
    if (step !== 4 || !reviewFile || reviewLoading || !reviewFile.isImageMode) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        setReviewImagePreviewLoading(true);
        const imageBase64 = await batchPreviewImage({
          file_id: reviewFile.file_id, page: 1,
          bounding_boxes: reviewBoxes.filter(b => b.selected !== false).map(b => ({ id: b.id, x: b.x, y: b.y, width: b.width, height: b.height, page: 1, type: b.type, text: b.text, selected: b.selected, source: b.source, confidence: b.confidence })),
          config: { replacement_mode: ReplacementMode.STRUCTURED, entity_types: [], custom_replacements: {}, image_redaction_method: cfg.imageRedactionMethod ?? 'mosaic', image_redaction_strength: cfg.imageRedactionStrength ?? 25, image_fill_color: cfg.imageFillColor ?? '#000000' },
        });
        if (!cancelled) setReviewImagePreview(imageBase64);
      } catch { if (!cancelled) setReviewImagePreview(''); }
      finally { if (!cancelled) setReviewImagePreviewLoading(false); }
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [step, reviewFile?.file_id, reviewBoxes, reviewLoading, cfg.imageRedactionMethod, cfg.imageRedactionStrength, cfg.imageFillColor, isPreviewMode]);

  return {
    loadReviewData,
    rerunCurrentItemRecognition,
    rerunRecognitionLoading,
    reviewImagePreviewLoading,
  };
}
