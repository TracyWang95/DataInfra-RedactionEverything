// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { t } from '@/i18n';
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

export function sortEntityTypes(types: EntityTypeConfig[]): EntityTypeConfig[] {
  return [...types].sort((left, right) => {
    const leftRegex = left.regex_pattern ? 1 : 0;
    const rightRegex = right.regex_pattern ? 1 : 0;
    if (leftRegex !== rightRegex) return rightRegex - leftRegex;
    return entityNameCollator.compare(left.name, right.name);
  });
}

export function buildPlaygroundTextGroups(types: EntityTypeConfig[]): PlaygroundTextGroup[] {
  const regexTypes = types.filter(type => Boolean(type.regex_pattern));
  const semanticTypes = types.filter(type => !type.regex_pattern);

  const groups: PlaygroundTextGroup[] = [
    {
      key: 'regex',
      label: t('playground.group.regex'),
      tone: 'regex',
      types: regexTypes,
    },
    {
      key: 'semantic',
      label: t('playground.group.semantic'),
      tone: 'semantic',
      types: semanticTypes,
    },
  ];

  return groups.filter(group => group.types.length > 0);
}

export function normalizeVisionPipelines(pipelines: PipelineConfig[]): PipelineConfig[] {
  return pipelines
    .filter(pipeline => pipeline.enabled)
    .map(pipeline => ({
      ...pipeline,
      name: pipeline.mode === 'has_image'
        ? t('settings.pipelineDisplayName.image')
        : pipeline.name,
      description: pipeline.mode === 'has_image'
        ? t('settings.pipelineDescription.image')
        : pipeline.description,
      types: pipeline.types.filter(type => type.enabled),
    }))
    .filter(pipeline => pipeline.types.length > 0);
}

export function flattenVisionTypes(pipelines: PipelineConfig[]): VisionTypeConfig[] {
  return pipelines.flatMap(pipeline => pipeline.types);
}
