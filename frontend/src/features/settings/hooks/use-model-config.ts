// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useCallback } from 'react';
import { authFetch } from '@/services/api-client';
import { fetchWithTimeout } from '@/utils/fetchWithTimeout';
import { showToast } from '@/components/Toast';
import { t } from '@/i18n';
import { TEST_BUTTON_MIN_SPIN_MS } from '@/constants/timing';
import { useServiceHealth } from '@/hooks/use-service-health';

function normalizeServiceLive(status: 'online' | 'offline' | 'checking' | undefined) {
  return status === 'online' || status === 'offline' ? status : undefined;
}

export function useNerBackend() {
  const [llamacppBaseUrl, setLlamacppBaseUrl] = useState('http://127.0.0.1:8080/v1');
  const [nerLoading, setNerLoading] = useState(true);
  const [nerSaving, setNerSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [nerLive, setNerLive] = useState<'online' | 'offline' | undefined>(undefined);
  const { health } = useServiceHealth();

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

  useEffect(() => {
    void fetchNerBackend();
  }, [fetchNerBackend]);

  useEffect(() => {
    const status = health?.services?.has_ner?.status;
    setNerLive(normalizeServiceLive(status));
  }, [health]);

  const payload = useCallback(
    () => ({
      backend: 'llamacpp' as const,
      llamacpp_base_url: llamacppBaseUrl,
    }),
    [llamacppBaseUrl],
  );

  const saveNerBackend = useCallback(async () => {
    try {
      setNerSaving(true);
      setTestResult(null);
      const res = await authFetch('/api/v1/ner-backend', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        showToast((d as { detail?: string }).detail || t('settings.saveFailed'), 'error');
        return;
      }
      setTestResult({ success: true, message: t('settings.textModel.saveSuccess') });
    } catch (e) {
      if (import.meta.env.DEV) console.error(e);
      showToast(t('settings.saveFailed'), 'error');
    } finally {
      setNerSaving(false);
    }
  }, [payload]);

  const testConnection = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await authFetch('/api/v1/ner-backend/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      });
      let data: { success?: boolean; message?: string; detail?: unknown } = {};
      try {
        data = await res.json();
      } catch {
        setTestResult({
          success: false,
          message: t('settings.textModel.responseNotJson').replace('{status}', String(res.status)),
        });
        return;
      }
      if (!res.ok) {
        const d = data.detail;
        let errMsg = t('settings.textModel.requestFailedWithStatus').replace(
          '{status}',
          String(res.status),
        );
        if (Array.isArray(d))
          errMsg = d.map((x: { msg?: string }) => x.msg || JSON.stringify(x)).join('\uFF1B');
        else if (typeof d === 'string') errMsg = d;
        else if (d && typeof d === 'object' && 'msg' in (d as object))
          errMsg = String((d as { msg: string }).msg);
        setTestResult({ success: false, message: errMsg });
        return;
      }
      setTestResult({
        success: Boolean(data.success),
        message:
          data.message ||
          (data.success
            ? t('settings.textModel.connectSuccess')
            : t('settings.textModel.connectFailed')),
      });
    } catch {
      setTestResult({ success: false, message: t('settings.textModel.testRequestFailed') });
    } finally {
      setTimeout(() => setTesting(false), TEST_BUTTON_MIN_SPIN_MS);
    }
  }, [payload]);

  const clearNerOverride = useCallback(async () => {
    try {
      const res = await authFetch('/api/v1/ner-backend', { method: 'DELETE' });
      if (res.ok) {
        await fetchNerBackend();
        setTestResult({ success: true, message: t('settings.textModel.resetSuccess') });
      }
    } catch (e) {
      if (import.meta.env.DEV) console.error(e);
    }
  }, [fetchNerBackend]);

  return {
    llamacppBaseUrl,
    setLlamacppBaseUrl,
    nerLoading,
    nerSaving,
    testing,
    testResult,
    nerLive,
    saveNerBackend,
    testConnection,
    clearNerOverride,
  };
}

export interface ModelConfig {
  id: string;
  name: string;
  provider: 'local' | 'openai' | 'custom';
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

interface ModelConfigList {
  configs: ModelConfig[];
  active_id?: string;
}
interface BuiltinServiceLive {
  paddle?: 'online' | 'offline';
  has_image?: 'online' | 'offline';
}

export const BUILTIN_VISION_IDS = new Set(['paddle_ocr_service', 'has_image_service']);

export const DEFAULT_MODEL_FORM: Partial<ModelConfig> = {
  provider: 'local',
  temperature: 0.8,
  top_p: 0.6,
  max_tokens: 4096,
  enable_thinking: false,
};

export function useVisionModelConfig() {
  const [modelConfigs, setModelConfigs] = useState<ModelConfigList>({
    configs: [],
    active_id: undefined,
  });
  const [loading, setLoading] = useState(true);
  const [builtinLive, setBuiltinLive] = useState<BuiltinServiceLive | null>(null);
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const { health } = useServiceHealth();

  const fetchModelConfigs = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetchWithTimeout('/api/v1/model-config', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('fetch failed');
      const data = await res.json().catch(() => ({}));
      const rawConfigs: ModelConfig[] = Array.isArray(data?.configs) ? data.configs : [];
      // After fetching models from API, redact keys
      const configs = rawConfigs.map((m) => ({
        ...m,
        api_key: m.api_key ? '__REDACTED__' : undefined,
      }));
      setModelConfigs({
        configs,
        active_id: typeof data?.active_id === 'string' ? data.active_id : undefined,
      });
    } catch (err) {
      if (import.meta.env.DEV) console.error('fetch model configs failed', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchModelConfigs();
  }, [fetchModelConfigs]);

  useEffect(() => {
    setBuiltinLive({
      paddle: normalizeServiceLive(health?.services?.paddle_ocr?.status),
      has_image: normalizeServiceLive(health?.services?.has_image?.status),
    });
  }, [health]);

  const saveModelConfig = useCallback(
    async (form: Partial<ModelConfig>, editingId: string | null) => {
      if (!form.name || !form.model_name) return false;
      const configId = editingId || `custom_${Date.now()}`;
      // In save payload, omit redacted/empty keys so the backend keeps the existing key
      const sanitizedForm = { ...form };
      if (sanitizedForm.api_key === '__REDACTED__' || sanitizedForm.api_key === '') {
        delete sanitizedForm.api_key;
      }
      const payload = {
        ...sanitizedForm,
        id: configId,
        enabled:
          editingId && BUILTIN_VISION_IDS.has(editingId) ? true : (sanitizedForm.enabled ?? true),
      };
      const url = editingId ? `/api/v1/model-config/${editingId}` : '/api/v1/model-config';
      const method = editingId ? 'PUT' : 'POST';
      const res = await authFetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        await fetchModelConfigs();
        return true;
      }
      const data = await res.json();
      showToast(data.detail || t('settings.saveFailed'), 'error');
      return false;
    },
    [fetchModelConfigs],
  );

  const deleteModelConfig = useCallback(
    async (configId: string) => {
      const res = await authFetch(`/api/v1/model-config/${configId}`, { method: 'DELETE' });
      if (res.ok) await fetchModelConfigs();
      else {
        const d = await res.json();
        showToast(d.detail || t('settings.deleteTypeFailed'), 'error');
      }
    },
    [fetchModelConfigs],
  );

  const testModelConfig = useCallback(async (configId: string) => {
    setTestingModelId(configId);
    setTestResult(null);
    try {
      const timeoutMs = configId === 'paddle_ocr_service' ? 60000 : 15000;
      const res = await fetchWithTimeout(`/api/v1/model-config/test/${configId}`, {
        method: 'POST',
        timeoutMs,
      });
      setTestResult(await res.json());
    } catch {
      setTestResult({
        success: false,
        message:
          configId === 'paddle_ocr_service'
            ? t('settings.visionModel.testFailedLong')
            : t('settings.visionModel.testFailed'),
      });
    } finally {
      setTestingModelId(null);
    }
  }, []);

  const resetModelConfigs = useCallback(async () => {
    const res = await authFetch('/api/v1/model-config/reset', { method: 'POST' });
    if (res.ok) await fetchModelConfigs();
  }, [fetchModelConfigs]);

  const liveForBuiltin = useCallback(
    (configId: string): 'online' | 'offline' | undefined => {
      if (configId === 'paddle_ocr_service') return builtinLive?.paddle;
      if (configId === 'has_image_service') return builtinLive?.has_image;
      return undefined;
    },
    [builtinLive],
  );

  const getProviderLabel = (provider: string) => {
    switch (provider) {
      case 'local':
        return t('settings.visionModel.tag.local');
      case 'openai':
        return 'OpenAI';
      case 'custom':
        return t('settings.visionModel.tag.custom');
      default:
        return provider;
    }
  };

  return {
    modelConfigs,
    loading,
    builtinLive,
    testingModelId,
    testResult,
    saveModelConfig,
    deleteModelConfig,
    testModelConfig,
    resetModelConfigs,
    liveForBuiltin,
    getProviderLabel,
  };
}
