// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

export interface DefaultTextTypeLike {
  id: string;
  enabled?: boolean;
  order?: number;
}

export interface DefaultPipelineTypeLike {
  id: string;
  enabled?: boolean;
  order?: number;
}

export interface DefaultPipelineLike<T extends DefaultPipelineTypeLike = DefaultPipelineTypeLike> {
  mode: 'ocr_has' | 'has_image';
  enabled: boolean;
  types: T[];
}

const TEXT_CUSTOM_ID_PREFIX = 'custom_';
const BUILTIN_TEXT_ORDER_LIMIT = 200;
const BUILTIN_PIPELINE_ORDER_LIMIT = 100;

function enabledIds<T extends { id: string; enabled?: boolean }>(items: T[]): string[] {
  return items.filter(item => item.enabled !== false).map(item => item.id);
}

export function isBuiltinDefaultTextType(type: DefaultTextTypeLike): boolean {
  if (type.enabled === false) return false;
  if (type.id.startsWith(TEXT_CUSTOM_ID_PREFIX)) return false;
  return typeof type.order !== 'number' || type.order < BUILTIN_TEXT_ORDER_LIMIT;
}

export function buildDefaultTextTypeIds<T extends DefaultTextTypeLike>(types: T[]): string[] {
  const builtinIds = types.filter(isBuiltinDefaultTextType).map(type => type.id);
  return builtinIds.length > 0 ? builtinIds : enabledIds(types);
}

export function isBuiltinDefaultPipelineType(type: DefaultPipelineTypeLike): boolean {
  if (type.enabled === false) return false;
  return typeof type.order !== 'number' || type.order < BUILTIN_PIPELINE_ORDER_LIMIT;
}

export function buildDefaultPipelineTypeIds<T extends DefaultPipelineTypeLike>(
  pipelines: DefaultPipelineLike<T>[],
  mode: 'ocr_has' | 'has_image'
): string[] {
  const builtinIds = pipelines
    .filter(pipeline => pipeline.mode === mode && pipeline.enabled)
    .flatMap(pipeline =>
      pipeline.types.filter(isBuiltinDefaultPipelineType).map(type => type.id)
    );
  if (builtinIds.length > 0) {
    return builtinIds;
  }
  return pipelines
    .filter(pipeline => pipeline.mode === mode && pipeline.enabled)
    .flatMap(pipeline => enabledIds(pipeline.types));
}
