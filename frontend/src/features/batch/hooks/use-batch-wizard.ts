/**
 * use-batch-wizard — all wizard state and actions for the 5-step batch wizard.
 *
 * Extracted from pages/Batch.tsx (3510 lines) into a standalone hook.
 * Handles: step navigation, job config, file upload, recognition polling,
 * review state (text entities + image bboxes), and export/download.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  useLocation,
  useParams,
  useBlocker,
  useSearchParams,
} from 'react-router-dom';
import { t } from '@/i18n';
import { useDropzone } from 'react-dropzone';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';

import { fileApi, authenticatedBlobUrl } from '@/services/api';
import type { FileListItem } from '@/types';
import { FileType, ReplacementMode } from '@/types';
import {
  batchGetFileRaw,
  batchPreviewEntityMap,
  batchPreviewImage,
  flattenBoundingBoxesFromStore,
  loadBatchWizardConfig,
  saveBatchWizardConfig,
  type BatchWizardMode,
  type BatchWizardPersistedConfig,
} from '@/services/batchPipeline';
import {
  getActivePresetTextId,
  getActivePresetVisionId,
  setActivePresetTextId,
  setActivePresetVisionId,
} from '@/services/activePresetBridge';
import {
  fetchPresets,
  presetAppliesText,
  presetAppliesVision,
  type RecognitionPreset,
} from '@/services/presetsApi';
import {
  buildDefaultPipelineTypeIds,
  buildDefaultTextTypeIds,
} from '@/services/defaultRedactionPreset';
import { fetchWithTimeout } from '@/utils/fetchWithTimeout';
import {
  buildFallbackPreviewEntityMap,
  buildTextSegments,
  mergePreviewMapWithDocumentSlices,
} from '@/utils/textRedactionSegments';
// redactionState used by step components directly
import {
  createJob,
  getJob,
  submitJob as apiSubmitJob,
  updateJobDraft,
  commitItemReview,
  getItemReviewDraft,
  putItemReviewDraft,
  requeueFailed,
} from '@/services/jobsApi';
import {
  effectiveWizardFurthestStep,
  parseWizardFurthestFromUnknown,
} from '@/utils/jobPrimaryNavigation';

// ── Types ──────────────────────────────────────────────────────────────

export type Step = 1 | 2 | 3 | 4 | 5;

export interface PipelineCfg {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: { id: string; name: string; color: string; enabled: boolean; order?: number }[];
}

export interface TextEntityType {
  id: string;
  name: string;
  color: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  order?: number;
}

export interface BatchRow extends FileListItem {
  analyzeStatus:
    | 'pending'
    | 'parsing'
    | 'analyzing'
    | 'awaiting_review'
    | 'review_approved'
    | 'redacting'
    | 'completed'
    | 'failed';
  analyzeError?: string;
  isImageMode?: boolean;
  reviewConfirmed?: boolean;
}

export type ReviewEntity = {
  id: string;
  text: string;
  type: string;
  start: number;
  end: number;
  selected: boolean;
  page?: number;
  confidence?: number;
  source?: string;
  coref_id?: string | null;
  replacement?: string;
};

export const RECOGNITION_DONE_STATUSES: ReadonlySet<BatchRow['analyzeStatus']> = new Set([
  'awaiting_review',
  'review_approved',
  'redacting',
  'completed',
]);

export const ANALYZE_STATUS_LABEL: Record<BatchRow['analyzeStatus'], string> = {
  pending: '等待中',
  parsing: '解析中',
  analyzing: '识别中',
  awaiting_review: '待审阅',
  review_approved: '待脱敏',
  redacting: '脱敏中',
  completed: '已完成',
  failed: '失败',
};

export const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: t('batchWizard.step1') },
  { n: 2, label: t('batchWizard.step2') },
  { n: 3, label: t('batchWizard.step3') },
  { n: 4, label: t('batchWizard.step4') },
  { n: 5, label: t('batchWizard.step5') },
];

// ── Helpers ────────────────────────────────────────────────────────────

function mapBackendStatus(status: string): BatchRow['analyzeStatus'] {
  switch (status) {
    case 'failed':
    case 'cancelled':
      return 'failed';
    case 'awaiting_review':
      return 'awaiting_review';
    case 'review_approved':
      return 'review_approved';
    case 'redacting':
      return 'redacting';
    case 'completed':
      return 'completed';
    case 'processing':
    case 'parsing':
    case 'ner':
    case 'vision':
      return 'analyzing';
    default:
      return 'pending';
  }
}

function deriveReviewConfirmed(item: { status: string; has_output?: boolean | null }): boolean {
  if (item.status === 'completed') return item.has_output !== false;
  return item.status === 'review_approved' || item.status === 'redacting';
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function defaultConfig(): BatchWizardPersistedConfig {
  return {
    selectedEntityTypeIds: [],
    ocrHasTypes: [],
    hasImageTypes: [],
    replacementMode: 'structured',
    imageRedactionMethod: 'mosaic',
    imageRedactionStrength: 25,
    imageFillColor: '#000000',
    presetTextId: null,
    presetVisionId: null,
    presetId: null,
    executionDefault: 'queue',
  };
}

function normalizeReviewEntity(e: ReviewEntity): ReviewEntity {
  const start = Math.max(0, Math.floor(Number(e.start) || 0));
  const end = Math.max(start, Math.floor(Number(e.end) || 0));
  return {
    ...e,
    id: String(e.id ?? ''),
    text: String(e.text ?? ''),
    type: String(e.type ?? 'CUSTOM'),
    start,
    end,
    page: Math.max(1, Math.floor(Number(e.page) || 1)),
    confidence: typeof e.confidence === 'number' && !Number.isNaN(e.confidence) ? e.confidence : 1,
    selected: e.selected !== false,
  };
}

function buildJobConfigForWorker(
  c: BatchWizardPersistedConfig,
  wizardMode: BatchWizardMode,
  wizardFurthestStep: Step,
): Record<string, unknown> {
  return {
    entity_type_ids: c.selectedEntityTypeIds,
    ocr_has_types: c.ocrHasTypes,
    has_image_types: c.hasImageTypes,
    replacement_mode: c.replacementMode,
    image_redaction_method: c.imageRedactionMethod,
    image_redaction_strength: c.imageRedactionStrength,
    image_fill_color: c.imageFillColor,
    batch_wizard_mode: wizardMode,
    preferred_execution: c.executionDefault === 'local' ? 'local' : 'queue',
    wizard_furthest_step: wizardFurthestStep,
  };
}

function mergeJobConfigIntoWizardCfg(
  c: BatchWizardPersistedConfig,
  jc: Record<string, unknown>,
): BatchWizardPersistedConfig {
  return {
    ...c,
    selectedEntityTypeIds:
      Array.isArray(jc.entity_type_ids) && (jc.entity_type_ids as string[]).length
        ? (jc.entity_type_ids as string[])
        : c.selectedEntityTypeIds,
    ocrHasTypes:
      Array.isArray(jc.ocr_has_types) && (jc.ocr_has_types as string[]).length
        ? (jc.ocr_has_types as string[])
        : c.ocrHasTypes,
    hasImageTypes:
      Array.isArray(jc.has_image_types) && (jc.has_image_types as string[]).length
        ? (jc.has_image_types as string[])
        : c.hasImageTypes,
    replacementMode:
      jc.replacement_mode === 'smart' ||
      jc.replacement_mode === 'mask' ||
      jc.replacement_mode === 'structured'
        ? (jc.replacement_mode as BatchWizardPersistedConfig['replacementMode'])
        : c.replacementMode,
    imageRedactionMethod:
      jc.image_redaction_method === 'mosaic' ||
      jc.image_redaction_method === 'blur' ||
      jc.image_redaction_method === 'fill'
        ? jc.image_redaction_method
        : c.imageRedactionMethod,
    imageRedactionStrength:
      typeof jc.image_redaction_strength === 'number'
        ? jc.image_redaction_strength
        : c.imageRedactionStrength,
    imageFillColor:
      typeof jc.image_fill_color === 'string' ? jc.image_fill_color : c.imageFillColor,
  };
}

const BATCH_WIZ_FURTHEST_LS_PREFIX = 'lr_batch_wiz_furthest_';

function readLocalWizardMaxStep(jobId: string): Step | null {
  try {
    const v = localStorage.getItem(BATCH_WIZ_FURTHEST_LS_PREFIX + jobId);
    return parseWizardFurthestFromUnknown(v);
  } catch {
    return null;
  }
}

function writeLocalWizardMaxStep(jobId: string, step: Step) {
  try {
    const prev = readLocalWizardMaxStep(jobId);
    const merged = Math.max(step, prev ?? 1) as Step;
    if (merged >= 2) localStorage.setItem(BATCH_WIZ_FURTHEST_LS_PREFIX + jobId, String(merged));
  } catch {
    /* ignore */
  }
}

function clearLocalWizardMaxStep(jobId: string) {
  try {
    localStorage.removeItem(BATCH_WIZ_FURTHEST_LS_PREFIX + jobId);
  } catch {
    /* ignore */
  }
}

function applyTextPresetFields(
  p: RecognitionPreset,
  textTypes: TextEntityType[],
): Pick<BatchWizardPersistedConfig, 'selectedEntityTypeIds' | 'presetTextId'> &
  Partial<Pick<BatchWizardPersistedConfig, 'replacementMode'>> {
  const textIds = new Set(textTypes.map(tt => tt.id));
  const base = {
    selectedEntityTypeIds: p.selectedEntityTypeIds.filter((id: string) => textIds.has(id)),
    presetTextId: p.id,
  };
  if ((p.kind ?? 'full') === 'text') return base;
  return { ...base, replacementMode: p.replacementMode };
}

function applyVisionPresetFields(
  p: RecognitionPreset,
  pipelines: PipelineCfg[],
): Pick<BatchWizardPersistedConfig, 'ocrHasTypes' | 'hasImageTypes' | 'presetVisionId'> {
  const ocrIds = pipelines
    .filter(pl => pl.mode === 'ocr_has' && pl.enabled)
    .flatMap(pl => pl.types.filter(tt => tt.enabled).map(tt => tt.id));
  const hiIds = pipelines
    .filter(pl => pl.mode === 'has_image' && pl.enabled)
    .flatMap(pl => pl.types.filter(tt => tt.enabled).map(tt => tt.id));
  return {
    ocrHasTypes: p.ocrHasTypes.filter((id: string) => ocrIds.includes(id)),
    hasImageTypes: p.hasImageTypes.filter((id: string) => hiIds.includes(id)),
    presetVisionId: p.id,
  };
}

async function fetchBatchPreviewMap(
  entities: ReviewEntity[],
  replacementMode: BatchWizardPersistedConfig['replacementMode'],
): Promise<Record<string, string>> {
  const visible = entities.filter(e => e.selected !== false);
  const payload = visible.map(e => {
    const n = normalizeReviewEntity(e);
    return {
      id: n.id, text: n.text, type: n.type,
      start: n.start, end: n.end, page: n.page,
      confidence: n.confidence, selected: n.selected,
      source: n.source, coref_id: n.coref_id,
    };
  });
  if (payload.length === 0) return {};
  const replacement_mode =
    replacementMode === 'smart'
      ? ReplacementMode.SMART
      : replacementMode === 'mask'
        ? ReplacementMode.MASK
        : ReplacementMode.STRUCTURED;
  const modeKey: 'structured' | 'smart' | 'mask' =
    replacementMode === 'smart' ? 'smart' : replacementMode === 'mask' ? 'mask' : 'structured';
  try {
    const map = await batchPreviewEntityMap({
      entities: payload,
      config: { replacement_mode, entity_types: [], custom_replacements: {} },
    });
    if (map && Object.keys(map).length > 0) return map;
  } catch {
    /* fallback */
  }
  return buildFallbackPreviewEntityMap(
    payload.map(p => ({ text: p.text, type: p.type, selected: p.selected })),
    modeKey,
  );
}

// ── Hook ───────────────────────────────────────────────────────────────

export function useBatchWizard() {
  const { batchMode } = useParams<{ batchMode: string }>();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const modeValid = batchMode === 'text' || batchMode === 'image' || batchMode === 'smart';
  const mode: BatchWizardMode = 'smart';
  const sessionJobKey = `lr_batch_job_id_${mode}`;

  // ── Job identity ──
  const [activeJobId, setActiveJobId] = useState<string | null>(() => {
    try { return sessionStorage.getItem(sessionJobKey); } catch { return null; }
  });
  const [jobSkipItemReview, setJobSkipItemReview] = useState(false);
  const itemIdByFileIdRef = useRef<Record<string, string>>({});
  const hydratedFromUrlRef = useRef(false);
  const batchHydrateGenRef = useRef(0);
  const urlHydrateKeyRef = useRef('');
  const prevHydrateUrlStepRef = useRef<string | null>(null);
  const internalStepNavRef = useRef(false);
  const lastSavedJobConfigJson = useRef<string>('');
  const prevFurthestForImmediateSaveRef = useRef<Step>(1);

  // ── Step tracking ──
  const [step, setStep] = useState<Step>(1);
  const [furthestStep, setFurthestStep] = useState<Step>(1);

  // ── Config ──
  const [cfg, setCfg] = useState<BatchWizardPersistedConfig>(() => defaultConfig());
  const [textTypes, setTextTypes] = useState<TextEntityType[]>([]);
  const [pipelines, setPipelines] = useState<PipelineCfg[]>([]);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [presets, setPresets] = useState<RecognitionPreset[]>([]);
  const [confirmStep1, setConfirmStep1] = useState(false);
  const [jobPriority, setJobPriority] = useState<number>(0);

  // ── File rows ──
  const [rows, setRows] = useState<BatchRow[]>([]);
  const batchGroupIdRef = useRef<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [analyzeRunning, _setAnalyzeRunning] = useState(false);
  const [zipLoading, setZipLoading] = useState(false);
  const [msg, setMsg] = useState<{ text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null>(null);

  // ── Review state ──
  const [reviewIndex, setReviewIndex] = useState(0);
  const [reviewEntities, setReviewEntities] = useState<ReviewEntity[]>([]);
  const [reviewBoxes, setReviewBoxes] = useState<EditorBox[]>([]);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewExecuteLoading, setReviewExecuteLoading] = useState(false);
  const [reviewDraftSaving, setReviewDraftSaving] = useState(false);
  const [reviewDraftError, setReviewDraftError] = useState<string | null>(null);
  const [reviewImagePreview, setReviewImagePreview] = useState('');
  const [reviewImagePreviewLoading, setReviewImagePreviewLoading] = useState(false);
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
  const batchScrollCountersRef = useRef<Record<string, number>>({});
  const reviewLoadSeqRef = useRef(0);

  const [leaveConfirmOpen, _setLeaveConfirmOpen] = useState(false);
  const [_pendingStepAfterLeave, _setPendingStepAfterLeave] = useState<Step | null>(null);

  // ── Session persistence ──
  useEffect(() => {
    try {
      if (activeJobId) sessionStorage.setItem(sessionJobKey, activeJobId);
      else sessionStorage.removeItem(sessionJobKey);
    } catch { /* ignore */ }
  }, [activeJobId, sessionJobKey]);

  useEffect(() => {
    const jid = searchParams.get('jobId');
    if (!jid) return;
    setActiveJobId(prev => (prev === jid ? prev : jid));
  }, [searchParams]);

  useEffect(() => { lastSavedJobConfigJson.current = ''; }, [activeJobId]);
  useEffect(() => { prevFurthestForImmediateSaveRef.current = 1; }, [activeJobId]);

  // ── Config auto-save to job draft ──
  useEffect(() => {
    if (!configLoaded || !activeJobId) return;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    const timer = window.setTimeout(() => {
      if (j === lastSavedJobConfigJson.current) return;
      void (async () => {
        try {
          await updateJobDraft(activeJobId, { config: payload });
          lastSavedJobConfigJson.current = j;
        } catch { /* only draft writable */ }
      })();
    }, 900);
    return () => window.clearTimeout(timer);
  }, [cfg, mode, activeJobId, configLoaded, furthestStep]);

  useEffect(() => {
    if (!configLoaded || !activeJobId) return;
    const prev = prevFurthestForImmediateSaveRef.current;
    if (furthestStep < 2) { prevFurthestForImmediateSaveRef.current = furthestStep; return; }
    if (furthestStep <= prev) { prevFurthestForImmediateSaveRef.current = furthestStep; return; }
    prevFurthestForImmediateSaveRef.current = furthestStep;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    if (j === lastSavedJobConfigJson.current) return;
    void (async () => {
      try { await updateJobDraft(activeJobId, { config: payload }); lastSavedJobConfigJson.current = j; } catch { /* */ }
    })();
  }, [furthestStep, cfg, mode, activeJobId, configLoaded]);

  useEffect(() => {
    const urlJobId = searchParams.get('jobId');
    if (!activeJobId || furthestStep < 2) return;
    if (activeJobId !== urlJobId) return;
    writeLocalWizardMaxStep(activeJobId, furthestStep);
  }, [activeJobId, furthestStep, searchParams]);

  // ── Blocker for step 4 ──
  const navigationBlocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      step === 4 &&
      (currentLocation.pathname !== nextLocation.pathname ||
        currentLocation.search !== nextLocation.search ||
        currentLocation.hash !== nextLocation.hash),
  );

  useEffect(() => { saveBatchWizardConfig(cfg, mode); }, [cfg, mode]);

  // ── Load config from backend ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [ctRes, pipeRes, presetRes] = await Promise.all([
          fetchWithTimeout('/api/v1/custom-types?enabled_only=true', { timeoutMs: 25000 }),
          fetchWithTimeout('/api/v1/vision-pipelines', { timeoutMs: 25000 }),
          fetchPresets().catch(() => [] as RecognitionPreset[]),
        ]);
        if (!ctRes.ok || !pipeRes.ok) throw new Error('Failed to load config');
        const ctData = await ctRes.json();
        const pipes: PipelineCfg[] = await pipeRes.json();
        if (cancelled) return;
        const types: TextEntityType[] = (ctData.custom_types || []).map((tt: TextEntityType) => ({
          id: tt.id, name: tt.name, color: tt.color,
          regex_pattern: tt.regex_pattern, use_llm: tt.use_llm, order: tt.order,
        }));
        setTextTypes(types);
        setPipelines(pipes);
        setPresets(Array.isArray(presetRes) ? presetRes : []);

        const persisted = loadBatchWizardConfig(mode);
        const defaultTextTypeIds = buildDefaultTextTypeIds(types);
        const defaultOcrHasTypeIds = buildDefaultPipelineTypeIds(pipes, 'ocr_has');
        const defaultHasImageTypeIds = buildDefaultPipelineTypeIds(pipes, 'has_image');
        const ocrIds = pipes.filter(p => p.mode === 'ocr_has' && p.enabled).flatMap(p => p.types.filter(tt => tt.enabled).map(tt => tt.id));
        const hiIds = pipes.filter(p => p.mode === 'has_image' && p.enabled).flatMap(p => p.types.filter(tt => tt.enabled).map(tt => tt.id));

        const presetList: RecognitionPreset[] = Array.isArray(presetRes) ? presetRes : [];
        const selectedEntityTypeIds = persisted?.selectedEntityTypeIds?.length
          ? persisted.selectedEntityTypeIds.filter(id => types.some(tt => tt.id === id))
          : defaultTextTypeIds;
        const ocrHas = persisted?.ocrHasTypes?.length
          ? persisted.ocrHasTypes.filter(id => ocrIds.includes(id))
          : defaultOcrHasTypeIds;
        const hasImg = persisted?.hasImageTypes?.length
          ? persisted.hasImageTypes.filter(id => hiIds.includes(id))
          : defaultHasImageTypeIds;

        let next: BatchWizardPersistedConfig = {
          selectedEntityTypeIds, ocrHasTypes: ocrHas, hasImageTypes: hasImg,
          replacementMode: persisted?.replacementMode ?? 'structured',
          imageRedactionMethod: persisted?.imageRedactionMethod ?? 'mosaic',
          imageRedactionStrength: persisted?.imageRedactionStrength ?? 25,
          imageFillColor: persisted?.imageFillColor ?? '#000000',
          presetTextId: null, presetVisionId: null, presetId: null,
          executionDefault: persisted?.executionDefault === 'local' ? 'local' : 'queue',
        };

        const tid = persisted?.presetTextId ?? persisted?.presetId ?? null;
        const vid = persisted?.presetVisionId ?? persisted?.presetId ?? null;
        const pt = tid ? presetList.find(x => x.id === tid && presetAppliesText(x)) : undefined;
        const pv = vid ? presetList.find(x => x.id === vid && presetAppliesVision(x)) : undefined;
        if (pt) next = { ...next, ...applyTextPresetFields(pt, types), presetTextId: pt.id };
        if (pv) next = { ...next, ...applyVisionPresetFields(pv, pipes), presetVisionId: pv.id };
        if (!pt && persisted === null) {
          const bid = getActivePresetTextId();
          const ptB = bid ? presetList.find(x => x.id === bid && presetAppliesText(x)) : undefined;
          if (ptB) next = { ...next, ...applyTextPresetFields(ptB, types), presetTextId: ptB.id };
        }
        if (!pv && persisted === null) {
          const bid = getActivePresetVisionId();
          const pvB = bid ? presetList.find(x => x.id === bid && presetAppliesVision(x)) : undefined;
          if (pvB) next = { ...next, ...applyVisionPresetFields(pvB, pipes), presetVisionId: pvB.id };
        }
        setCfg(next);
      } catch {
        setMsg({ text: t('batchWizard.waitConfig'), tone: 'err' });
      } finally {
        if (!cancelled) setConfigLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [mode]);

  // ── URL hydration (deep-link restore) ──
  useEffect(() => {
    const jobId = searchParams.get('jobId');
    const itemId = searchParams.get('itemId');
    const stepRaw = searchParams.get('step');
    const _isNew = searchParams.get('new') === '1'; void _isNew;
    const jobItemKey = `${jobId ?? ''}|${itemId ?? ''}`;
    if (urlHydrateKeyRef.current !== jobItemKey) {
      urlHydrateKeyRef.current = jobItemKey;
      hydratedFromUrlRef.current = false;
      prevHydrateUrlStepRef.current = null;
    }
    const stepKey = stepRaw ?? '';
    if (prevHydrateUrlStepRef.current !== null && prevHydrateUrlStepRef.current !== stepKey) {
      if (internalStepNavRef.current) internalStepNavRef.current = false;
      else hydratedFromUrlRef.current = false;
    }
    prevHydrateUrlStepRef.current = stepKey;

    const snUrl = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
    const urlStepParsed = Number.isFinite(snUrl) ? (Math.min(5, Math.max(1, snUrl)) as Step) : null;
    if (hydratedFromUrlRef.current && urlStepParsed !== null && step < urlStepParsed) {
      hydratedFromUrlRef.current = false;
    }

    if (!configLoaded || !jobId || hydratedFromUrlRef.current) return;
    const hydrateGen = ++batchHydrateGenRef.current;

    (async () => {
      try {
        const detail = await getJob(jobId);
        if (hydrateGen !== batchHydrateGenRef.current) return;
        const validTypes: string[] = ['smart_batch', 'text_batch', 'image_batch'];
        if (!validTypes.includes(detail.job_type)) {
          setMsg({ text: 'Job type mismatch', tone: 'warn' });
          return;
        }
        setActiveJobId(jobId);
        const jc = detail.config as Record<string, unknown>;
        const mergedCfg = mergeJobConfigIntoWizardCfg(cfg, jc);
        setCfg(mergedCfg);

        const jobTypeNav = (['smart_batch', 'text_batch', 'image_batch'].includes(detail.job_type) ? detail.job_type : 'smart_batch') as 'smart_batch' | 'text_batch' | 'image_batch';
        const restoredFurthest: Step | null = effectiveWizardFurthestStep({ jobConfig: jc, navHints: detail.nav_hints, jobType: jobTypeNav });

        const persistDraftFingerprint = (furthest: Step) => {
          lastSavedJobConfigJson.current = JSON.stringify(buildJobConfigForWorker(mergedCfg, mode, furthest));
        };

        if (detail.items.length === 0) {
          const sn = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
          const urlStep = Number.isFinite(sn) ? (Math.min(5, Math.max(1, sn)) as Step) : null;
          const sessionMax = readLocalWizardMaxStep(jobId);
          const baseEmpty = urlStep !== null && urlStep >= 2
            ? Math.max(restoredFurthest ?? 1, urlStep)
            : Math.max(restoredFurthest ?? 1, sessionMax ?? 1);
          const rawNext = Math.max(urlStep ?? 1, baseEmpty) as Step;
          const nextStep: Step = rawNext > 3 ? 3 : rawNext;
          itemIdByFileIdRef.current = {};
          setRows([]);
          setSelected(new Set());
          setReviewIndex(0);
          batchGroupIdRef.current = jobId;
          if (nextStep >= 2) setConfirmStep1(true);
          setStep(nextStep);
          const mergedFurthest = Math.max(restoredFurthest ?? 1, nextStep, sessionMax ?? 1) as Step;
          setFurthestStep(prev => Math.max(prev, mergedFurthest) as Step);
          persistDraftFingerprint(mergedFurthest);
          if (detail.status === 'draft') {
            const payload = buildJobConfigForWorker(mergedCfg, mode, mergedFurthest);
            try { await updateJobDraft(jobId, { config: payload }); lastSavedJobConfigJson.current = JSON.stringify(payload); } catch { /* */ }
          }
          if (hydrateGen !== batchHydrateGenRef.current) return;
          hydratedFromUrlRef.current = true;
          return;
        }

        const badItemIdInUrl = Boolean(itemId && !detail.items.some(i => i.id === itemId));
        const item = itemId && !badItemIdInUrl ? detail.items.find(i => i.id === itemId) : detail.items[0];
        if (!item) { setMsg({ text: 'Item not found', tone: 'warn' }); return; }

        const sn0 = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
        const urlStepNum0 = Number.isFinite(sn0) ? (Math.min(5, Math.max(1, sn0)) as Step) : null;
        const sessionMaxItems0 = readLocalWizardMaxStep(jobId);
        const basePersist0 = urlStepNum0 !== null && urlStepNum0 >= 2
          ? Math.max(restoredFurthest ?? 1, urlStepNum0)
          : Math.max(restoredFurthest ?? 1, sessionMaxItems0 ?? 1);
        let resolvedNextStep: Step;
        if (urlStepNum0 !== null) resolvedNextStep = Math.max(urlStepNum0, basePersist0) as Step;
        else if (detail.status === 'draft') resolvedNextStep = Math.min(5, Math.max(2, basePersist0)) as Step;
        else if (detail.status === 'awaiting_review') resolvedNextStep = 4;
        else resolvedNextStep = Math.min(5, Math.max(3, basePersist0)) as Step;

        if (resolvedNextStep >= 2 && resolvedNextStep <= 3) {
          setConfirmStep1(true);
          setStep(resolvedNextStep);
          setFurthestStep(prev => Math.max(prev, restoredFurthest ?? 1, resolvedNextStep) as Step);
          persistDraftFingerprint(Math.max(restoredFurthest ?? 1, resolvedNextStep) as Step);
        }

        const hydratedItems = await Promise.all(
          detail.items.map(async entry => {
            const info = await batchGetFileRaw(entry.file_id);
            return { item: entry, info };
          }),
        );
        if (hydrateGen !== batchHydrateGenRef.current) return;

        const urlMatchIndex = Math.max(0, hydratedItems.findIndex(entry => entry.item.id === item.id));
        const urlMatchHasOutput = Boolean((hydratedItems[urlMatchIndex]?.info || {}).output_path);
        const firstPendingIdx = urlMatchHasOutput
          ? hydratedItems.findIndex(e => !e.info?.output_path && RECOGNITION_DONE_STATUSES.has(mapBackendStatus(e.item.status)))
          : -1;
        const currentIndex = firstPendingIdx >= 0 ? firstPendingIdx : urlMatchIndex;
        const fileIdToItemId = Object.fromEntries(hydratedItems.map(entry => [entry.item.file_id, entry.item.id]));
        const rowsFromJob: BatchRow[] = hydratedItems.map(entry => {
          const rowInfo = entry.info;
          const rowFileTypeRaw = String(rowInfo.file_type ?? entry.item.file_type ?? 'docx').toLowerCase();
          const isScanned = Boolean(rowInfo.is_scanned);
          const rowFileType: FileType =
            rowFileTypeRaw === 'image' || rowFileTypeRaw === 'jpg' || rowFileTypeRaw === 'jpeg' || rowFileTypeRaw === 'png'
              ? FileType.IMAGE
              : rowFileTypeRaw === 'pdf_scanned' || (rowFileTypeRaw === 'pdf' && isScanned)
                ? FileType.PDF_SCANNED
                : rowFileTypeRaw === 'pdf' ? FileType.PDF : FileType.DOCX;
          return {
            file_id: entry.item.file_id,
            original_filename: String(rowInfo.original_filename ?? entry.item.filename ?? entry.item.file_id),
            file_size: Number(rowInfo.file_size ?? 0),
            file_type: rowFileType,
            created_at: String(rowInfo.created_at ?? entry.item.created_at ?? ''),
            has_output: Boolean(rowInfo.output_path ?? entry.item.has_output),
            reviewConfirmed: deriveReviewConfirmed(entry.item),
            entity_count: typeof entry.item.entity_count === 'number' ? entry.item.entity_count : Array.isArray(rowInfo.entities) ? rowInfo.entities.length : 0,
            analyzeStatus: mapBackendStatus(entry.item.status),
            analyzeError: entry.item.status === 'failed' || entry.item.status === 'cancelled' ? (entry.item.error_message || 'Failed') : undefined,
            isImageMode: rowFileType === FileType.IMAGE || rowFileType === FileType.PDF_SCANNED,
          };
        });

        const allRowsReviewConfirmed = rowsFromJob.length > 0 && rowsFromJob.every(row => row.reviewConfirmed === true);
        const anyRecognitionDone = rowsFromJob.some(row => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus));
        let resolvedStepWithGates = resolvedNextStep;
        if (resolvedStepWithGates >= 4 && !anyRecognitionDone) resolvedStepWithGates = 3 as Step;
        if (resolvedStepWithGates === 5 && !allRowsReviewConfirmed) resolvedStepWithGates = 4 as Step;

        itemIdByFileIdRef.current = fileIdToItemId;
        setJobSkipItemReview(Boolean(detail.skip_item_review));
        setRows(rowsFromJob);
        setSelected(new Set(rowsFromJob.map(row => row.file_id)));
        setReviewIndex(currentIndex);
        batchGroupIdRef.current = jobId;
        if (resolvedStepWithGates >= 2) setConfirmStep1(true);
        setStep(resolvedStepWithGates);
        setFurthestStep(prev => Math.max(prev, restoredFurthest ?? 1, resolvedStepWithGates) as Step);
        persistDraftFingerprint(Math.max(restoredFurthest ?? 1, resolvedStepWithGates) as Step);
        hydratedFromUrlRef.current = true;
      } catch (e) {
        if (hydrateGen === batchHydrateGenRef.current) {
          setMsg({ text: e instanceof Error ? e.message : 'Failed to load job', tone: 'err' });
        }
      }
    })();
    return () => { batchHydrateGenRef.current += 1; };
  }, [configLoaded, location.search, mode]);

  // ── Sync step to URL ──
  useEffect(() => {
    const jid = searchParams.get('jobId');
    if (!jid || !activeJobId || jid !== activeJobId) return;
    if (!hydratedFromUrlRef.current) return;
    const cur = searchParams.get('step');
    if (cur === String(step)) return;
    const sp = new URLSearchParams(searchParams);
    sp.set('step', String(step));
    setSearchParams(sp, { replace: true });
  }, [step, activeJobId, searchParams, setSearchParams]);

  // ── Derived values ──
  const textPresets = useMemo(() => presets.filter(presetAppliesText), [presets]);
  const visionPresets = useMemo(() => presets.filter(presetAppliesVision), [presets]);
  const batchDefaultTextTypeIds = useMemo(() => buildDefaultTextTypeIds(textTypes), [textTypes]);
  const batchDefaultOcrHasTypeIds = useMemo(() => buildDefaultPipelineTypeIds(pipelines, 'ocr_has'), [pipelines]);
  const batchDefaultHasImageTypeIds = useMemo(() => buildDefaultPipelineTypeIds(pipelines, 'has_image'), [pipelines]);
  const doneRows = useMemo(() => rows.filter(r => RECOGNITION_DONE_STATUSES.has(r.analyzeStatus)), [rows]);
  const failedRows = useMemo(() => rows.filter(r => r.analyzeStatus === 'failed'), [rows]);
  const reviewFile = doneRows[reviewIndex] ?? null;
  const reviewedOutputCount = useMemo(() => rows.filter(r => r.reviewConfirmed === true).length, [rows]);
  const pendingReviewCount = Math.max(0, rows.length - reviewedOutputCount);
  const allReviewConfirmed = rows.length > 0 && pendingReviewCount === 0;
  const reviewItemId = reviewFile ? itemIdByFileIdRef.current[reviewFile.file_id] : undefined;
  const reviewFileReadOnly = reviewFile?.analyzeStatus === 'completed' || reviewFile?.analyzeStatus === 'redacting';

  const isStep1Complete = useMemo(() => {
    if (!confirmStep1 || !configLoaded) return false;
    const anyTextSelected = cfg.selectedEntityTypeIds.length > 0;
    const anyVisionSelected = cfg.ocrHasTypes.length > 0 || cfg.hasImageTypes.length > 0;
    return anyTextSelected || anyVisionSelected;
  }, [configLoaded, cfg.selectedEntityTypeIds, cfg.ocrHasTypes, cfg.hasImageTypes, confirmStep1]);

  // ── Preset change handlers ──
  const onBatchTextPresetChange = useCallback((id: string) => {
    if (!id) {
      setActivePresetTextId(null);
      setCfg(c => ({ ...c, presetTextId: null, selectedEntityTypeIds: [...batchDefaultTextTypeIds], replacementMode: 'structured' }));
      return;
    }
    const p = presets.find(x => x.id === id);
    if (p && presetAppliesText(p)) {
      setActivePresetTextId(p.id);
      setCfg(c => ({ ...c, ...applyTextPresetFields(p, textTypes), presetTextId: p.id }));
    }
  }, [batchDefaultTextTypeIds, presets, textTypes]);

  const onBatchVisionPresetChange = useCallback((id: string) => {
    if (!id) {
      setActivePresetVisionId(null);
      setCfg(c => ({ ...c, presetVisionId: null, ocrHasTypes: [...batchDefaultOcrHasTypeIds], hasImageTypes: [...batchDefaultHasImageTypeIds] }));
      return;
    }
    const p = presets.find(x => x.id === id);
    if (p && presetAppliesVision(p)) {
      setActivePresetVisionId(p.id);
      setCfg(c => ({ ...c, ...applyVisionPresetFields(p, pipelines), presetVisionId: p.id }));
    }
  }, [batchDefaultOcrHasTypeIds, batchDefaultHasImageTypeIds, presets, pipelines]);

  // ── Review draft management ──
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
      setReviewDraftError(e instanceof Error ? e.message : 'Auto-save failed');
      return false;
    } finally {
      setReviewDraftSaving(false);
    }
  }, [activeJobId, buildCurrentReviewDraftPayload, reviewFile]);

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

  // ── Load review data ──
  useEffect(() => { batchScrollCountersRef.current = {}; }, [reviewFile?.file_id]);

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

  useLayoutEffect(() => {
    if (step !== 4 || !reviewFile) return;
    setReviewLoading(true);
  }, [step, reviewFile?.file_id, reviewFile?.isImageMode]);

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
    [activeJobId, cfg.replacementMode, cfg.selectedEntityTypeIds, textTypes],
  );

  useEffect(() => {
    if (step !== 4 || !reviewFile) return;
    const isImg = reviewFile.isImageMode === true;
    void loadReviewData(reviewFile.file_id, isImg);
  }, [step, reviewFile?.file_id, reviewFile?.isImageMode, loadReviewData]);

  // ── Autosave ──
  useEffect(() => {
    if (step !== 4 || !reviewFile || !reviewDraftInitializedRef.current) return;
    if (!activeJobId || !reviewItemId) return;
    const payload = buildCurrentReviewDraftPayload();
    const json = JSON.stringify(payload);
    if (json === reviewLastSavedJsonRef.current) return;
    reviewDraftDirtyRef.current = true;
    if (reviewAutosaveTimerRef.current !== null) window.clearTimeout(reviewAutosaveTimerRef.current);
    reviewAutosaveTimerRef.current = window.setTimeout(() => { void flushCurrentReviewDraft(); }, 900);
    return () => { if (reviewAutosaveTimerRef.current !== null) { window.clearTimeout(reviewAutosaveTimerRef.current); reviewAutosaveTimerRef.current = null; } };
  }, [step, reviewFile?.file_id, reviewItemId, activeJobId, buildCurrentReviewDraftPayload, flushCurrentReviewDraft]);

  // ── Preview map refresh ──
  useEffect(() => {
    if (step !== 4 || !reviewFile || reviewLoading || reviewFile.isImageMode) return;
    if (!reviewTextContent || reviewEntities.length === 0) { setPreviewEntityMap({}); return; }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const map = await fetchBatchPreviewMap(reviewEntities, cfg.replacementMode);
      if (!cancelled) setPreviewEntityMap(map);
    }, 300);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [step, reviewFile?.file_id, reviewEntities, reviewTextContent, reviewLoading, cfg.replacementMode]);

  // ── Image preview ──
  useEffect(() => {
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
  }, [step, reviewFile?.file_id, reviewBoxes, reviewLoading, cfg.imageRedactionMethod, cfg.imageRedactionStrength, cfg.imageFillColor]);

  const displayPreviewMap = useMemo(() => mergePreviewMapWithDocumentSlices(reviewTextContent, reviewEntities, previewEntityMap), [reviewTextContent, reviewEntities, previewEntityMap]);
  const textPreviewSegments = useMemo(() => buildTextSegments(reviewTextContent, displayPreviewMap), [reviewTextContent, displayPreviewMap]);

  const selectedReviewEntityCount = useMemo(() => reviewEntities.filter(e => e.selected !== false).length, [reviewEntities]);
  const selectedReviewBoxCount = useMemo(() => reviewBoxes.filter(b => b.selected !== false).length, [reviewBoxes]);
  const reviewImagePreviewSrc = useMemo(() => (reviewImagePreview ? `data:image/png;base64,${reviewImagePreview}` : ''), [reviewImagePreview]);

  // ── File upload ──
  const onDrop = useCallback(async (accepted: File[]) => {
    if (!accepted.length) return;
    setLoading(true);
    setMsg(null);
    const uploaded: BatchRow[] = [];
    const failed: string[] = [];
    try {
      if (!batchGroupIdRef.current) {
        batchGroupIdRef.current = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `bg_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
      }
      const bg = batchGroupIdRef.current;
      for (const file of accepted) {
        try {
          const r = await fileApi.upload(file, bg, activeJobId ?? undefined, 'batch');
          const ft = String(r.file_type ?? '').toLowerCase();
          const isImg = ft === 'image' || ft === 'jpg' || ft === 'jpeg' || ft === 'png' || ft === 'pdf_scanned';
          uploaded.push({ file_id: r.file_id, original_filename: r.filename, file_size: r.file_size, file_type: r.file_type, created_at: r.created_at ?? undefined, has_output: false, reviewConfirmed: false, entity_count: 0, analyzeStatus: 'pending', isImageMode: isImg });
        } catch { failed.push(file.name); }
      }
      if (uploaded.length) {
        setRows(prev => [...uploaded, ...prev]);
        setSelected(prev => { const n = new Set(prev); uploaded.forEach(u => n.add(u.file_id)); return n; });
        if (activeJobId) {
          try {
            const d = await getJob(activeJobId);
            const m = { ...itemIdByFileIdRef.current };
            for (const it of d.items) m[it.file_id] = it.id;
            itemIdByFileIdRef.current = m;
          } catch { /* ignore */ }
        }
      }
    } finally { setLoading(false); }
  }, [activeJobId]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, disabled: loading, multiple: true });

  // ── Queue submit ──
  const submitQueueToWorker = useCallback(async () => {
    if (!activeJobId) { setMsg({ text: 'No active job', tone: 'warn' }); return; }
    setMsg(null);
    setRows(prev => prev.map(r => !RECOGNITION_DONE_STATUSES.has(r.analyzeStatus) && r.analyzeStatus !== 'failed' ? { ...r, analyzeStatus: 'pending' as const } : r));
    try {
      const jobCfg = buildJobConfigForWorker(cfg, mode, furthestStep);
      try { await updateJobDraft(activeJobId, { config: jobCfg }); lastSavedJobConfigJson.current = JSON.stringify(jobCfg); } catch { /* */ }
      await apiSubmitJob(activeJobId);
      clearLocalWizardMaxStep(activeJobId);
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : 'Submit failed', tone: 'err' }); }
  }, [activeJobId, cfg, mode, furthestStep]);

  // ── Polling ──
  const hasItemsInProgress = useMemo(() => rows.some(r => r.analyzeStatus === 'pending' || r.analyzeStatus === 'parsing' || r.analyzeStatus === 'analyzing'), [rows]);

  useEffect(() => {
    if (step !== 3 || !activeJobId || !hasItemsInProgress || analyzeRunning) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const detail = await getJob(activeJobId);
        if (cancelled) return;
        const itemMap = new Map(detail.items.map(it => [it.file_id, it]));
        setRows(prev => prev.map(r => {
          const item = itemMap.get(r.file_id);
          if (!item) return r;
          return { ...r, analyzeStatus: mapBackendStatus(item.status), reviewConfirmed: deriveReviewConfirmed(item), has_output: Boolean(item.has_output), isImageMode: r.isImageMode ?? false, analyzeError: item.status === 'failed' || item.status === 'cancelled' ? (item.error_message || 'Failed') : undefined, entity_count: typeof item.entity_count === 'number' ? item.entity_count : r.entity_count };
        }));
      } catch { /* ignore network jitter */ }
    };
    const timer = setInterval(poll, 1000);
    poll();
    return () => { cancelled = true; clearInterval(timer); };
  }, [step, activeJobId, hasItemsInProgress, analyzeRunning]);

  // ── Requeue failed ──
  const requeueFailedItems = useCallback(async () => {
    if (!failedRows.length) return;
    if (activeJobId && cfg.executionDefault !== 'local') {
      setMsg(null);
      try {
        await requeueFailed(activeJobId);
        setRows(prev => prev.map(r => r.analyzeStatus === 'failed' ? { ...r, analyzeStatus: 'pending', analyzeError: undefined } : r));
      } catch { /* fallback handled outside */ }
      return;
    }
  }, [activeJobId, cfg.executionDefault, failedRows.length]);

  // ── Confirm review ──
  const confirmCurrentReview = useCallback(async () => {
    if (!reviewFile) return;
    setReviewExecuteLoading(true);
    setMsg(null);
    const currentFileId = reviewFile.file_id;
    const currentIsImage = reviewFile.isImageMode;
    try {
      const jid = activeJobId;
      const linkedItemId = itemIdByFileIdRef.current[currentFileId];
      if (!jid || !linkedItemId) throw new Error('No linked item');
      const entitiesPayload = reviewEntities.map(e => ({ id: e.id, text: e.text, type: e.type, start: e.start, end: e.end, page: e.page ?? 1, confidence: e.confidence ?? 1, selected: e.selected, source: e.source, coref_id: e.coref_id, replacement: e.replacement }));
      const boxesPayload = reviewBoxes.map(b => ({ id: b.id, x: b.x, y: b.y, width: b.width, height: b.height, page: 1, type: b.type, text: b.text, selected: b.selected, source: b.source, confidence: b.confidence }));

      setRows(prev => prev.map(r => r.file_id === currentFileId ? { ...r, reviewConfirmed: true, has_output: true, analyzeStatus: 'completed' as const } : r));
      const isLastFile = reviewIndex >= doneRows.length - 1;
      if (!isLastFile) setReviewIndex(reviewIndex + 1);

      const ok = await flushCurrentReviewDraft();
      if (!ok) throw new Error(reviewDraftError || 'Auto-save failed');
      const commitResult = await commitItemReview(jid, linkedItemId, { entities: entitiesPayload as Array<Record<string, unknown>>, bounding_boxes: boxesPayload as Array<Record<string, unknown>> });
      const committedStatus = mapBackendStatus(commitResult.status ?? 'completed');
      setRows(prev => prev.map(r => r.file_id === currentFileId ? { ...r, has_output: Boolean(commitResult.has_output ?? true), reviewConfirmed: deriveReviewConfirmed(commitResult), analyzeStatus: committedStatus, entity_count: typeof commitResult.entity_count === 'number' ? commitResult.entity_count : currentIsImage ? boxesPayload.length : entitiesPayload.length } : r));
      reviewLastSavedJsonRef.current = JSON.stringify({ entities: entitiesPayload, bounding_boxes: boxesPayload });
      reviewDraftDirtyRef.current = false;
      if (isLastFile) setFurthestStep(prev => Math.max(prev, 5) as Step);
    } catch (e) {
      setRows(prev => prev.map(r => r.file_id === currentFileId ? { ...r, reviewConfirmed: false, has_output: false, analyzeStatus: 'awaiting_review' as const } : r));
      setMsg({ text: e instanceof Error ? e.message : 'Failed', tone: 'err' });
    } finally { setReviewExecuteLoading(false); }
  }, [activeJobId, doneRows.length, flushCurrentReviewDraft, reviewBoxes, reviewDraftError, reviewEntities, reviewFile, reviewIndex]);

  // ── Download ZIP ──
  const downloadZip = useCallback(async (redacted: boolean) => {
    const selectedIds = rows.filter(r => selected.has(r.file_id)).map(r => r.file_id);
    if (!selectedIds.length) { setMsg({ text: 'No files selected', tone: 'warn' }); return; }
    if (redacted) {
      const noOut = rows.filter(r => selected.has(r.file_id) && !r.has_output);
      if (noOut.length) { setMsg({ text: 'Some files not yet redacted', tone: 'warn' }); return; }
    }
    setZipLoading(true);
    setMsg(null);
    try {
      const blob = await fileApi.batchDownloadZip(selectedIds, redacted);
      triggerDownload(blob, redacted ? 'batch_redacted.zip' : 'batch_original.zip');
      if (redacted && activeJobId) clearLocalWizardMaxStep(activeJobId);
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : 'Download failed', tone: 'err' }); }
    finally { setZipLoading(false); }
  }, [activeJobId, rows, selected]);

  // ── Step navigation ──
  const selectedIds = rows.filter(r => selected.has(r.file_id)).map(r => r.file_id);

  const canGoStep = useCallback((target: Step): boolean => {
    if (target <= 1) return true;
    const allAnalyzeDone = rows.length > 0 && rows.every(r => RECOGNITION_DONE_STATUSES.has(r.analyzeStatus));
    if (target === 4) return allAnalyzeDone;
    if (target < step) return true;
    if (!isStep1Complete && target >= 2) return false;
    if (target === 2) return furthestStep >= 2;
    if (target === 3) return furthestStep >= 2 && rows.length > 0;
    if (target === 5) {
      if (jobSkipItemReview) return furthestStep >= 5 && rows.every(r => r.has_output);
      return furthestStep >= 5 && allReviewConfirmed;
    }
    return false;
  }, [allReviewConfirmed, furthestStep, isStep1Complete, jobSkipItemReview, rows, step]);

  const flushJobDraftFromStep1 = useCallback(async () => {
    if (!activeJobId) return;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    if (j === lastSavedJobConfigJson.current) return;
    try { await updateJobDraft(activeJobId, { config: payload }); lastSavedJobConfigJson.current = j; } catch { /* */ }
  }, [activeJobId, cfg, mode, furthestStep]);

  const applyStep = useCallback((s: Step) => {
    if (s === step) return;
    if (s === 1) setConfirmStep1(false);
    if (s >= 2 && !isStep1Complete) {
      setMsg({ text: !configLoaded ? t('batchWizard.waitConfig') : !confirmStep1 ? t('batchWizard.confirmConfigFirst') : t('batchWizard.selectTypesFirst'), tone: 'warn' });
      return;
    }
    if (!canGoStep(s)) { setMsg({ text: t('batchWizard.stepsOrder'), tone: 'warn' }); return; }
    if (step === 1 && s >= 2 && activeJobId) void flushJobDraftFromStep1();
    internalStepNavRef.current = true;
    setStep(s);
    setFurthestStep(prev => Math.max(prev, s) as Step);
    setMsg(null);
    if (s === 4) {
      const firstPending = doneRows.findIndex(r => !r.has_output);
      setReviewIndex(firstPending >= 0 ? firstPending : 0);
    }
    if (s === 5 && activeJobId) {
      void (async () => {
        try {
          const detail = await getJob(activeJobId);
          const itemMap = new Map(detail.items.map(it => [it.file_id, it]));
          setRows(prev => prev.map(r => { const item = itemMap.get(r.file_id); if (!item) return r; return { ...r, has_output: Boolean(item.has_output), analyzeStatus: mapBackendStatus(item.status), reviewConfirmed: deriveReviewConfirmed(item) }; }));
        } catch { /* ignore */ }
      })();
    }
  }, [activeJobId, canGoStep, configLoaded, confirmStep1, doneRows, flushJobDraftFromStep1, isStep1Complete, step]);

  const goStep = useCallback((s: Step) => {
    if (step === 4 && s !== 5) {
      void (async () => { const ok = await flushCurrentReviewDraft(); if (ok) applyStep(s); })();
      return;
    }
    applyStep(s);
  }, [applyStep, flushCurrentReviewDraft, step]);

  const advanceToUploadStep = useCallback(async () => {
    if (!isStep1Complete) {
      setMsg({ text: !configLoaded ? t('batchWizard.waitConfig') : !confirmStep1 ? t('batchWizard.confirmConfigFirst') : t('batchWizard.selectTypesFirst'), tone: 'warn' });
      return;
    }
    try {
      const nextFurthest = Math.max(furthestStep, 2) as Step;
      const payload = buildJobConfigForWorker(cfg, mode, nextFurthest);
      let jid = activeJobId;
      if (!jid) {
        const j = await createJob({ job_type: 'smart_batch', title: `${t('batchHub.batch')} ${new Date().toLocaleString()}`, config: payload, priority: jobPriority });
        jid = j.id;
        writeLocalWizardMaxStep(jid, nextFurthest);
        setActiveJobId(jid);
      } else {
        writeLocalWizardMaxStep(jid, nextFurthest);
        await updateJobDraft(jid, { config: payload });
      }
      lastSavedJobConfigJson.current = JSON.stringify(payload);
      internalStepNavRef.current = true;
      setStep(2);
      setFurthestStep(prev => Math.max(prev, 2) as Step);
      setMsg(null);
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : 'Failed', tone: 'err' }); }
  }, [activeJobId, cfg, configLoaded, confirmStep1, furthestStep, isStep1Complete, jobPriority, mode]);

  const advanceToExportStep = useCallback(async () => {
    if (!rows.length) { setMsg({ text: 'No files to export', tone: 'warn' }); return; }
    await flushCurrentReviewDraft();
    if (activeJobId) {
      try {
        const detail = await getJob(activeJobId);
        const itemMap = new Map(detail.items.map(it => [it.file_id, it]));
        const backendFileIds = new Set(detail.items.map(it => it.file_id));
        setRows(prev => prev.filter(r => backendFileIds.has(r.file_id)).map(r => { const item = itemMap.get(r.file_id); if (!item) return r; return { ...r, has_output: Boolean(item.has_output), analyzeStatus: mapBackendStatus(item.status), reviewConfirmed: deriveReviewConfirmed(item) }; }));
        const freshConfirmed = detail.items.every(it => deriveReviewConfirmed(it));
        if (!freshConfirmed) { setMsg({ text: 'Not all files confirmed', tone: 'warn' }); return; }
        internalStepNavRef.current = true;
        setStep(5);
        setFurthestStep(prev => Math.max(prev, 5) as Step);
        setMsg(null);
        return;
      } catch { /* fallback */ }
    }
    if (!allReviewConfirmed) { setMsg({ text: 'Not all files confirmed', tone: 'warn' }); return; }
    internalStepNavRef.current = true;
    setStep(5);
    setFurthestStep(prev => Math.max(prev, 5) as Step);
    setMsg(null);
  }, [activeJobId, allReviewConfirmed, flushCurrentReviewDraft, rows.length]);

  const navigateReviewIndex = useCallback(async (nextIndex: number) => {
    if (nextIndex < 0 || nextIndex >= doneRows.length || nextIndex === reviewIndex) return;
    if (reviewLoading) return;
    await flushCurrentReviewDraft();
    setReviewIndex(nextIndex);
  }, [doneRows.length, flushCurrentReviewDraft, reviewIndex, reviewLoading]);

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

  const toggleReviewEntitySelected = useCallback((entityId: string) => {
    applyReviewEntities(prev => prev.map(e => (e.id === entityId ? { ...e, selected: !e.selected } : e)));
  }, [applyReviewEntities]);

  const toggle = useCallback((id: string) => {
    setSelected(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }, []);

  // ── Blocker effects ──
  const showLeaveConfirmModal = leaveConfirmOpen || navigationBlocker.state === 'blocked';

  useEffect(() => {
    if (navigationBlocker.state !== 'blocked') return;
    void (async () => { const ok = await flushCurrentReviewDraft(); if (ok && navigationBlocker.state === 'blocked') navigationBlocker.proceed(); })();
  }, [flushCurrentReviewDraft, navigationBlocker]);

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => { if (step !== 4 || !reviewDraftDirtyRef.current) return; e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [step]);

  useEffect(() => {
    if (step !== 4) return;
    const onPageHide = () => { void flushCurrentReviewDraft(); };
    window.addEventListener('pagehide', onPageHide);
    return () => window.removeEventListener('pagehide', onPageHide);
  }, [flushCurrentReviewDraft, step]);

  return {
    // Identity
    modeValid,
    mode,
    activeJobId,

    // Step
    step,
    furthestStep,
    canGoStep,
    goStep,
    advanceToUploadStep,
    advanceToExportStep,

    // Config
    cfg,
    setCfg,
    configLoaded,
    textTypes,
    pipelines,
    presets,
    textPresets,
    visionPresets,
    confirmStep1,
    setConfirmStep1,
    isStep1Complete,
    jobPriority,
    setJobPriority,
    onBatchTextPresetChange,
    onBatchVisionPresetChange,

    // Files
    rows,
    selected,
    selectedIds,
    loading,
    msg,
    setMsg,
    toggle,

    // Upload
    getRootProps,
    getInputProps,
    isDragActive,

    // Recognition
    submitQueueToWorker,
    requeueFailedItems,
    failedRows,
    doneRows,

    // Review
    reviewIndex,
    reviewFile,
    reviewLoading,
    reviewExecuteLoading,
    reviewEntities,
    reviewBoxes,
    reviewTextContent,
    reviewDraftSaving,
    reviewDraftError,
    reviewFileReadOnly,
    reviewedOutputCount,
    pendingReviewCount,
    allReviewConfirmed,
    reviewImagePreviewSrc,
    reviewImagePreviewLoading,
    reviewOrigImageBlobUrl,
    reviewTextUndoStack,
    reviewTextRedoStack,
    reviewImageUndoStack,
    reviewImageRedoStack,
    selectedReviewEntityCount,
    selectedReviewBoxCount,
    displayPreviewMap,
    textPreviewSegments,
    reviewTextContentRef,
    reviewTextScrollRef,
    navigateReviewIndex,
    confirmCurrentReview,
    applyReviewEntities,
    toggleReviewEntitySelected,
    toggleReviewBoxSelected,
    handleReviewBoxesCommit,
    undoReviewText,
    redoReviewText,
    undoReviewImage,
    redoReviewImage,
    setReviewBoxes,

    // Export
    zipLoading,
    downloadZip,

    // Blocker
    showLeaveConfirmModal,
    navigationBlocker,
  };
}
