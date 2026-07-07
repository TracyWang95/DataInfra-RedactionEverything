// Copyright 2026 DataInfra-RedactionEverything Contributors

import type { PipelineTypeConfig } from '../hooks/use-entity-types';

export type PromptRowForm = {
  id: string;
  text: string;
};

export type SampleForm = {
  id: string;
  type: 'positive' | 'negative';
  image: string;
  label: string;
  filename?: string | null;
};

export type PipelineTypeForm = {
  name: string;
  description: string;
  rulesText: string;
  positivePrompts: PromptRowForm[];
  negativePrompts: PromptRowForm[];
  samples: SampleForm[];
};

export const MAX_VisualFeature_SAMPLES = 5;

export function localId() {
  return `local_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

export function emptyPromptRow(text = ''): PromptRowForm {
  return {
    id: localId(),
    text,
  };
}

export function emptyForm(): PipelineTypeForm {
  return {
    name: '',
    description: '',
    rulesText: '',
    positivePrompts: [emptyPromptRow()],
    negativePrompts: [emptyPromptRow()],
    samples: [],
  };
}

export function positivePromptsFromType(type: PipelineTypeConfig): PromptRowForm[] {
  if (type.checklist?.length) {
    const rows = type.checklist
      .map((item) => item.rule ?? item.positive_prompt ?? '')
      .filter(Boolean)
      .map((text) => emptyPromptRow(text));
    if (rows.length) return rows;
  }

  const rows = (type.rules ?? []).filter(Boolean).map((rule) => emptyPromptRow(rule));
  return rows.length ? rows : [emptyPromptRow()];
}

export function negativePromptsFromType(type: PipelineTypeConfig): PromptRowForm[] {
  const rowPrompts = (type.checklist ?? [])
    .map((item) => item.negative_prompt ?? '')
    .filter(Boolean);
  const legacyPrompts = (type.negative_prompt ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  const rows = [...rowPrompts, ...legacyPrompts].map((text) => emptyPromptRow(text));
  return rows.length ? rows : [emptyPromptRow()];
}

export function samplesFromType(type: PipelineTypeConfig): SampleForm[] {
  return (type.few_shot_samples ?? []).map((sample) => ({
    id: localId(),
    type: sample.type === 'negative' ? 'negative' : 'positive',
    image: sample.image,
    label: sample.label ?? '',
    filename: sample.filename ?? null,
  }));
}

export function readImageAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
