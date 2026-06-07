// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type {
  ParseResult,
  NERResult,
  VisionResult,
  RedactionResult,
  RedactionRequest,
} from '../types';
import { get, post, BATCH_TIMEOUT } from './api-client';

export async function batchParse(fileId: string, signal?: AbortSignal): Promise<ParseResult> {
  return get<ParseResult>(`/files/${fileId}/parse`, { signal, timeout: BATCH_TIMEOUT });
}

export async function batchHybridNer(
  fileId: string,
  body: { entity_type_ids: string[] },
  signal?: AbortSignal,
): Promise<NERResult> {
  return post<NERResult>(`/files/${fileId}/ner/hybrid`, body, { signal, timeout: BATCH_TIMEOUT });
}

export async function batchVision(
  fileId: string,
  page: number,
  selectedOcrHasTypes: string[],
  selectedVisualFeatureTypes: string[],
  signal?: AbortSignal,
): Promise<VisionResult> {
  return post<VisionResult>(
    `/redaction/${fileId}/vision?page=${page}&include_result_image=false`,
    {
      selected_ocr_has_types: selectedOcrHasTypes,
      selected_visual_feature_types: Array.from(new Set(selectedVisualFeatureTypes)),
    },
    {
      signal,
      timeout: BATCH_TIMEOUT,
    },
  );
}

export async function batchGetFileRaw(fileId: string): Promise<Record<string, unknown>> {
  return get<Record<string, unknown>>(`/files/${fileId}`);
}

export async function batchExecute(request: RedactionRequest): Promise<RedactionResult> {
  return post<RedactionResult>('/redaction/execute', request, { timeout: BATCH_TIMEOUT });
}

export async function batchPreviewEntityMap(body: {
  entities: unknown[];
  config: Record<string, unknown>;
}): Promise<Record<string, string>> {
  const data = await post<{ entity_map?: Record<string, string> }>('/redaction/preview-map', body);
  return data.entity_map ?? {};
}

export async function batchPreviewImage(body: {
  file_id: string;
  page?: number;
  bounding_boxes: unknown[];
  config: Record<string, unknown>;
}): Promise<string> {
  const page = body.page ?? 1;
  const data = await post<{ image_base64?: string }>(
    `/redaction/${encodeURIComponent(body.file_id)}/preview-image?page=${page}`,
    {
      bounding_boxes: body.bounding_boxes,
      config: body.config,
    },
  );
  return data.image_base64 ?? '';
}

export function flattenBoundingBoxesFromStore(raw: unknown): Array<Record<string, unknown>> {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as Array<Record<string, unknown>>;
  if (typeof raw === 'object') {
    const out: Array<Record<string, unknown>> = [];
    for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
      const pageNum = Number(key) || 1;
      const pageBoxes = Array.isArray(value) ? value : [];
      for (const box of pageBoxes) {
        if (box && typeof box === 'object') {
          out.push({ ...(box as object), page: (box as { page?: number }).page ?? pageNum });
        }
      }
    }
    return out;
  }
  return [];
}

export type BatchWizardMode = 'text' | 'image' | 'smart';

const LEGACY_BATCH_WIZARD_KEY = 'batchWizard:config:v1';

export function batchWizardStorageKey(mode: BatchWizardMode): string {
  if (mode === 'image') return 'batchWizard:config:v3:image';
  if (mode === 'smart') return 'batchWizard:config:v3:smart';
  return `batchWizard:config:v3:${mode}`;
}

export interface BatchWizardPersistedConfig {
  selectedEntityTypeIds: string[];
  ocrHasTypes: string[];
  visualFeatureTypes: string[];
  replacementMode: 'structured' | 'smart' | 'mask';
  imageRedactionMethod?: 'mosaic' | 'blur' | 'fill';
  imageRedactionStrength?: number;
  imageFillColor?: string;
  presetTextId?: string | null;
  presetVisionId?: string | null;
  executionDefault?: 'queue' | 'local';
}

export function loadBatchWizardConfig(
  mode: BatchWizardMode = 'text',
): BatchWizardPersistedConfig | null {
  try {
    const key = batchWizardStorageKey(mode);
    let rawJson = sessionStorage.getItem(key);
    if (!rawJson && mode === 'text') {
      rawJson = sessionStorage.getItem(LEGACY_BATCH_WIZARD_KEY);
      if (rawJson) {
        try {
          sessionStorage.setItem(key, rawJson);
          sessionStorage.removeItem(LEGACY_BATCH_WIZARD_KEY);
        } catch {
          /* ignore */
        }
      }
    }
    if (!rawJson) return null;
    const raw = JSON.parse(rawJson) as Record<string, unknown>;
    const base = raw as unknown as BatchWizardPersistedConfig;
    const legacyPresetId = (raw.presetId as string | null | undefined) ?? null;
    return {
      ...base,
      selectedEntityTypeIds: Array.isArray(raw.selectedEntityTypeIds)
        ? (raw.selectedEntityTypeIds as string[])
        : [],
      ocrHasTypes: Array.isArray(raw.ocrHasTypes) ? (raw.ocrHasTypes as string[]) : [],
      visualFeatureTypes: Array.isArray(raw.visualFeatureTypes)
        ? (raw.visualFeatureTypes as string[])
        : [],
      replacementMode:
        raw.replacementMode === 'smart' || raw.replacementMode === 'mask'
          ? raw.replacementMode
          : 'structured',
      presetTextId:
        (raw.presetTextId as string | null | undefined) ?? legacyPresetId ?? base.presetTextId ?? null,
      presetVisionId:
        (raw.presetVisionId as string | null | undefined) ??
        legacyPresetId ??
        base.presetVisionId ??
        null,
      executionDefault: raw.executionDefault === 'local' ? 'local' : 'queue',
    };
  } catch {
    return null;
  }
}

export function saveBatchWizardConfig(
  config: BatchWizardPersistedConfig,
  mode: BatchWizardMode = 'text',
): void {
  try {
    sessionStorage.setItem(batchWizardStorageKey(mode), JSON.stringify(config));
  } catch {
    /* ignore */
  }
}
