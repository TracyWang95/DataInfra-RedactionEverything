// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { authFetch } from '@/services/api-client';
import { fetchWithTimeout } from '@/utils/fetchWithTimeout';
import { showToast } from '@/components/Toast';
import { t } from '@/i18n';
import { selectionToneHex, type SelectionTone } from '@/ui/selectionPalette';
import type { PipelineMode } from '@/services/defaultRedactionPreset';
import {
  fetchRecognitionEntityTypes,
  fetchRecognitionPipelines,
} from '@/services/recognition-config';

export interface EntityTypeConfig {
  id: string;
  name: string;
  data_domain?: string;
  generic_target?: string | null;
  entity_type_ids?: string[];
  linkage_groups?: string[];
  coref_enabled?: boolean;
  default_enabled?: boolean;
  description?: string;
  examples?: string[];
  color: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  enabled?: boolean;
  order?: number;
  tag_template?: string | null;
}

export interface TextTaxonomyTarget {
  value: string;
  label: string;
}

export interface TextTaxonomyDomain {
  value: string;
  label: string;
  default_target: string;
  targets: TextTaxonomyTarget[];
}

export interface PipelineTypeConfig {
  id: string;
  name: string;
  data_domain?: string;
  generic_target?: string | null;
  entity_type_ids?: string[];
  linkage_groups?: string[];
  coref_enabled?: boolean;
  default_enabled?: boolean;
  description?: string;
  examples?: string[];
  color: string;
  enabled: boolean;
  order: number;
  rules?: string[];
  checklist?: VisualFeatureChecklistItem[];
  negative_prompt_enabled?: boolean;
  negative_prompt?: string | null;
  few_shot_enabled?: boolean;
  few_shot_samples?: VisualFeatureFewShotSample[];
}

export interface VisualFeatureChecklistItem {
  rule: string;
  positive_prompt?: string | null;
  negative_prompt?: string | null;
}

export interface VisualFeatureFewShotSample {
  type: 'positive' | 'negative';
  image: string;
  label?: string | null;
  filename?: string | null;
}

export interface PipelineConfig {
  mode: PipelineMode;
  name: string;
  description: string;
  enabled: boolean;
  types: PipelineTypeConfig[];
}

export type RegexModalCheck =
  | 'empty_pattern'
  | 'invalid_pattern'
  | 'matches_empty'
  | 'no_sample'
  | 'pass'
  | 'fail';

export function getRegexModalCheck(pattern: string, sample: string): RegexModalCheck {
  const p = pattern.trim();
  if (!p) return 'empty_pattern';
  let regex: RegExp;
  try {
    regex = new RegExp(p);
  } catch {
    return 'invalid_pattern';
  }
  if (regex.test('')) return 'matches_empty';
  const s = sample.trim();
  if (!s) return 'no_sample';
  return regex.test(s) ? 'pass' : 'fail';
}

export function getEntityTypeTone(useLlm: boolean): SelectionTone {
  return useLlm ? 'semantic' : 'regex';
}

export function getPipelineTone(mode: PipelineMode): SelectionTone {
  return mode === 'ocr_has' ? 'semantic' : 'visual';
}

export function getToneColor(tone: SelectionTone): string {
  return selectionToneHex[tone];
}

export function buildPipelineTypeId(name: string, mode: PipelineMode) {
  const normalized = name
    .trim()
    .replace(/[^a-zA-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
  const suffix = normalized || Date.now().toString(36);
  return `custom_${mode}_${suffix}`;
}

export function useEntityTypes() {
  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>([]);
  const [textTaxonomy, setTextTaxonomy] = useState<TextTaxonomyDomain[]>([]);
  const [pipelines, setPipelines] = useState<PipelineConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [pipelinesLoading, setPipelinesLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const importFileRef = useRef<HTMLInputElement>(null);

  const initialLoadDone = useRef(false);

  const fetchEntityTypes = useCallback(async () => {
    try {
      // Only show full loading spinner on initial load, not on CRUD refreshes
      if (!initialLoadDone.current) setLoading(true);
      setLoadError(null);
      const [types, taxonomyRes] = await Promise.all([
        fetchRecognitionEntityTypes(false, 1_200),
        authFetch('/api/v1/custom-types/taxonomy').then((res) => {
          if (!res.ok) throw new Error(`taxonomy ${res.status}`);
          return res.json() as Promise<{ domains: TextTaxonomyDomain[] }>;
        }),
      ]);
      setEntityTypes(types as EntityTypeConfig[]);
      setTextTaxonomy(Array.isArray(taxonomyRes.domains) ? taxonomyRes.domains : []);
      initialLoadDone.current = true;
    } catch (err) {
      if (import.meta.env.DEV) console.error('fetch entity types failed', err);
      setEntityTypes([]);
      setTextTaxonomy([]);
      setLoadError(t('settings.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchPipelines = useCallback(async () => {
    try {
      setPipelinesLoading(true);
      setLoadError(null);
      const fetched = (await fetchRecognitionPipelines(1_200)) as PipelineConfig[];
      const merged = Array.from(
        fetched.reduce((acc, pipeline) => {
          const existing = acc.get(pipeline.mode);
          acc.set(
            pipeline.mode,
            existing
              ? { ...existing, types: [...existing.types, ...pipeline.types], enabled: existing.enabled || pipeline.enabled }
              : pipeline,
          );
          return acc;
        }, new Map<PipelineMode, PipelineConfig>()).values(),
      );
      const normalized = merged.map((p: PipelineConfig) =>
          p.mode === 'visual_features'
            ? {
                ...p,
                name: t('settings.pipelineDisplayName.image'),
                description: t('settings.pipelineDescription.image'),
              }
            : p.mode === 'ocr_has'
              ? {
                  ...p,
                  name: t('settings.pipelineDisplayName.ocr'),
                  description: t('settings.pipelineDescription.ocr'),
                }
              : p,
      );
      setPipelines(normalized);
    } catch (err) {
      if (import.meta.env.DEV) console.error('fetch pipelines failed', err);
      setPipelines([]);
      setLoadError((current) => current ?? t('settings.loadFailed'));
    } finally {
      setPipelinesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEntityTypes();
    fetchPipelines();
  }, [fetchEntityTypes, fetchPipelines]);

  const regexTypes = useMemo(
    () =>
      entityTypes.filter(
        (t) => t.enabled !== false && t.id.startsWith('custom_') && t.regex_pattern,
      ),
    [entityTypes],
  );
  // Text rules list: LLM (semantic) types plus custom regex-fallback types (use_llm=false).
  const textRuleTypes = useMemo(
    () =>
      entityTypes.filter(
        (t) =>
          t.enabled !== false &&
          (t.use_llm || (t.id.startsWith('custom_') && Boolean(t.regex_pattern))),
      ),
    [entityTypes],
  );

  const createType = useCallback(
    async (newType: {
      name: string;
      description: string;
      regex_pattern: string;
      use_llm: boolean;
      tag_template?: string;
      data_domain?: string;
      generic_target?: string | null;
      entity_type_ids?: string[];
      coref_enabled?: boolean;
      default_enabled?: boolean;
    }) => {
      const res = await authFetch('/api/v1/custom-types', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newType.name.trim(),
          description: newType.description?.trim() || null,
          examples: [],
          color: getToneColor(getEntityTypeTone(newType.use_llm)),
          regex_pattern: newType.regex_pattern?.trim() || null,
          use_llm: newType.use_llm,
          tag_template: newType.tag_template || null,
          data_domain: newType.data_domain || 'custom_extension',
          generic_target: newType.generic_target || null,
          entity_type_ids: newType.entity_type_ids || [],
          coref_enabled: newType.coref_enabled ?? true,
          default_enabled: Boolean(newType.default_enabled),
        }),
      });
      if (res.ok) {
        await fetchEntityTypes();
        window.dispatchEvent(new CustomEvent('entity-types-changed'));
        showToast(t('settings.createSuccess'), 'success');
      } else {
        const data = await res.json().catch(() => ({}));
        showToast((data as { detail?: string }).detail || t('settings.createFailed'), 'error');
      }
      return res.ok;
    },
    [fetchEntityTypes],
  );

  const updateType = useCallback(
    async (
      id: string,
      update: {
        name: string;
        description: string;
        regex_pattern: string;
        use_llm: boolean;
        tag_template: string;
        data_domain?: string;
        generic_target?: string | null;
        entity_type_ids?: string[];
        coref_enabled?: boolean;
        default_enabled?: boolean;
      },
    ) => {
      const res = await authFetch(`/api/v1/custom-types/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: update.name.trim(),
          description: update.description?.trim() || null,
          color: getToneColor(getEntityTypeTone(update.use_llm)),
          regex_pattern: update.regex_pattern?.trim() || null,
          use_llm: update.use_llm,
          tag_template: update.tag_template || null,
          data_domain: update.data_domain || 'custom_extension',
          generic_target: update.generic_target || null,
          entity_type_ids: update.entity_type_ids || [],
          coref_enabled: update.coref_enabled ?? true,
          default_enabled: Boolean(update.default_enabled),
        }),
      });
      if (res.ok) {
        await fetchEntityTypes();
        window.dispatchEvent(new CustomEvent('entity-types-changed'));
        return true;
      }
      const data = await res.json().catch(() => ({}));
      showToast((data as { detail?: string }).detail || t('settings.saveFailed'), 'error');
      return false;
    },
    [fetchEntityTypes],
  );

  const deleteType = useCallback(
    async (id: string) => {
      const res = await authFetch(`/api/v1/custom-types/${id}`, { method: 'DELETE' });
      if (res.ok) {
        await fetchEntityTypes();
        window.dispatchEvent(new CustomEvent('entity-types-changed'));
      } else {
        const d = await res.json().catch(() => ({}));
        showToast(d.detail || t('settings.deleteTypeFailed'), 'error');
      }
    },
    [fetchEntityTypes],
  );

  const resetToDefault = useCallback(async () => {
    const res = await authFetch('/api/v1/custom-types/reset', { method: 'POST' });
    if (res.ok) {
      await fetchEntityTypes();
      window.dispatchEvent(new CustomEvent('entity-types-changed'));
    }
  }, [fetchEntityTypes]);

  const createPipelineType = useCallback(
    async (
      mode: PipelineMode,
      name: string,
      description: string,
      options?: Pick<
        PipelineTypeConfig,
        | 'rules'
        | 'checklist'
        | 'negative_prompt_enabled'
        | 'negative_prompt'
        | 'few_shot_enabled'
        | 'few_shot_samples'
      >,
    ) => {
      const typeId = buildPipelineTypeId(name, mode);
      const res = await authFetch(`/api/v1/vision-pipelines/${mode}/types`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: typeId,
          name: name.trim(),
          description: description?.trim() || null,
          examples: [],
          color: getToneColor(getPipelineTone(mode)),
          enabled: true,
          order: 100,
          rules: options?.rules ?? [],
          checklist: options?.checklist ?? [],
          negative_prompt_enabled: options?.negative_prompt_enabled ?? false,
          negative_prompt: options?.negative_prompt ?? null,
          few_shot_enabled: options?.few_shot_enabled ?? false,
          few_shot_samples: options?.few_shot_samples ?? [],
        }),
      });
      if (res.ok) await fetchPipelines();
      else {
        const d = await res.json().catch(() => ({}));
        showToast(d.detail || t('settings.createFailed'), 'error');
      }
      return res.ok;
    },
    [fetchPipelines],
  );

  const updatePipelineType = useCallback(
    async (
      mode: string,
      typeId: string,
      update: Partial<PipelineTypeConfig> & { name: string; description?: string },
    ) => {
      const res = await authFetch(`/api/v1/vision-pipelines/${mode}/types/${typeId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: typeId, ...update }),
      });
      if (res.ok) await fetchPipelines();
      else {
        const d = await res.json().catch(() => ({}));
        showToast(d.detail || t('settings.saveFailed'), 'error');
      }
      return res.ok;
    },
    [fetchPipelines],
  );

  const deletePipelineType = useCallback(
    async (mode: string, typeId: string) => {
      const res = await authFetch(`/api/v1/vision-pipelines/${mode}/types/${typeId}`, {
        method: 'DELETE',
      });
      if (res.ok) await fetchPipelines();
      else {
        const d = await res.json().catch(() => ({}));
        showToast(d.detail || t('settings.deleteTypeFailed'), 'error');
      }
    },
    [fetchPipelines],
  );

  const resetPipelines = useCallback(async () => {
    const res = await authFetch('/api/v1/vision-pipelines/reset', { method: 'POST' });
    if (res.ok) await fetchPipelines();
  }, [fetchPipelines]);

  const handleExportPresets = useCallback(async () => {
    try {
      const res = await fetchWithTimeout('/api/v1/presets/export', { timeoutMs: 15000 });
      if (!res.ok) throw new Error('export failed');
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `presets-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      showToast(t('settings.exportFailed'), 'error');
    }
  }, []);

  const handleImportPresets = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const presets = data.presets || data;
      const res = await authFetch('/api/v1/presets/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ presets, merge: false }),
      });
      if (!res.ok) throw new Error('import failed');
      showToast(t('settings.importSuccess'), 'success');
    } catch {
      showToast(t('settings.importFormatError'), 'error');
    } finally {
      if (importFileRef.current) importFileRef.current.value = '';
    }
  }, []);

  return {
    entityTypes,
    textTaxonomy,
    pipelines,
    loading,
    pipelinesLoading,
    regexTypes,
    textRuleTypes,
    loadError,
    importFileRef,
    createType,
    updateType,
    deleteType,
    resetToDefault,
    createPipelineType,
    updatePipelineType,
    deletePipelineType,
    resetPipelines,
    handleExportPresets,
    handleImportPresets,
    fetchEntityTypes,
    fetchPipelines,
  };
}
