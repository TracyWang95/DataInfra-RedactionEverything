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

export type PipelineMode = 'ocr_has' | 'visual_features';

export function normalizeVisualTypeId(id: string): string {
  return id.trim().toLowerCase().replace(/-/g, '_');
}

function enabledIds<T extends { id: string; enabled?: boolean }>(items: T[]): string[] {
  return items.filter((item) => item.enabled !== false).map((item) => item.id);
}

export function isBuiltinDefaultTextType(type: DefaultTextTypeLike): boolean {
  return type.enabled !== false && type.default_enabled === true;
}

export function buildDefaultTextTypeIds<T extends DefaultTextTypeLike>(types: T[]): string[] {
  return types.filter(isBuiltinDefaultTextType).map((type) => type.id);
}

export function isBuiltinDefaultPipelineType(type: DefaultPipelineTypeLike): boolean {
  return type.enabled !== false && type.default_enabled === true;
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
      pipeline.types.filter(isBuiltinDefaultPipelineType).map((type) => type.id),
    );
  if (builtinIds.length > 0) {
    return builtinIds;
  }
  if (mode === 'visual_features') {
    return builtinIds;
  }
  return pipelines
    .filter((pipeline) => pipeline.mode === mode && pipeline.enabled)
    .flatMap((pipeline) => enabledIds(pipeline.types));
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
