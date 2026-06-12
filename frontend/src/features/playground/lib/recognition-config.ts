// Copyright 2026 DataInfra-RedactionEverything Contributors

import { t } from '@/i18n';
import { getScopedStorageItem, setScopedStorageItem } from '@/lib/storage';
import { buildDefaultPipelineTypeIds } from '@/services/defaultRedactionPreset';
import type { SelectionTone } from '@/ui/selectionPalette';
import type { EntityTypeConfig, PipelineConfig, VisionTypeConfig } from '../types';

export type ConfigLoadState = 'loading' | 'ready' | 'empty' | 'unavailable';
export type PlaygroundTextGroupKey = 'regex' | 'semantic';

export interface PlaygroundTextGroup {
  key: PlaygroundTextGroupKey;
  label: string;
  tone: SelectionTone;
  types: EntityTypeConfig[];
}

const entityNameCollator = new Intl.Collator('zh-Hans-CN', {
  numeric: true,
  sensitivity: 'base',
});

const RECOGNITION_CONFIG_CACHE_VERSION = 1;
const RECOGNITION_CONFIG_CACHE_TTL_MS = 10 * 60 * 1000;
const RECOGNITION_CONFIG_CACHE_KEY = 'datainfraRedaction:recognitionConfigCache';

type CachedConfigPayload = {
  version: number;
  savedAt: number;
  entityTypes: EntityTypeConfig[];
  pipelines: PipelineConfig[];
};

const isObject = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const isRecognitionPayload = (value: unknown): value is CachedConfigPayload => {
  if (!isObject(value)) return false;
  if (value.version !== RECOGNITION_CONFIG_CACHE_VERSION) return false;
  if (typeof value.savedAt !== 'number' || value.savedAt <= 0) return false;
  if (!Array.isArray(value.entityTypes) || !Array.isArray(value.pipelines)) return false;
  return true;
};

export interface CachedRecognitionConfig {
  entityTypes: EntityTypeConfig[];
  pipelines: PipelineConfig[];
}

export function getCachedRecognitionConfig(ownerId?: string | null): CachedRecognitionConfig | null {
  const cached = getScopedStorageItem<unknown>(RECOGNITION_CONFIG_CACHE_KEY, null, ownerId);
  if (!isRecognitionPayload(cached)) return null;

  if (Date.now() - cached.savedAt > RECOGNITION_CONFIG_CACHE_TTL_MS) {
    return null;
  }

  return {
    entityTypes: cached.entityTypes,
    pipelines: cached.pipelines,
  };
}

export function updateRecognitionConfigCache(
  payload: Partial<CachedRecognitionConfig>,
  ownerId?: string | null,
): void {
  const cached = getCachedRecognitionConfig(ownerId);
  setScopedStorageItem(RECOGNITION_CONFIG_CACHE_KEY, {
    version: RECOGNITION_CONFIG_CACHE_VERSION,
    savedAt: Date.now(),
    entityTypes: payload.entityTypes ?? cached?.entityTypes ?? [],
    pipelines: payload.pipelines ?? cached?.pipelines ?? [],
  }, ownerId);
}

export function buildVisionSelectionSignature(pipelines: PipelineConfig[]): string {
  return JSON.stringify({
    ocrHas: buildDefaultPipelineTypeIds(pipelines, 'ocr_has'),
    visualFeatures: buildDefaultPipelineTypeIds(pipelines, 'visual_features'),
  });
}

export function sortEntityTypes(types: EntityTypeConfig[]): EntityTypeConfig[] {
  return [...types].sort((left, right) => {
    const leftRegex = left.regex_pattern ? 1 : 0;
    const rightRegex = right.regex_pattern ? 1 : 0;
    if (leftRegex !== rightRegex) return leftRegex - rightRegex;
    return entityNameCollator.compare(left.name, right.name);
  });
}

export function buildPlaygroundTextGroups(types: EntityTypeConfig[]): PlaygroundTextGroup[] {
  const regexTypes = types.filter((type) => Boolean(type.regex_pattern));
  const semanticTypes = types.filter((type) => !type.regex_pattern);

  return [
    {
      key: 'semantic',
      label: t('playground.group.semantic'),
      tone: 'semantic',
      types: semanticTypes,
    },
    {
      key: 'regex',
      label: t('playground.group.regex'),
      tone: 'regex',
      types: regexTypes,
    },
  ];
}

export function normalizeVisionPipelines(pipelines: PipelineConfig[]): PipelineConfig[] {
  const normalized = pipelines
    .filter((pipeline) => pipeline.enabled)
    .map((pipeline) => ({
      ...pipeline,
      name:
        pipeline.mode === 'visual_features'
          ? t('settings.pipelineDisplayName.image')
          : pipeline.mode === 'ocr_has'
            ? t('settings.pipelineDisplayName.ocr')
            : pipeline.name,
      description:
        pipeline.mode === 'visual_features'
          ? t('settings.pipelineDescription.image')
          : pipeline.mode === 'ocr_has'
            ? t('settings.pipelineDescription.ocr')
          : pipeline.description,
      types: pipeline.types.filter((type) => type.enabled !== false),
    }));
  const byMode = new Map<string, PipelineConfig>();
  for (const pipeline of normalized) {
    const existing = byMode.get(pipeline.mode);
    if (!existing) {
      byMode.set(pipeline.mode, pipeline);
      continue;
    }
    byMode.set(pipeline.mode, {
      ...existing,
      enabled: existing.enabled || pipeline.enabled,
      types: [...existing.types, ...pipeline.types],
    });
  }
  return Array.from(byMode.values());
}

export function flattenVisionTypes(pipelines: PipelineConfig[]): VisionTypeConfig[] {
  return pipelines.flatMap((pipeline) => pipeline.types);
}
