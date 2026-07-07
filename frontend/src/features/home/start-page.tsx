// Copyright 2026 DataInfra-RedactionEverything Contributors

import { Link } from 'react-router-dom';
import {
  ArrowRight,
  CheckCircle2,
  Download,
  FileCheck2,
  History,
  ListChecks,
  Play,
  RefreshCw,
  Search,
  Upload,
} from 'lucide-react';
import { useT } from '@/i18n';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { useServiceHealth, type ServicesHealth } from '@/hooks/use-service-health';
import { buildPreviewBatchRoute } from '@/features/batch/lib/batch-preview-fixtures';
import { hasAnyBatchModeReady } from '@/features/batch/lib/batch-mode-readiness';

export function StartPage() {
  const t = useT();
  const { health, checking, roundTripMs, refresh } = useServiceHealth();
  const liveAvailable = hasAnyBatchModeReady(health, checking);
  const liveReady = Boolean(health?.all_online && !checking);
  const backendDown = Boolean(!health && !checking);
  const degraded = Boolean(health && !health.all_online && !checking);
  const liveBlockedReason = liveAvailable
    ? null
    : backendDown
      ? t('batchHub.liveDisabledBackend')
      : degraded
        ? t('batchHub.liveDisabledModels')
        : t('start.pathDesc.checking');

  return (
    <div className="saas-page flex h-full min-h-0 overflow-hidden bg-background">
      <div className="page-shell-narrow !max-w-[118rem] !px-3 !py-3 sm:!px-5 2xl:!max-w-[124rem]">
        <div className="page-stack gap-3 overflow-hidden">
          <section className="flex flex-none flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <span className="saas-kicker">{t('start.kicker')}</span>
              <h1
                className="text-2xl font-semibold tracking-tight text-foreground"
                data-testid="start-title"
              >
                {t('start.title')}
              </h1>
              <p className="max-w-3xl text-sm leading-6 text-muted-foreground">{t('start.desc')}</p>
            </div>
            <Button variant="outline" size="sm" className="rounded-xl" onClick={refresh}>
              <RefreshCw className={cn('mr-2 size-4', checking && 'animate-spin')} />
              {t('start.refreshServices')}
            </Button>
          </section>

          <section className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_24rem] 2xl:grid-cols-[minmax(0,1fr)_25rem]">
            <SingleFileActionCard />
            <aside className="grid min-h-0 content-start gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <ServiceReadinessCard
                health={health}
                checking={checking}
                liveReady={liveReady}
                backendDown={backendDown}
                roundTripMs={roundTripMs}
                onRefresh={refresh}
              />
              <LiveBatchActionCard
                liveAvailable={liveAvailable}
                liveBlockedReason={liveBlockedReason}
              />
              <ResultsAndTasksActionCard />
            </aside>
          </section>
        </div>
      </div>
    </div>
  );
}

const workflowSteps = [
  {
    key: 'upload',
    Icon: Upload,
    markerClass: 'bg-[var(--success-surface)] text-[var(--success-foreground)]',
    dotClass: 'bg-[var(--success-foreground)]',
  },
  {
    key: 'recognize',
    Icon: Search,
    markerClass: 'bg-muted text-foreground',
    dotClass: 'bg-foreground',
  },
  {
    key: 'review',
    Icon: CheckCircle2,
    markerClass: 'bg-[var(--warning-surface)] text-[var(--warning-foreground)]',
    dotClass: 'bg-[var(--warning-foreground)]',
  },
  {
    key: 'export',
    Icon: Download,
    markerClass: 'bg-foreground text-background',
    dotClass: 'bg-background',
  },
] as const;

function WorkflowDemoCard() {
  const t = useT();

  return (
    <div
      className="flex min-h-0 flex-1 flex-col rounded-[20px] border border-border/70 bg-background/80 p-4 sm:p-5"
      data-testid="start-workflow-demo"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="saas-kicker">{t('start.workflow.kicker')}</span>
          <h3 className="mt-2 text-lg font-semibold">{t('start.workflow.title')}</h3>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            {t('start.workflow.desc')}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{t('start.workflow.badge.singleFirst')}</Badge>
          <Badge variant="outline">{t('start.workflow.badge.noMedia')}</Badge>
        </div>
      </div>
      <div className="relative flex min-h-0 flex-1 items-stretch">
        <div className="absolute bottom-10 left-8 top-10 hidden w-px bg-border lg:block" />
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-rows-4">
          {workflowSteps.map(({ key, Icon, markerClass, dotClass }, index) => (
            <div
              key={key}
              className="relative grid min-h-[5rem] grid-cols-[2.75rem_minmax(0,1fr)] items-start gap-3 rounded-[20px] border border-border/60 bg-[var(--surface-control-muted)] px-4 py-4 lg:bg-transparent"
            >
              <div
                className={cn(
                  'relative z-10 mt-0.5 flex size-10 items-center justify-center rounded-full shadow-sm',
                  markerClass,
                  index === 1 && 'animate-pulse',
                )}
              >
                <Icon className="size-4" />
              </div>
              <div className="min-w-0 pt-0.5">
                <div className="flex items-center gap-1.5 leading-none">
                  <span
                    className={cn(
                      'size-1.5 rounded-full',
                      dotClass,
                      index === 2 && 'animate-pulse',
                    )}
                  />
                  <span className="text-xs font-semibold">
                    {t(`start.workflow.step.${key}.title`)}
                  </span>
                </div>
                <p className="mt-1.5 text-sm leading-5 text-muted-foreground">
                  {t(`start.workflow.step.${key}.desc`)}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SingleFileActionCard() {
  const t = useT();

  return (
    <Card className="page-surface h-full border-border/70 shadow-[var(--shadow-md)]">
      <CardContent className="flex min-h-0 flex-1 flex-col gap-5 p-5 sm:p-6">
        <div className="flex flex-none flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 items-start gap-4">
            <span className="flex size-14 shrink-0 items-center justify-center rounded-2xl border border-foreground bg-foreground text-background">
              <Play className="size-6" />
            </span>
            <div className="min-w-0 space-y-2">
              <CardTitle className="text-2xl font-semibold leading-8">
                {t('start.entry.playground.title')}
              </CardTitle>
              <CardDescription className="max-w-3xl text-sm leading-6">
                {t('start.entry.playground.desc')}
              </CardDescription>
            </div>
          </div>
          <Button
            className="h-10 shrink-0 justify-between rounded-xl lg:min-w-56"
            asChild
            data-testid="start-playground"
          >
            <Link to="/single">
              {t('start.entry.playground.cta')}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
        <WorkflowDemoCard />
      </CardContent>
    </Card>
  );
}

function LiveBatchActionCard({
  liveAvailable,
  liveBlockedReason,
}: {
  liveAvailable: boolean;
  liveBlockedReason: string | null;
}) {
  const t = useT();
  const demoRoute = buildPreviewBatchRoute('smart', 1);

  return (
    <Card className="page-surface !flex-none border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="gap-3 px-4 py-3.5">
        <div className="flex items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-border bg-muted text-foreground">
            <ListChecks className="size-4" />
          </span>
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-sm font-semibold">{t('start.batchLive.title')}</CardTitle>
              {!liveAvailable ? (
                <Badge variant="outline">{t('start.batchDemo.title')}</Badge>
              ) : null}
            </div>
            <CardDescription className="text-xs leading-5">
              {t('start.batchLive.desc')}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <Button
          className="h-9 w-full justify-between rounded-xl"
          size="sm"
          disabled={!liveAvailable}
          asChild={liveAvailable}
          data-testid="start-live-batch"
        >
          {liveAvailable ? (
            <Link to="/batch">
              {t('start.batchLive.cta')}
              <ArrowRight className="size-4" />
            </Link>
          ) : (
            <span>
              {t('start.batchLive.blocked')}
              <ArrowRight className="size-4" />
            </span>
          )}
        </Button>
        {liveBlockedReason ? (
          <p
            className="mt-2 text-xs leading-4 text-muted-foreground"
            data-testid="start-live-blocked-reason"
          >
            {liveBlockedReason}
          </p>
        ) : null}
        {!liveAvailable ? (
          <Button
            variant="ghost"
            size="sm"
            className="mt-2 h-9 w-full justify-between rounded-xl"
            asChild
            data-testid="start-demo-batch"
          >
            <Link to={demoRoute}>
              {t('start.batchDemo.cta')}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ResultsAndTasksActionCard() {
  const t = useT();

  return (
    <Card className="page-surface !flex-none border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="gap-3 px-4 py-3.5">
        <div className="flex items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-border bg-muted text-foreground">
            <History className="size-4" />
          </span>
          <div className="min-w-0 space-y-1">
            <CardTitle className="text-sm font-semibold">
              {t('start.entry.history.title')}
            </CardTitle>
            <CardDescription className="text-xs leading-5">
              {t('start.entry.history.desc')}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-2 px-4 pb-4 pt-0 sm:grid-cols-2 xl:grid-cols-1">
        <Button
          className="h-9 w-full justify-between rounded-xl"
          size="sm"
          asChild
          data-testid="start-history"
        >
          <Link to="/history">
            {t('start.entry.history.cta')}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-9 w-full justify-between rounded-xl"
          asChild
          data-testid="start-jobs"
        >
          <Link to="/jobs">
            {t('start.entry.jobs.cta')}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function ServiceReadinessCard({
  health,
  checking,
  liveReady,
  backendDown,
  roundTripMs,
  onRefresh,
}: {
  health: ServicesHealth | null;
  checking: boolean;
  liveReady: boolean;
  backendDown: boolean;
  roundTripMs: number | null;
  onRefresh: () => void;
}) {
  const t = useT();
  const services = health ? Object.values(health.services) : [];
  const readinessMessage = checking
    ? t('start.services.checking')
    : liveReady
      ? t('start.services.allOnline')
      : backendDown
        ? t('start.services.backendDown')
        : t('start.services.needsAction');

  return (
    <Card className="page-surface min-h-0 border-border/70 shadow-[var(--shadow-control)]">
      <CardContent className="flex flex-col gap-4 p-4">
        <div className="flex min-w-0 flex-none items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-border bg-muted text-foreground">
            <FileCheck2 className="size-4" />
          </span>
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-sm font-semibold">{t('start.services.title')}</CardTitle>
              <Badge
                variant={liveReady ? 'default' : 'outline'}
                data-testid="start-live-state"
              >
                {checking
                  ? t('start.state.checking')
                  : liveReady
                    ? t('start.state.liveReady')
                    : backendDown
                      ? t('start.state.backendDown')
                      : t('start.state.modelLimited')}
              </Badge>
              {roundTripMs != null ? (
                <span className="text-xs text-muted-foreground">
                  {t('health.frontendRoundTrip')} {roundTripMs} ms
                </span>
              ) : null}
            </div>
            <CardDescription className="text-xs leading-5">{readinessMessage}</CardDescription>
          </div>
        </div>

        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
          {services.map((service) => {
            const displayStatus = service.status === 'busy' ? 'online' : service.status;

            return (
              <span
                key={service.name}
                className={cn(
                  'block min-w-0 max-w-full truncate rounded-full border px-2.5 py-1 text-xs font-medium',
                  displayStatus === 'online' &&
                    'border-[var(--success-border)] bg-[var(--success-surface)] text-[var(--success-foreground)]',
                  displayStatus === 'degraded' &&
                    'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]',
                  displayStatus !== 'online' &&
                    displayStatus !== 'degraded' &&
                    'border-[var(--error-border)] bg-[var(--error-surface)] text-[var(--error-foreground)]',
                )}
                title={service.name}
              >
                {service.name}
              </span>
            );
          })}
          {services.length === 0 ? (
            <span className="text-xs text-muted-foreground">
              {checking ? t('health.detecting') : t('health.backendDown')}
            </span>
          ) : null}
        </div>
        <div className="flex justify-end">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="rounded-xl px-2"
            onClick={onRefresh}
            aria-label={t('start.refreshServices')}
          >
            <RefreshCw className={cn('size-4', checking && 'animate-spin')} />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
