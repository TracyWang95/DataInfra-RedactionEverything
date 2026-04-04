/**
 * Hook: entity type & pipeline management for Settings page.
 * Covers text rules (regex + semantic) and vision pipeline types.
 */
import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { fetchWithTimeout } from '@/utils/fetchWithTimeout';
import { showToast } from '@/components/Toast';

export interface EntityTypeConfig {
  id: string;
  name: string;
  description?: string;
  examples?: string[];
  color: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  enabled?: boolean;
  order?: number;
  tag_template?: string | null;
}

export interface PipelineTypeConfig {
  id: string;
  name: string;
  description?: string;
  examples?: string[];
  color: string;
  enabled: boolean;
  order: number;
}

export interface PipelineConfig {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: PipelineTypeConfig[];
}

export type RegexModalCheck =
  | 'empty_pattern'
  | 'invalid_pattern'
  | 'no_sample'
  | 'pass'
  | 'fail';

export function getRegexModalCheck(pattern: string, sample: string): RegexModalCheck {
  const p = pattern.trim();
  if (!p) return 'empty_pattern';
  try { new RegExp(p); } catch { return 'invalid_pattern'; }
  const s = sample.trim();
  if (!s) return 'no_sample';
  return new RegExp(p).test(s) ? 'pass' : 'fail';
}

export function buildPipelineTypeId(name: string, mode: 'ocr_has' | 'has_image') {
  const normalized = name.trim().replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase();
  return normalized || `custom_${mode}_${Date.now()}`;
}

export function useEntityTypes() {
  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>([]);
  const [pipelines, setPipelines] = useState<PipelineConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const importFileRef = useRef<HTMLInputElement>(null);

  const fetchEntityTypes = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetchWithTimeout('/api/v1/custom-types?enabled_only=false', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('fetch failed');
      const data = await res.json();
      setEntityTypes(data.custom_types || []);
    } catch (err) {
      if (import.meta.env.DEV) console.error('fetch entity types failed', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchPipelines = useCallback(async () => {
    try {
      const res = await fetchWithTimeout('/api/v1/vision-pipelines', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('fetch failed');
      const data = await res.json();
      const normalized = (data || []).map((p: PipelineConfig) =>
        p.mode === 'has_image'
          ? { ...p, name: 'HaS Image', description: '\u4F7F\u7528\u89C6\u89C9\u8BED\u8A00\u6A21\u578B\u8BC6\u522B\u7B7E\u540D\u3001\u5370\u7AE0\u3001\u624B\u5199\u7B49\u89C6\u89C9\u4FE1\u606F\u3002' }
          : p
      );
      setPipelines(normalized);
    } catch (err) {
      if (import.meta.env.DEV) console.error('fetch pipelines failed', err);
    }
  }, []);

  useEffect(() => {
    fetchEntityTypes();
    fetchPipelines();
  }, [fetchEntityTypes, fetchPipelines]);

  const regexTypes = useMemo(() => entityTypes.filter(t => t.regex_pattern), [entityTypes]);
  const llmTypes = useMemo(() => entityTypes.filter(t => t.use_llm), [entityTypes]);

  const createType = useCallback(async (newType: {
    name: string; description: string; regex_pattern: string; use_llm: boolean;
  }) => {
    const res = await fetch('/api/v1/custom-types', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newType.name.trim(),
        description: newType.use_llm ? newType.description?.trim() || null : null,
        examples: [], color: '#6B7280',
        regex_pattern: newType.use_llm ? null : newType.regex_pattern || null,
        use_llm: newType.use_llm, tag_template: null,
      }),
    });
    if (res.ok) await fetchEntityTypes();
    return res.ok;
  }, [fetchEntityTypes]);

  const deleteType = useCallback(async (id: string) => {
    if (!confirm('\u786E\u5B9A\u8981\u5220\u9664\u6B64\u7C7B\u578B\u5417\uFF1F')) return;
    const res = await fetch(`/api/v1/custom-types/${id}`, { method: 'DELETE' });
    if (res.ok) await fetchEntityTypes();
    else { const d = await res.json(); showToast(d.detail || '\u5220\u9664\u5931\u8D25', 'error'); }
  }, [fetchEntityTypes]);

  const resetToDefault = useCallback(async () => {
    if (!confirm('\u786E\u5B9A\u8981\u91CD\u7F6E\u4E3A\u9ED8\u8BA4\u914D\u7F6E\u5417\uFF1F\u8FD9\u5C06\u8986\u76D6\u6240\u6709\u81EA\u5B9A\u4E49\u4FEE\u6539\u3002')) return;
    const res = await fetch('/api/v1/custom-types/reset', { method: 'POST' });
    if (res.ok) await fetchEntityTypes();
  }, [fetchEntityTypes]);

  const createPipelineType = useCallback(async (
    mode: 'ocr_has' | 'has_image', name: string, description: string
  ) => {
    const typeId = buildPipelineTypeId(name, mode);
    const res = await fetch(`/api/v1/vision-pipelines/${mode}/types`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: typeId, name: name.trim(), description: description?.trim() || null,
        examples: [], color: '#6B7280', enabled: true, order: 100,
      }),
    });
    if (res.ok) await fetchPipelines();
    else { const d = await res.json(); showToast(d.detail || '\u521B\u5EFA\u5931\u8D25', 'error'); }
    return res.ok;
  }, [fetchPipelines]);

  const updatePipelineType = useCallback(async (
    mode: string, typeId: string, update: Partial<PipelineTypeConfig> & { name: string; description?: string }
  ) => {
    const res = await fetch(`/api/v1/vision-pipelines/${mode}/types/${typeId}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: typeId, ...update }),
    });
    if (res.ok) await fetchPipelines();
    else { const d = await res.json(); showToast(d.detail || '\u66F4\u65B0\u5931\u8D25', 'error'); }
    return res.ok;
  }, [fetchPipelines]);

  const deletePipelineType = useCallback(async (mode: string, typeId: string) => {
    if (!confirm('\u786E\u5B9A\u8981\u5220\u9664\u6B64\u7C7B\u578B\u5417\uFF1F')) return;
    const res = await fetch(`/api/v1/vision-pipelines/${mode}/types/${typeId}`, { method: 'DELETE' });
    if (res.ok) await fetchPipelines();
    else { const d = await res.json(); showToast(d.detail || '\u5220\u9664\u5931\u8D25', 'error'); }
  }, [fetchPipelines]);

  const resetPipelines = useCallback(async () => {
    if (!confirm('\u786E\u5B9A\u8981\u91CD\u7F6E\u6240\u6709Pipeline\u914D\u7F6E\u4E3A\u9ED8\u8BA4\u5417\uFF1F')) return;
    const res = await fetch('/api/v1/vision-pipelines/reset', { method: 'POST' });
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
      showToast('\u5BFC\u51FA\u9884\u8BBE\u5931\u8D25', 'error');
    }
  }, []);

  const handleImportPresets = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const presets = data.presets || data;
      const res = await fetch('/api/v1/presets/import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ presets, merge: false }),
      });
      if (!res.ok) throw new Error('import failed');
      showToast('\u9884\u8BBE\u5BFC\u5165\u6210\u529F', 'success');
    } catch {
      showToast('\u5BFC\u5165\u9884\u8BBE\u5931\u8D25\uFF0C\u8BF7\u68C0\u67E5\u6587\u4EF6\u683C\u5F0F', 'error');
    } finally {
      if (importFileRef.current) importFileRef.current.value = '';
    }
  }, []);

  return {
    entityTypes, pipelines, loading, regexTypes, llmTypes, importFileRef,
    createType, deleteType, resetToDefault,
    createPipelineType, updatePipelineType, deletePipelineType, resetPipelines,
    handleExportPresets, handleImportPresets, fetchEntityTypes, fetchPipelines,
  };
}
