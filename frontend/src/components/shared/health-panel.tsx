// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type {
  ServicesHealth,
  ServiceRuntimeMode,
  ServiceStatus,
} from '@/hooks/use-service-health';

interface HealthPanelProps {
  health: ServicesHealth | null;
  checking: boolean;
  roundTripMs: number | null;
  onRefresh: () => void;
}

type ServiceKey = keyof ServicesHealth['services'];

const serviceKeys: ServiceKey[] = ['paddle_ocr', 'has_ner', 'visual_features'];

function serviceDisplayStatus(status: ServiceStatus | 'offline' | 'checking') {
  return status === 'busy' ? 'online' : status;
}

function runtimeModeLabel(mode: ServiceRuntimeMode | undefined, t: (key: string) => string) {
  return mode ? t(`health.runtime.${mode}`) : null;
}

export function HealthPanel({ health, checking, onRefresh }: HealthPanelProps) {
  const t = useT();
  const serviceStatuses = serviceKeys.map((key) =>
    serviceDisplayStatus(health?.services[key]?.status ?? (checking ? 'checking' : 'offline')),
  );
  const textRuntimeMode = health?.services.has_ner.detail?.cpu_fallback_risk
    ? t('health.runtime.cpuRisk')
    : runtimeModeLabel(health?.services.has_ner.detail?.runtime_mode, t);
  const overallTone =
    !health && !checking
      ? 'error'
      : serviceStatuses.some((status) => status === 'offline')
        ? 'error'
        : serviceStatuses.some((status) => status !== 'online')
          ? 'warning'
          : 'success';
  const statusText = checking
    ? t('health.checking')
    : !health
      ? t('health.backendDown')
      : serviceStatuses.some((status) => status === 'offline')
        ? t('health.someOffline')
        : serviceStatuses.some((status) => status === 'degraded')
          ? t('health.someDegraded')
          : t('health.allOnline');
  const statusLine = textRuntimeMode ? `${statusText} - ${textRuntimeMode}` : statusText;

  return (
    <div
      className="rounded-xl border border-sidebar-border bg-sidebar-accent px-3 py-2 text-sidebar-foreground shadow-[var(--shadow-sm)]"
      data-testid="health-panel"
    >
      <div className="flex items-center gap-2">
        <span
          className={cn('h-2.5 w-2.5 shrink-0 rounded-full', {
            'animate-pulse bg-sidebar-foreground/35': checking,
            'bg-[var(--success-foreground)]': overallTone === 'success',
            'bg-[var(--warning-foreground)]': overallTone === 'warning',
            'bg-[var(--error-foreground)]': overallTone === 'error',
          })}
        />
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate text-sm font-semibold">{t('health.sidebar.title')}</p>
          <p className="mt-0.5 truncate text-xs text-sidebar-foreground/55">{statusLine}</p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-sidebar-foreground/60 transition hover:bg-sidebar-primary hover:text-sidebar-foreground"
          title={t('health.refreshTitle')}
          aria-label={t('health.refreshTitle')}
          data-testid="health-refresh"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', checking && 'animate-spin')} />
        </button>
      </div>
    </div>
  );
}
