import { RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import { t } from '@/i18n';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { JobTypeApi } from '@/services/jobsApi';

type PageMetrics = {
  draft: number;
  processing: number;
  awaitingReview: number;
  completed: number;
  risk: number;
};

type JobsFiltersProps = {
  tab: JobTypeApi | 'all';
  onTabChange: (tab: JobTypeApi | 'all') => void;
  onRefresh: () => void;
  onCleanup: () => void;
  refreshing: boolean;
  tableBusy: boolean;
  visibleCount: number;
  metrics: PageMetrics;
};

export function JobsFilters({
  tab,
  onTabChange,
  onRefresh,
  onCleanup,
  refreshing,
  tableBusy,
  visibleCount,
  metrics,
}: JobsFiltersProps) {
  return (
    <section className="saas-panel mb-4 flex shrink-0 flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <span className="saas-kicker inline-flex items-center gap-2">
            <Sparkles className="h-3.5 w-3.5" />
            Operations
          </span>
          <div>
            <h2 className="text-lg font-semibold tracking-[-0.03em] text-foreground">
              Jobs Console
            </h2>
            <p className="text-sm text-muted-foreground">
              Keep the queue, review backlog, and finished runs in one clean control surface.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Tabs value={tab} onValueChange={(value) => onTabChange(value as JobTypeApi | 'all')}>
            <TabsList className="h-auto p-1" data-testid="jobs-tab-list">
              <TabsTrigger value="all" className="px-3 py-1.5 text-xs" data-testid="jobs-tab-all">
                {t('jobs.tab.all')}
              </TabsTrigger>
            </TabsList>
          </Tabs>

          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={tableBusy}
            data-testid="jobs-refresh-btn"
            title={t('jobs.refreshTitle')}
            className="h-9 rounded-xl px-3"
          >
            <RefreshCw data-icon="inline-start" className={refreshing ? 'animate-spin' : ''} />
            {refreshing ? t('jobs.refreshing') : t('jobs.clickRefresh')}
          </Button>

          <Button
            variant="outline"
            size="sm"
            className="h-9 rounded-xl border-destructive/25 text-destructive hover:bg-destructive/10"
            onClick={onCleanup}
            data-testid="jobs-cleanup-btn"
          >
            <Trash2 data-icon="inline-start" />
            Clear Finished
          </Button>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <MetricPill label="Visible" value={visibleCount} />
        <MetricPill label="Draft" value={metrics.draft} />
        <MetricPill label="Running" value={metrics.processing} />
        <MetricPill label="Awaiting Review" value={metrics.awaitingReview} />
        <MetricPill label="Completed" value={metrics.completed} />
        <MetricPill label="Attention Needed" value={metrics.risk} tone="alert" />
      </div>
    </section>
  );
}

function MetricPill({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: number;
  tone?: 'default' | 'alert';
}) {
  return (
    <div className="rounded-2xl border border-border/70 bg-muted/35 px-3 py-3">
      <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </div>
      <div className={tone === 'alert' ? 'mt-1 text-lg font-semibold text-destructive' : 'mt-1 text-lg font-semibold text-foreground'}>
        {value}
      </div>
    </div>
  );
}
