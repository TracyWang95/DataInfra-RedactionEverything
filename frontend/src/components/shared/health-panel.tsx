// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type { ServicesHealth } from '@/hooks/use-service-health';

interface HealthPanelProps {
  health: ServicesHealth | null;
  checking: boolean;
  roundTripMs: number | null;
  onRefresh: () => void;
}

export function HealthPanel({ health, checking, roundTripMs, onRefresh }: HealthPanelProps) {
  const t = useT();

  return (
    <div className="rounded-[18px] border border-sidebar-border bg-sidebar-accent px-3 py-3 text-sidebar-foreground backdrop-blur-xl" data-testid="health-panel">
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={cn('h-1.5 w-1.5 rounded-full', {
              'animate-pulse bg-sidebar-foreground/30': checking,
              'bg-[var(--success-foreground)]': !checking && health?.all_online,
              'bg-[var(--warning-foreground)]': !checking && health && !health.all_online,
              'bg-[var(--error-foreground)]': !checking && !health,
            })}
          />
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/65">{t('health.title')}</span>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-full p-1 text-sidebar-foreground/55 transition hover:bg-sidebar-primary hover:text-sidebar-foreground"
          title={t('health.refreshTitle')}
          data-testid="health-refresh"
        >
          <RefreshCw className={cn('h-3 w-3', checking && 'animate-spin')} />
        </button>
      </div>

      {health ? (
        <div className="space-y-2.5 text-[11px]">
          <ServiceRow name={health.services.paddle_ocr.name} status={health.services.paddle_ocr.status} t={t} />
          <ServiceRow name={health.services.has_ner.name} status={health.services.has_ner.status} t={t} />
          <ServiceRow name={health.services.has_image.name} status={health.services.has_image.status} t={t} />

          <div className="mt-1 space-y-1 border-t border-sidebar-border pt-2 pl-0.5 text-[10px] leading-snug text-sidebar-foreground/50">
            {typeof health.probe_ms === 'number' && (
              <p className="truncate">{t('health.backendProbe')} {health.probe_ms} ms</p>
            )}
            {roundTripMs != null && (
              <p className="truncate">{t('health.frontendRoundTrip')} {roundTripMs} ms</p>
            )}
            <p className="truncate">
              {t('health.gpuMemory')}{' '}
              {health.gpu_memory
                ? `${health.gpu_memory.used_mb} / ${health.gpu_memory.total_mb} MiB`
                : <span className="text-sidebar-foreground/45">{t('health.gpuNotDetected')}</span>}
            </p>
            {health.checked_at && (
              <p className="break-all text-sidebar-foreground/45">
                {t('health.probeTime')} {new Date(health.checked_at).toLocaleString()}
              </p>
            )}
          </div>
        </div>
      ) : (
        <div className="text-[11px] text-[var(--error-foreground)]">
          {checking ? t('health.detecting') : t('health.backendDown')}
        </div>
      )}
    </div>
  );
}

function ServiceRow({ name, status, t }: { name: string; status: string; t: (key: string) => string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="truncate text-sidebar-foreground/58" title={name}>{name}</span>
      <span
        className={cn(
          'shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium',
          status === 'online'
            ? 'border-[var(--success-border)] bg-[var(--success-surface)] text-[var(--success-foreground)]'
            : 'border-[var(--error-border)] bg-[var(--error-surface)] text-[var(--error-foreground)]',
        )}
      >
        {status === 'online' ? t('health.online') : t('health.offline')}
      </span>
    </div>
  );
}
