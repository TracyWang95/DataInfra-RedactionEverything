/**
 * Hook: NER backend + vision model configuration management.
 */
import { useState, useEffect, useCallback } from 'react';
import { fetchWithTimeout } from '@/utils/fetchWithTimeout';
import { showToast } from '@/components/Toast';

/* ── Text NER (HaS / llama-server) ── */

const OLLAMA_PLACEHOLDER = {
  ollama_base_url: 'http://127.0.0.1:11434/v1',
  ollama_model: 'qwen3:8b',
};

export function useNerBackend() {
  const [llamacppBaseUrl, setLlamacppBaseUrl] = useState('http://127.0.0.1:8080/v1');
  const [nerLoading, setNerLoading] = useState(true);
  const [nerSaving, setNerSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [nerLive, setNerLive] = useState<'online' | 'offline' | undefined>(undefined);

  const fetchNerBackend = useCallback(async () => {
    try {
      setNerLoading(true);
      const res = await fetchWithTimeout('/api/v1/ner-backend', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('fetch failed');
      const data = await res.json();
      setLlamacppBaseUrl(data.llamacpp_base_url || 'http://127.0.0.1:8080/v1');
    } catch (e) {
      if (import.meta.env.DEV) console.error('fetch NER config failed', e);
    } finally {
      setNerLoading(false);
    }
  }, []);

  useEffect(() => { void fetchNerBackend(); }, [fetchNerBackend]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch('/health/services');
        if (!res.ok || cancelled) return;
        const d = await res.json();
        const st = d.services?.has_ner?.status;
        if (st === 'online' || st === 'offline') setNerLive(st);
        else setNerLive(undefined);
      } catch { if (!cancelled) setNerLive(undefined); }
    };
    void load();
    const t = setInterval(load, 15000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  const payload = useCallback(() => ({
    backend: 'llamacpp' as const,
    llamacpp_base_url: llamacppBaseUrl,
    ...OLLAMA_PLACEHOLDER,
  }), [llamacppBaseUrl]);

  const saveNerBackend = useCallback(async () => {
    try {
      setNerSaving(true); setTestResult(null);
      const res = await fetch('/api/v1/ner-backend', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        showToast((d as { detail?: string }).detail || '\u4FDD\u5B58\u5931\u8D25', 'error');
        return;
      }
      setTestResult({ success: true, message: '\u914D\u7F6E\u5DF2\u4FDD\u5B58\u5E76\u751F\u6548\u3002' });
    } catch (e) {
      if (import.meta.env.DEV) console.error(e);
      showToast('\u4FDD\u5B58\u5931\u8D25', 'error');
    } finally { setNerSaving(false); }
  }, [payload]);

  const testConnection = useCallback(async () => {
    setTesting(true); setTestResult(null);
    try {
      const res = await fetch('/api/v1/ner-backend/test', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      });
      let data: { success?: boolean; message?: string; detail?: unknown } = {};
      try { data = await res.json(); } catch {
        setTestResult({ success: false, message: `HTTP ${res.status}\uFF1A\u54CD\u5E94\u4E0D\u662FJSON\uFF08\u8BF7\u786E\u8BA4\u540E\u7AEF\u5DF2\u542F\u52A8\uFF09` });
        return;
      }
      if (!res.ok) {
        const d = data.detail;
        let errMsg = `\u8BF7\u6C42\u5931\u8D25 (${res.status})`;
        if (Array.isArray(d)) errMsg = d.map((x: { msg?: string }) => x.msg || JSON.stringify(x)).join('\uFF1B');
        else if (typeof d === 'string') errMsg = d;
        else if (d && typeof d === 'object' && 'msg' in (d as object)) errMsg = String((d as { msg: string }).msg);
        setTestResult({ success: false, message: errMsg });
        return;
      }
      setTestResult({
        success: Boolean(data.success),
        message: data.message || (data.success ? '\u8FDE\u63A5\u6210\u529F' : '\u8FDE\u63A5\u5931\u8D25\uFF08\u8BF7\u67E5\u770B\u540E\u7AEF\u65E5\u5FD7\u6216\u4FDD\u5B58\u914D\u7F6E\u540E\u91CD\u8BD5\uFF09'),
      });
    } catch { setTestResult({ success: false, message: '\u6D4B\u8BD5\u8BF7\u6C42\u5931\u8D25\uFF08\u7F51\u7EDC\u6216\u8DE8\u57DF\uFF09' }); }
    finally { setTimeout(() => setTesting(false), 300); }
  }, [payload]);

  const clearNerOverride = useCallback(async () => {
    if (!confirm('\u786E\u5B9A\u6E05\u9664\u524D\u7AEF\u4FDD\u5B58\u7684\u914D\u7F6E\uFF0C\u6062\u590D\u4E3A\u670D\u52A1\u5668\u73AF\u5883\u53D8\u91CF\u9ED8\u8BA4\u503C\uFF1F')) return;
    try {
      const res = await fetch('/api/v1/ner-backend', { method: 'DELETE' });
      if (res.ok) {
        await fetchNerBackend();
        setTestResult({ success: true, message: '\u5DF2\u6062\u590D\u4E3A\u73AF\u5883\u53D8\u91CF\u9ED8\u8BA4\u3002' });
      }
    } catch (e) { if (import.meta.env.DEV) console.error(e); }
  }, [fetchNerBackend]);

  return {
    llamacppBaseUrl, setLlamacppBaseUrl, nerLoading, nerSaving, testing,
    testResult, nerLive, saveNerBackend, testConnection, clearNerOverride,
  };
}

/* ── Vision model configs ── */

export interface ModelConfig {
  id: string;
  name: string;
  provider: 'local' | 'zhipu' | 'openai' | 'custom';
  enabled: boolean;
  base_url?: string;
  api_key?: string;
  model_name: string;
  temperature: number;
  top_p: number;
  max_tokens: number;
  enable_thinking: boolean;
  description?: string;
}

interface ModelConfigList { configs: ModelConfig[]; active_id?: string; }
interface BuiltinServiceLive { paddle?: 'online' | 'offline'; has_image?: 'online' | 'offline'; }

export const BUILTIN_VISION_IDS = new Set(['paddle_ocr_service', 'has_image_service']);

export const DEFAULT_MODEL_FORM: Partial<ModelConfig> = {
  provider: 'local', temperature: 0.8, top_p: 0.6, max_tokens: 4096, enable_thinking: false,
};

export function useVisionModelConfig() {
  const [modelConfigs, setModelConfigs] = useState<ModelConfigList>({ configs: [], active_id: undefined });
  const [loading, setLoading] = useState(true);
  const [builtinLive, setBuiltinLive] = useState<BuiltinServiceLive | null>(null);
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  const fetchModelConfigs = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetchWithTimeout('/api/v1/model-config', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('fetch failed');
      setModelConfigs(await res.json());
    } catch (err) { if (import.meta.env.DEV) console.error('fetch model configs failed', err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchModelConfigs(); }, [fetchModelConfigs]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch('/health/services');
        if (!res.ok || cancelled) return;
        const d = await res.json();
        setBuiltinLive({ paddle: d.services?.paddle_ocr?.status, has_image: d.services?.has_image?.status });
      } catch { if (!cancelled) setBuiltinLive({ paddle: undefined, has_image: undefined }); }
    };
    load();
    const t = setInterval(load, 15000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  const saveModelConfig = useCallback(async (form: Partial<ModelConfig>, editingId: string | null) => {
    if (!form.name || !form.model_name) return false;
    const configId = editingId || `custom_${Date.now()}`;
    const payload = {
      ...form, id: configId,
      enabled: editingId && BUILTIN_VISION_IDS.has(editingId) ? true : (form.enabled ?? true),
    };
    const url = editingId ? `/api/v1/model-config/${editingId}` : '/api/v1/model-config';
    const method = editingId ? 'PUT' : 'POST';
    const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (res.ok) { await fetchModelConfigs(); return true; }
    const data = await res.json();
    showToast(data.detail || '\u4FDD\u5B58\u5931\u8D25', 'error');
    return false;
  }, [fetchModelConfigs]);

  const deleteModelConfig = useCallback(async (configId: string) => {
    if (!confirm('\u786E\u5B9A\u8981\u5220\u9664\u6B64\u6A21\u578B\u914D\u7F6E\u5417\uFF1F')) return;
    const res = await fetch(`/api/v1/model-config/${configId}`, { method: 'DELETE' });
    if (res.ok) await fetchModelConfigs();
    else { const d = await res.json(); showToast(d.detail || '\u5220\u9664\u5931\u8D25', 'error'); }
  }, [fetchModelConfigs]);

  const testModelConfig = useCallback(async (configId: string) => {
    setTestingModelId(configId); setTestResult(null);
    try {
      const timeoutMs = configId === 'paddle_ocr_service' ? 60000 : 15000;
      const res = await fetchWithTimeout(`/api/v1/model-config/test/${configId}`, { method: 'POST', timeoutMs });
      setTestResult(await res.json());
    } catch {
      setTestResult({
        success: false,
        message: configId === 'paddle_ocr_service'
          ? '\u6D4B\u8BD5\u8BF7\u6C42\u5931\u8D25\u6216\u8D85\u65F6\uFF08OCR\u9996\u542F\u52A0\u8F7D\u53EF\u80FD\u8F83\u6162\uFF09' : '\u6D4B\u8BD5\u8BF7\u6C42\u5931\u8D25',
      });
    } finally { setTestingModelId(null); }
  }, []);

  const resetModelConfigs = useCallback(async () => {
    if (!confirm('\u786E\u5B9A\u8981\u91CD\u7F6E\u6240\u6709\u6A21\u578B\u914D\u7F6E\u4E3A\u9ED8\u8BA4\u5417\uFF1F')) return;
    const res = await fetch('/api/v1/model-config/reset', { method: 'POST' });
    if (res.ok) await fetchModelConfigs();
  }, [fetchModelConfigs]);

  const liveForBuiltin = useCallback((configId: string): 'online' | 'offline' | undefined => {
    if (configId === 'paddle_ocr_service') return builtinLive?.paddle;
    if (configId === 'has_image_service') return builtinLive?.has_image;
    return undefined;
  }, [builtinLive]);

  const getProviderLabel = (provider: string) => {
    switch (provider) {
      case 'local': return '\u672C\u5730';
      case 'zhipu': return '\u667A\u8C31\uFF08\u65E7\uFF09';
      case 'openai': return 'OpenAI';
      case 'custom': return '\u81EA\u5B9A\u4E49';
      default: return provider;
    }
  };

  return {
    modelConfigs, loading, builtinLive, testingModelId, testResult,
    saveModelConfig, deleteModelConfig, testModelConfig, resetModelConfigs,
    liveForBuiltin, getProviderLabel,
  };
}
