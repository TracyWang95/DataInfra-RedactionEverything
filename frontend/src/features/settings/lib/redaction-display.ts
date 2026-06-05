// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { normalizeEntityTypeId } from '@/config/entityTypes';
import { normalizeVisualTypeId } from '@/services/defaultRedactionPreset';
import type { RecognitionPreset } from '@/services/presetsApi';

type Translate = (key: string) => string;

export interface TypeDisplayLike {
  id: string;
  name?: string;
}

function translateIfPresent(t: Translate, key: string): string | null {
  const translated = t(key);
  return translated === key ? null : translated;
}

function prettifyTypeId(typeId: string): string {
  return typeId
    .trim()
    .replace(/[-_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function localizePresetName(preset: RecognitionPreset, t: Translate): string {
  const localized = translateIfPresent(t, `settings.redaction.presetName.${preset.id}`);
  return localized ?? preset.name;
}

export function localizeRecognitionTypeName(type: TypeDisplayLike, t: Translate): string {
  if (type.id.startsWith('custom_')) {
    return type.name?.trim() || type.id;
  }

  const candidates = [
    type.id,
    normalizeEntityTypeId(type.id),
    normalizeVisualTypeId(type.id),
    normalizeVisualTypeId(normalizeEntityTypeId(type.id)),
  ];

  for (const candidate of candidates) {
    const localized = translateIfPresent(t, `entity.${candidate}`);
    if (localized) return localized;
  }

  return type.name?.trim() || prettifyTypeId(type.id);
}

export function localizePipelineConfig<
  T extends TypeDisplayLike,
  P extends { mode: string; name: string; description?: string; types: T[] },
>(pipeline: P, t: Translate): P {
  const nameKey =
    pipeline.mode === 'ocr_has'
      ? 'settings.pipelineDisplayName.ocr'
      : pipeline.mode === 'visual_features'
        ? 'settings.pipelineDisplayName.image'
        : null;
  const descriptionKey =
    pipeline.mode === 'ocr_has'
      ? 'settings.pipelineDescription.ocr'
      : pipeline.mode === 'visual_features'
        ? 'settings.pipelineDescription.image'
        : null;

  return {
    ...pipeline,
    name: nameKey ? (translateIfPresent(t, nameKey) ?? pipeline.name) : pipeline.name,
    description: descriptionKey
      ? (translateIfPresent(t, descriptionKey) ?? pipeline.description)
      : pipeline.description,
    types: pipeline.types.map((type) => ({
      ...type,
      name: localizeRecognitionTypeName(type, t),
    })),
  };
}
