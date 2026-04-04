import { t } from '@/i18n';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
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
    <div className="flex flex-wrap items-center gap-2 mb-3 flex-shrink-0">
      <div className="flex items-center gap-1.5">
        <Tabs
          value={tab}
          onValueChange={(v) => onTabChange(v as JobTypeApi | 'all')}
        >
          <TabsList className="h-auto p-0.5" data-testid="jobs-tab-list">
            <TabsTrigger value="all" className="text-xs px-2.5 py-1" data-testid="jobs-tab-all">
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
        >
          {refreshing ? t('jobs.refreshing') : t('jobs.clickRefresh')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="border-red-200 text-red-600 hover:bg-red-50"
          onClick={onCleanup}
          data-testid="jobs-cleanup-btn"
        >
          {'\u4e00\u952e\u6e05\u7a7a'}
        </Button>
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{t('jobs.thisPage').replace('{n}', String(visibleCount))}</span>
        <span className="text-gray-300">|</span>
        <span>{t('jobs.toConfigure').replace('{n}', String(metrics.draft))}</span>
        <span className="text-gray-300">|</span>
        <span>{t('jobs.processing').replace('{n}', String(metrics.processing))}</span>
        <span className="text-gray-300">|</span>
        <span>{t('jobs.awaitingReviewMetric').replace('{n}', String(metrics.awaitingReview))}</span>
        <span className="text-gray-300">|</span>
        <span>{t('jobs.completedMetric').replace('{n}', String(metrics.completed))}</span>
        <span className="text-gray-300">|</span>
        <span>{t('jobs.abnormalMetric').replace('{n}', String(metrics.risk))}</span>
      </div>
    </div>
  );
}
