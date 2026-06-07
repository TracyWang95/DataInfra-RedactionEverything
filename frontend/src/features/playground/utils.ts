// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { t } from '@/i18n';
import { PLAYGROUND_VISION_PAGE_CONCURRENCY } from '@/constants/timing';
import { authFetch, VISION_TIMEOUT } from '@/services/api-client';
import {
  getSelectionMarkStyle,
  getSelectionToneClasses,
  type SelectionTone,
} from '@/ui/selectionPalette';
import type { BoundingBox, Entity, VisionDetectionResponse } from './types';

export { clampPopoverInCanvas } from '@/utils/domSelection';

export async function safeJson<T = unknown>(res: Response): Promise<T> {
  try {
    return await res.json();
  } catch {
    throw new Error('Non-JSON response from server');
  }
}

export function previewEntityMarkStyle(entity: Entity): React.CSSProperties {
  const tone = sourceToTone(entity.source);
  const base = getSelectionMarkStyle(tone);
  if (!entity.selected) {
    return { ...base, opacity: 0.5, filter: 'saturate(0.55)' };
  }
  return base;
}

export function previewEntityHoverRingClass(source: Entity['source']): string {
  return getSelectionToneClasses(sourceToTone(source)).hoverRing;
}

export function getModePreview(mode: string, sampleEntity?: Entity) {
  const name = sampleEntity?.text || t('editor.sampleName');
  switch (mode) {
    case 'smart':
      return `${name} -> [${t('editor.sampleSmart')}]`;
    case 'mask':
      return `${name} -> ${name[0]}${'*'.repeat(Math.max(name.length - 1, 1))}`;
    case 'structured':
      return `${name} -> <${t('editor.sampleStructured')}>`;
    default:
      return '';
  }
}

export async function authBlobUrl(url: string, mime?: string): Promise<string> {
  const res = await authFetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load file: ${res.status}`);
  }
  const buf = await res.arrayBuffer();
  const blob = mime ? new Blob([buf], { type: mime }) : new Blob([buf]);
  return URL.createObjectURL(blob);
}

export const VISION_FETCH_TIMEOUT_MS = VISION_TIMEOUT;

export async function runVisionDetection(
  fileId: string,
  ocrHasTypes: string[],
  visualFeatureTypes: string[],
  externalSignal?: AbortSignal,
  page = 1,
  force = false,
): Promise<{ boxes: BoundingBox[]; resultImage?: string }> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), VISION_FETCH_TIMEOUT_MS);

  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      window.clearTimeout(timer);
      throw new DOMException('Aborted', 'AbortError');
    }
    externalSignal.addEventListener('abort', onExternalAbort);
  }

  let res: Response;
  try {
    const query = `page=${page}&include_result_image=false${force ? '&force=true' : ''}`;
    res = await authFetch(`/api/v1/redaction/${fileId}/vision?${query}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selected_ocr_has_types: ocrHasTypes,
        selected_visual_feature_types: Array.from(new Set(visualFeatureTypes)),
      }),
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (externalSignal?.aborted) throw error;
      throw new Error(t('error.visionTimeout'));
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener('abort', onExternalAbort);
  }

  if (!res.ok) {
    throw new Error(t('error.visionDetectionFailed'));
  }

  const data = await safeJson<VisionDetectionResponse>(res);
  const boxes = (data.bounding_boxes || []).map(
    (box: Record<string, unknown>, idx: number) =>
      ({
        ...box,
        id: box.id || `bbox_${idx}`,
        selected: true,
      }) as BoundingBox,
  );
  return { boxes, resultImage: data.result_image };
}

export interface VisionPageCompletePayload {
  page: number;
  pageBoxes: BoundingBox[];
  completedPages: number;
  totalPages: number;
  totalBoxes: number;
}

interface RunVisionDetectionPagesOptions {
  fileId: string;
  ocrHasTypes: string[];
  visualFeatureTypes?: string[];
  totalPages: number;
  signal?: AbortSignal;
  concurrency?: number;
  force?: boolean;
  label: string;
  setLoadingMessage?: (message: string) => void;
  onPageComplete?: (payload: VisionPageCompletePayload) => void;
}

export async function runVisionDetectionPages({
  fileId,
  ocrHasTypes,
  visualFeatureTypes = [],
  totalPages,
  signal,
  concurrency = PLAYGROUND_VISION_PAGE_CONCURRENCY,
  force = false,
  label,
  setLoadingMessage,
  onPageComplete,
}: RunVisionDetectionPagesOptions): Promise<{ boxes: BoundingBox[]; totalBoxes: number }> {
  const pages = Array.from({ length: Math.max(1, totalPages) }, (_unused, index) => index + 1);
  const mergedVisualFeatureTypes = Array.from(new Set(visualFeatureTypes));
  const effectiveConcurrency = mergedVisualFeatureTypes.length > 0 ? 1 : concurrency;
  const maxWorkers = Math.max(1, Math.min(effectiveConcurrency, pages.length));
  const boxesByPage = new Map<number, BoundingBox[]>();
  let nextIndex = 0;
  let completedPages = 0;
  let totalBoxes = 0;
  setLoadingMessage?.(`${label} (0/${pages.length})`);

  const runPage = async (page: number) => {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    let result: Awaited<ReturnType<typeof runVisionDetection>> | null = null;
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      try {
        result = await runVisionDetection(
          fileId,
          ocrHasTypes,
          mergedVisualFeatureTypes,
          signal,
          page,
          force,
        );
        break;
      } catch (error) {
        if (signal?.aborted) throw error;
        if (attempt >= 2) throw error;
        setLoadingMessage?.(`${label} (${completedPages}/${pages.length}) retry p.${page}`);
      }
    }
    if (!result) throw new Error(t('playground.recognizeFailed'));
    const pageBoxes = result.boxes.map((box) => ({
      ...box,
      page: Number(box.page || page),
    }));
    boxesByPage.set(page, pageBoxes);
    totalBoxes += pageBoxes.length;
    completedPages += 1;
    setLoadingMessage?.(`${label} (${completedPages}/${pages.length})`);
    onPageComplete?.({
      page,
      pageBoxes,
      completedPages,
      totalPages: pages.length,
      totalBoxes,
    });
  };

  async function worker() {
    while (nextIndex < pages.length) {
      const page = pages[nextIndex];
      nextIndex += 1;
      await runPage(page);
    }
  }

  await Promise.all(Array.from({ length: maxWorkers }, () => worker()));
  const boxes = pages.flatMap((page) => boxesByPage.get(page) ?? []);
  return { boxes, totalBoxes };
}

export function computeEntityStats(
  entities: Entity[],
): Record<string, { total: number; selected: number }> {
  const stats: Record<string, { total: number; selected: number }> = {};
  entities.forEach((entity) => {
    if (!stats[entity.type]) stats[entity.type] = { total: 0, selected: 0 };
    stats[entity.type].total += 1;
    if (entity.selected) stats[entity.type].selected += 1;
  });
  return stats;
}

function sourceToTone(source: Entity['source']): SelectionTone {
  switch (source) {
    case 'regex':
      return 'regex';
    case 'llm':
      return 'semantic';
    case 'manual':
    case 'has':
    default:
      return 'visual';
  }
}
