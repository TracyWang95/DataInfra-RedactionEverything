// Copyright 2026 DataInfra-RedactionEverything Contributors

export interface DefaultTextTypeLike {
  id: string;
  enabled?: boolean;
  default_enabled?: boolean;
  generic_target?: string | null;
  order?: number;
}

export interface DefaultPipelineTypeLike {
  id: string;
  enabled?: boolean;
  default_enabled?: boolean;
  order?: number;
}

export interface DefaultPipelineLike<T extends DefaultPipelineTypeLike = DefaultPipelineTypeLike> {
  mode: PipelineMode;
  enabled: boolean;
  types: T[];
}

export interface DefaultPipelineCoverage {
  selectedIds: string[];
  excludedIds: string[];
  enabledIds: string[];
}

const DEFAULT_EXCLUDED_TEXT_TYPE_IDS = new Set<string>();
export type PipelineMode = 'ocr_has' | 'visual_features';

const DEFAULT_EXCLUDED_PIPELINE_TYPE_IDS: Record<PipelineMode, ReadonlySet<string>> = {
  ocr_has: new Set(),
  visual_features: new Set(),
};

export function normalizeVisualTypeId(id: string): string {
  const normalized = id.trim().toLowerCase().replace(/-/g, '_');
  const aliases: Record<string, string> = {
    receipt_region: 'receipt',
    portrait_face: 'face',
    stamp_region: 'official_seal',
  };
  return aliases[normalized] ?? normalized;
}

function enabledIds<T extends { id: string; enabled?: boolean }>(items: T[]): string[] {
  return items.filter((item) => item.enabled !== false).map((item) => item.id);
}

function normalizeTextTypeId(id: string): string {
  return id.trim().toUpperCase().replace(/[- /]/g, '_');
}

export function isDefaultExcludedTextTypeId(id: string): boolean {
  const normalized = normalizeTextTypeId(id);
  return DEFAULT_EXCLUDED_TEXT_TYPE_IDS.has(normalized);
}

export function isBuiltinDefaultTextType(type: DefaultTextTypeLike): boolean {
  return (
    type.enabled !== false &&
    type.default_enabled === true &&
    !isDefaultExcludedTextTypeId(type.id)
  );
}

export function buildDefaultTextTypeIds<T extends DefaultTextTypeLike>(types: T[]): string[] {
  return types.filter(isBuiltinDefaultTextType).map((type) => type.id);
}

export function isBuiltinDefaultPipelineType(type: DefaultPipelineTypeLike): boolean {
  return type.enabled !== false && type.default_enabled === true;
}

export function isDefaultExcludedPipelineTypeId(
  mode: PipelineMode,
  id: string,
): boolean {
  if (mode === 'ocr_has' && isDefaultExcludedTextTypeId(id)) return true;
  return DEFAULT_EXCLUDED_PIPELINE_TYPE_IDS[mode].has(id);
}

function isDefaultPipelineType(
  type: DefaultPipelineTypeLike,
  mode: PipelineMode,
): boolean {
  return isBuiltinDefaultPipelineType(type) && !isDefaultExcludedPipelineTypeId(mode, type.id);
}

function enabledDefaultPipelineIds<T extends DefaultPipelineTypeLike>(
  items: T[],
  mode: PipelineMode,
): string[] {
  return enabledIds(items).filter((id) => !isDefaultExcludedPipelineTypeId(mode, id));
}

function isPipelineTypeVisibleInConfig(
  type: DefaultPipelineTypeLike,
  _mode: PipelineMode,
): boolean {
  if (type.enabled === false) return false;
  return true;
}

export function buildDefaultPipelineTypeIds<T extends DefaultPipelineTypeLike>(
  pipelines: DefaultPipelineLike<T>[],
  mode: PipelineMode,
): string[] {
  const builtinIds = pipelines
    .filter((pipeline) => pipeline.mode === mode && pipeline.enabled)
    .flatMap((pipeline) =>
      pipeline.types.filter((type) => isDefaultPipelineType(type, mode)).map((type) => type.id),
    );
  if (builtinIds.length > 0) {
    return builtinIds;
  }
  if (mode === 'visual_features') {
    return builtinIds;
  }
  return pipelines
    .filter((pipeline) => pipeline.mode === mode && pipeline.enabled)
    .flatMap((pipeline) => enabledDefaultPipelineIds(pipeline.types, mode));
}

export function buildDefaultPipelineCoverage<T extends DefaultPipelineTypeLike>(
  pipelines: DefaultPipelineLike<T>[],
  mode: PipelineMode,
): DefaultPipelineCoverage {
  const visibleTypes = pipelines
    .filter((pipeline) => pipeline.mode === mode && pipeline.enabled)
    .flatMap((pipeline) =>
      pipeline.types.filter((type) => isPipelineTypeVisibleInConfig(type, mode)),
    );
  const enabledIdList = visibleTypes.map((type) => type.id);
  const selectedIds = buildDefaultPipelineTypeIds(pipelines, mode);
  const selected = new Set(selectedIds);
  return {
    selectedIds,
    excludedIds: enabledIdList.filter((id) => !selected.has(id)),
    enabledIds: enabledIdList,
  };
}
