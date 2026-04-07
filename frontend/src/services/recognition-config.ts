// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { fetchWithTimeout } from '@/utils/fetchWithTimeout';
import { fetchPresets, type RecognitionPreset } from './presetsApi';
import type { EntityTypeConfig as PlaygroundEntityType, PipelineConfig as PlaygroundPipeline } from '@/features/playground/types';

export type RecognitionEntityType = PlaygroundEntityType;
export type RecognitionPipeline = PlaygroundPipeline;

export async function fetchRecognitionEntityTypes(
  enabledOnly: boolean,
  timeoutMs = 3_500,
): Promise<RecognitionEntityType[]> {
  const res = await fetchWithTimeout(
    `/api/v1/custom-types?enabled_only=${enabledOnly}`,
    { timeoutMs },
  );
  if (!res.ok) {
    throw new Error('Failed to load entity types');
  }
  const data = await res.json().catch(() => ({}));
  return Array.isArray(data?.custom_types) ? data.custom_types : [];
}

export async function fetchRecognitionPipelines(timeoutMs = 3_500): Promise<RecognitionPipeline[]> {
  const res = await fetchWithTimeout('/api/v1/vision-pipelines', { timeoutMs });
  if (!res.ok) {
    throw new Error('Failed to load vision pipelines');
  }
  const data = await res.json().catch(() => []);
  return Array.isArray(data) ? data : [];
}

export async function fetchRecognitionPresets(): Promise<RecognitionPreset[]> {
  return fetchPresets();
}
