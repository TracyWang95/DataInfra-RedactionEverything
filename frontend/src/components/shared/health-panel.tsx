/**
 * Service health status panel for the sidebar footer.
 * Styled for dark sidebar context — uses opacity-based coloring.
 */
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
    <div className="rounded-[18px] border border-white/[0.08] bg-white/[0.04] px-3 py-3 backdrop-blur-xl" data-testid="health-panel">
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={cn('h-1.5 w-1.5 rounded-full', {
              'bg-white/30 animate-pulse': checking,
              'bg-emerald-400': !checking && health?.all_online,
              'bg-amber-400': !checking && health && !health.all_online,
              'bg-red-400': !checking && !health,
            })}
          />
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] opacity-60">{t('health.title')}</span>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-full p-1 opacity-40 transition-opacity hover:bg-white/[0.05] hover:opacity-80"
          title={t('health.refreshTitle')}
          data-testid="health-refresh"
        >
          <RefreshCw className={cn('w-3 h-3', checking && 'animate-spin')} />
        </button>
      </div>

      {health ? (
        <div className="space-y-2 text-[10px]">
          <ServiceRow name={health.services.paddle_ocr.name} status={health.services.paddle_ocr.status} t={t} />
          <ServiceRow name={health.services.has_ner.name} status={health.services.has_ner.status} t={t} />
          <ServiceRow name={health.services.has_image.name} status={health.services.has_image.status} t={t} />

          <div className="mt-1 space-y-0.5 border-t border-white/[0.06] pt-2 pl-0.5 text-[9px] leading-snug opacity-30">
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
                : <span className="opacity-50">{t('health.gpuNotDetected')}</span>}
            </p>
            {health.checked_at && (
              <p className="opacity-50 break-all">
                {t('health.probeTime')} {new Date(health.checked_at).toLocaleString()}
              </p>
            )}
          </div>
        </div>
      ) : (
        <div className="text-[10px] text-red-400">
          {checking ? t('health.detecting') : t('health.backendDown')}
        </div>
      )}
    </div>
  );
}

function ServiceRow({ name, status, t }: { name: string; status: string; t: (key: string) => string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="truncate opacity-50" title={name}>{name}</span>
      <span className={cn('shrink-0 rounded-full px-2 py-0.5 font-medium', status === 'online' ? 'bg-emerald-500/12 text-emerald-300' : 'bg-red-500/12 text-red-300')}>
        {status === 'online' ? t('health.online') : t('health.offline')}
      </span>
    </div>
  );
}
