// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { get, post, put, del } from './api-client';

export type ReplacementMode = 'structured' | 'smart' | 'mask';


export type PresetKind = 'text' | 'vision' | 'full';

export interface RecognitionPreset {
  id: string;
  name: string;
  
  kind?: PresetKind;
  selectedEntityTypeIds: string[];
  ocrHasTypes: string[];
  hasImageTypes: string[];
  replacementMode: ReplacementMode;
  created_at: string;
  updated_at: string;
}

export interface PresetPayload {
  name: string;
  kind: PresetKind;
  selectedEntityTypeIds: string[];
  ocrHasTypes: string[];
  hasImageTypes: string[];
  replacementMode: ReplacementMode;
}


export function presetAppliesText(p: RecognitionPreset): boolean {
  const k = p.kind ?? 'full';
  return k === 'text' || k === 'full';
}


export function presetAppliesVision(p: RecognitionPreset): boolean {
  const k = p.kind ?? 'full';
  return k === 'vision' || k === 'full';
}

export async function fetchPresets(): Promise<RecognitionPreset[]> {
  const data = await get<any>('/presets');
  
  return Array.isArray(data) ? data : Array.isArray(data?.presets) ? data.presets : [];
}

export async function createPreset(body: PresetPayload): Promise<RecognitionPreset> {
  return post<RecognitionPreset>('/presets', body);
}

export async function updatePreset(id: string, patch: Partial<PresetPayload>): Promise<RecognitionPreset> {
  return put<RecognitionPreset>(`/presets/${id}`, patch);
}

export async function deletePreset(id: string): Promise<void> {
  return del(`/presets/${id}`);
}
