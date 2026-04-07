// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { ReplacementMode } from '@/types';
import {
  batchPreviewEntityMap,
  type BatchWizardMode,
  type BatchWizardPersistedConfig,
} from '@/services/batchPipeline';
import type { RecognitionPreset } from '@/services/presetsApi';
import {
  effectiveWizardFurthestStep,
  parseWizardFurthestFromUnknown,
} from '@/utils/jobPrimaryNavigation';
import { buildFallbackPreviewEntityMap } from '@/utils/textRedactionSegments';

import type {
  BatchRow,
  PipelineCfg,
  ReviewEntity,
  Step,
  TextEntityType,
} from '../types';

// ── Pure helpers ──

export function isBatchWizardMode(value: string | null | undefined): value is BatchWizardMode {
  return value === 'text' || value === 'image' || value === 'smart';
}

export function toBatchJobType(mode: BatchWizardMode): 'text_batch' | 'image_batch' | 'smart_batch' {
  if (mode === 'text') return 'text_batch';
  if (mode === 'image') return 'image_batch';
  return 'smart_batch';
}

export function mapBackendStatus(status: string): BatchRow['analyzeStatus'] {
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

export function deriveReviewConfirmed(item: { status: string; has_output?: boolean | null }): boolean {
  if (item.status === 'completed') return item.has_output !== false;
  return item.status === 'review_approved' || item.status === 'redacting';
}

export function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function defaultConfig(): BatchWizardPersistedConfig {
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

export function normalizeReviewEntity(e: ReviewEntity): ReviewEntity {
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

export function buildJobConfigForWorker(
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

export function mergeJobConfigIntoWizardCfg(
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

// ── Local-storage furthest-step tracking ──

const BATCH_WIZ_FURTHEST_LS_PREFIX = 'lr_batch_wiz_furthest_';

export function readLocalWizardMaxStep(jobId: string): Step | null {
  try {
    const v = localStorage.getItem(BATCH_WIZ_FURTHEST_LS_PREFIX + jobId);
    return parseWizardFurthestFromUnknown(v);
  } catch {
    return null;
  }
}

export function writeLocalWizardMaxStep(jobId: string, step: Step) {
  try {
    const prev = readLocalWizardMaxStep(jobId);
    const merged = Math.max(step, prev ?? 1) as Step;
    if (merged >= 2) localStorage.setItem(BATCH_WIZ_FURTHEST_LS_PREFIX + jobId, String(merged));
  } catch {
    return;
  }
}

export function clearLocalWizardMaxStep(jobId: string) {
  try {
    localStorage.removeItem(BATCH_WIZ_FURTHEST_LS_PREFIX + jobId);
  } catch {
    return;
  }
}

// ── Preset application ──

export function applyTextPresetFields(
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

export function applyVisionPresetFields(
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

// ── Preview entity map fetch ──

export async function fetchBatchPreviewMap(
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
    return buildFallbackPreviewEntityMap(
      payload.map((item) => ({ text: item.text, type: item.type, selected: item.selected })),
      modeKey,
    );
  }
  return buildFallbackPreviewEntityMap(
    payload.map(p => ({ text: p.text, type: p.type, selected: p.selected })),
    modeKey,
  );
}

// Re-export types that sub-hooks need from effectiveWizardFurthestStep
export { effectiveWizardFurthestStep };
