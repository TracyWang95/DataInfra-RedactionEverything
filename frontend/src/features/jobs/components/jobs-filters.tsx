// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import { useT } from '@/i18n';
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
  const t = useT();

  return (
    <section className="saas-panel mb-3 flex shrink-0 flex-col gap-3.5 p-3.5 sm:p-4">
      <div className="flex flex-col gap-2.5 lg:flex-row lg:items-start lg:justify-between">
        <div className="page-section-heading">
          <span className="saas-kicker inline-flex items-center gap-2">
            <Sparkles className="h-3.5 w-3.5" />
            {t('jobs.filters.kicker')}
          </span>
          <div className="page-section-heading">
            <h2 className="page-title text-lg">
              {t('jobs.filters.title')}
            </h2>
            <p className="page-copy">
              {t('jobs.filters.desc')}
            </p>
          </div>
        </div>

        <div className="control-cluster">
          <Tabs value={tab} onValueChange={(value) => onTabChange(value as JobTypeApi | 'all')}>
            <TabsList className="h-auto rounded-xl border border-border/70 bg-muted/45 p-1" data-testid="jobs-tab-list">
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
            {t('jobs.cleanupButton')}
          </Button>
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-3 2xl:grid-cols-6">
        <MetricPill label={t('jobs.metric.visible')} value={visibleCount} />
        <MetricPill label={t('jobs.metric.draft')} value={metrics.draft} />
        <MetricPill label={t('jobs.metric.running')} value={metrics.processing} />
        <MetricPill label={t('jobs.metric.awaitingReview')} value={metrics.awaitingReview} />
        <MetricPill label={t('jobs.metric.completed')} value={metrics.completed} />
        <MetricPill label={t('jobs.metric.attention')} value={metrics.risk} tone="alert" />
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
    <div className="metric-card">
      <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </div>
      <div className={tone === 'alert' ? 'mt-1 text-lg font-semibold text-destructive' : 'mt-1 text-lg font-semibold text-foreground'}>
        {value}
      </div>
    </div>
  );
}
