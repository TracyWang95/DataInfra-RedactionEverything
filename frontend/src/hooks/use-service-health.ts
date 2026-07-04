// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useSyncExternalStore } from 'react';
import { t } from '@/i18n';

export interface ServiceInfo {
  name: string;
  status: 'online' | 'offline' | 'checking' | 'busy' | 'degraded';
  detail?: ServiceDetail | null;
}

export type ServiceStatus = ServiceInfo['status'];
export type ServiceRuntimeMode = 'gpu' | 'cpu' | 'unknown';

export interface ServiceDetail {
  runtime?: string | null;
  runtime_mode?: ServiceRuntimeMode;
  gpu_available?: boolean | null;
  device?: string | null;
  gpu_only_mode?: boolean | null;
  cpu_fallback_risk?: boolean | null;
}

export interface GpuProcessInfo {
  pid: number;
  name: string;
  used_mb?: number | null;
}

export interface ServicesHealth {
  all_online: boolean;
  probe_ms?: number;
  checked_at?: string;
  gpu_memory?: { used_mb: number; total_mb: number } | null;
  gpu_memory_all?: { index: number; used_mb: number; total_mb: number }[] | null;
  accelerator?: string | null;
  gpu_processes?: GpuProcessInfo[];
  services: {
    paddle_ocr: ServiceInfo;
    has_ner: ServiceInfo;
    visual_features: ServiceInfo;
  };
}

const HEALTH_TIMEOUT_MS = 55_000;
const HEALTH_POLL_INTERVAL_MS = 15_000;
const HEALTH_FAILURES_BEFORE_OFFLINE = 3;

const LIVE_SERVICE_STATUSES = new Set([
  'online',
  'busy',
  'running',
  'processing',
  'inferencing',
  'loading',
]);

// Built lazily so the localized fallback name follows the active locale.
function buildServiceFallbacks(): Required<ServicesHealth['services']> {
  return {
    paddle_ocr: { name: 'PaddleOCR', status: 'offline' },
    has_ner: { name: 'HaS Text', status: 'offline' },
    visual_features: { name: t('health.serviceName.visualFeatures'), status: 'offline' },
  };
}

type HealthStoreSnapshot = {
  health: ServicesHealth | null;
  checking: boolean;
  roundTripMs: number | null;
};

type HealthListener = () => void;

const initialSnapshot: HealthStoreSnapshot = {
  health: null,
  checking: true,
  roundTripMs: null,
};

let snapshot: HealthStoreSnapshot = initialSnapshot;
const listeners = new Set<HealthListener>();
let activeFetch: Promise<void> | null = null;
let started = false;
let consecutiveFailures = 0;

function emitHealthChange() {
  listeners.forEach((listener) => listener());
}

function updateSnapshot(next: Partial<HealthStoreSnapshot>) {
  snapshot = { ...snapshot, ...next };
  emitHealthChange();
}

function normalizeService(value: unknown, fallback: ServiceInfo): ServiceInfo {
  if (!value || typeof value !== 'object') return fallback;
  const raw = value as Partial<ServiceInfo>;
  const normalizedStatus =
    typeof raw.status === 'string' && LIVE_SERVICE_STATUSES.has(raw.status)
      ? 'online'
      : raw.status;

  return {
    name: typeof raw.name === 'string' && raw.name.trim() ? raw.name : fallback.name,
    status:
      normalizedStatus === 'online' ||
      normalizedStatus === 'offline' ||
      normalizedStatus === 'checking' ||
      normalizedStatus === 'degraded' ||
      normalizedStatus === 'busy'
        ? normalizedStatus
        : fallback.status,
    detail: normalizeServiceDetail(raw.detail),
  };
}

function normalizeServiceDetail(value: unknown): ServiceDetail | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const raw = value as Record<string, unknown>;
  const detail: ServiceDetail = {};
  if (typeof raw.runtime === 'string') detail.runtime = raw.runtime;
  if (raw.runtime_mode === 'gpu' || raw.runtime_mode === 'cpu' || raw.runtime_mode === 'unknown') {
    detail.runtime_mode = raw.runtime_mode;
  }
  if (typeof raw.gpu_available === 'boolean' || raw.gpu_available === null) {
    detail.gpu_available = raw.gpu_available;
  }
  if (typeof raw.device === 'string') detail.device = raw.device;
  if (typeof raw.gpu_only_mode === 'boolean' || raw.gpu_only_mode === null) {
    detail.gpu_only_mode = raw.gpu_only_mode;
  }
  if (typeof raw.cpu_fallback_risk === 'boolean' || raw.cpu_fallback_risk === null) {
    detail.cpu_fallback_risk = raw.cpu_fallback_risk;
  }
  return Object.keys(detail).length ? detail : undefined;
}

function normalizeGpuProcesses(value: unknown): GpuProcessInfo[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const raw = item as Partial<GpuProcessInfo>;
    if (typeof raw.pid !== 'number') return [];
    return [
      {
        pid: raw.pid,
        name: typeof raw.name === 'string' ? raw.name : '',
        used_mb: typeof raw.used_mb === 'number' ? raw.used_mb : null,
      },
    ];
  });
}

function normalizeGpuMemoryAll(
  value: unknown,
): { index: number; used_mb: number; total_mb: number }[] | null {
  if (!Array.isArray(value)) return null;
  const cards = value.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const raw = item as Record<string, unknown>;
    if (typeof raw.used_mb !== 'number' || typeof raw.total_mb !== 'number') return [];
    return [
      {
        index: typeof raw.index === 'number' ? raw.index : 0,
        used_mb: raw.used_mb,
        total_mb: raw.total_mb,
      },
    ];
  });
  return cards.length ? cards : null;
}

export function normalizeHealthPayload(value: unknown): ServicesHealth {
  const data = value && typeof value === 'object' ? (value as Partial<ServicesHealth>) : {};
  const services = data.services && typeof data.services === 'object' ? data.services : {};
  const serviceFallbacks = buildServiceFallbacks();
  const normalizedServices = {
    paddle_ocr: normalizeService(
      (services as Partial<ServicesHealth['services']>).paddle_ocr,
      serviceFallbacks.paddle_ocr,
    ),
    has_ner: normalizeService(
      (services as Partial<ServicesHealth['services']>).has_ner,
      serviceFallbacks.has_ner,
    ),
    visual_features: normalizeService(
      (services as Partial<ServicesHealth['services']>).visual_features,
      serviceFallbacks.visual_features,
    ),
  };

  return {
    all_online: [
      normalizedServices.paddle_ocr,
      normalizedServices.has_ner,
      normalizedServices.visual_features,
    ].every((service) => service.status === 'online'),
    probe_ms: typeof data.probe_ms === 'number' ? data.probe_ms : undefined,
    checked_at: typeof data.checked_at === 'string' ? data.checked_at : undefined,
    gpu_memory: data.gpu_memory ?? null,
    gpu_memory_all: normalizeGpuMemoryAll((data as { gpu_memory_all?: unknown }).gpu_memory_all),
    accelerator: typeof (data as { accelerator?: unknown }).accelerator === 'string'
      ? ((data as { accelerator?: string }).accelerator as string)
      : null,
    gpu_processes: normalizeGpuProcesses((data as { gpu_processes?: unknown }).gpu_processes),
    services: normalizedServices,
  };
}

async function runHealthCheck(showChecking: boolean) {
  if (activeFetch) {
    if (showChecking && !snapshot.checking) updateSnapshot({ checking: true });
    return activeFetch;
  }

  if (showChecking && !snapshot.checking) {
    updateSnapshot({ checking: true });
  }

  activeFetch = (async () => {
    const ac = new AbortController();
    const timer = window.setTimeout(() => ac.abort(), HEALTH_TIMEOUT_MS);
    const start = performance.now();
    try {
      const res = await fetch('/health/services', {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache' },
        signal: ac.signal,
      });
      if (!res.ok) {
        recordHealthFailure();
        return;
      }
      const data = normalizeHealthPayload(await res.json().catch(() => ({})));
      consecutiveFailures = 0;
      updateSnapshot({
        health: data,
        roundTripMs: Math.round(performance.now() - start),
      });
    } catch {
      recordHealthFailure();
    } finally {
      window.clearTimeout(timer);
      activeFetch = null;
      updateSnapshot({ checking: false });
    }
  })();

  return activeFetch;
}

function recordHealthFailure() {
  consecutiveFailures += 1;
  if (!snapshot.health || consecutiveFailures >= HEALTH_FAILURES_BEFORE_OFFLINE) {
    updateSnapshot({ health: null, roundTripMs: null });
  }
}

function ensureHealthPolling() {
  if (started || typeof window === 'undefined') return;
  started = true;

  void runHealthCheck(false);

  const tick = () => {
    if (document.visibilityState === 'visible') {
      void runHealthCheck(false);
    }
  };

  window.setInterval(tick, HEALTH_POLL_INTERVAL_MS);
  window.addEventListener('focus', tick);
  window.addEventListener('online', tick);
  document.addEventListener('visibilitychange', tick);
}

function subscribe(listener: HealthListener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useServiceHealth() {
  useEffect(() => {
    ensureHealthPolling();
    void runHealthCheck(false);
  }, []);

  const state = useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => initialSnapshot,
  );
  const refresh = useCallback(() => {
    void runHealthCheck(true);
  }, []);

  return {
    health: state.health,
    checking: state.checking,
    roundTripMs: state.roundTripMs,
    refresh,
  };
}
