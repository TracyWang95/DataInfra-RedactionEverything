// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { useCallback, useEffect, useSyncExternalStore } from 'react';

interface ServiceInfo {
  name: string;
  status: 'online' | 'offline' | 'checking';
}

export interface ServicesHealth {
  all_online: boolean;
  probe_ms?: number;
  checked_at?: string;
  gpu_memory?: { used_mb: number; total_mb: number } | null;
  services: {
    paddle_ocr: ServiceInfo;
    has_ner: ServiceInfo;
    has_image: ServiceInfo;
  };
}

const HEALTH_TIMEOUT_MS = 55_000;
const HEALTH_POLL_INTERVAL_MS = 15_000;

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

function emitHealthChange() {
  listeners.forEach((listener) => listener());
}

function updateSnapshot(next: Partial<HealthStoreSnapshot>) {
  snapshot = { ...snapshot, ...next };
  emitHealthChange();
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
    const t0 = performance.now();
    try {
      // Intentionally uses raw fetch: health endpoint is unauthenticated
      const res = await fetch('/health/services', { signal: ac.signal });
      if (!res.ok) {
        updateSnapshot({ health: null, roundTripMs: null });
        return;
      }
      const data = (await res.json()) as ServicesHealth;
      updateSnapshot({
        health: data,
        roundTripMs: Math.round(performance.now() - t0),
      });
    } catch {
      updateSnapshot({ health: null, roundTripMs: null });
    } finally {
      window.clearTimeout(timer);
      activeFetch = null;
      updateSnapshot({ checking: false });
    }
  })();

  return activeFetch;
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
  }, []);

  const state = useSyncExternalStore(subscribe, () => snapshot, () => initialSnapshot);
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
