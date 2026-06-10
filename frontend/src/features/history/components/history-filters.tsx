// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Download, RefreshCw, SlidersHorizontal, Trash2 } from 'lucide-react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { DateFilter, FileTypeFilter, SourceTab, StatusFilter } from '../hooks/use-history';

type HistoryFilterMetrics = {
  totalFiles: number;
  redactedFiles: number;
  awaitingReviewFiles: number;
  entitySum: number;
  sizeLabel: string;
};

type HistoryFilterMenuProps = {
  sourceTab: SourceTab;
  onSourceTabChange: (tab: SourceTab) => void;
  dateFilter: DateFilter;
  onDateFilterChange: (value: DateFilter) => void;
  fileTypeFilter: FileTypeFilter;
  onFileTypeFilterChange: (value: FileTypeFilter) => void;
  statusFilter: StatusFilter;
  onStatusFilterChange: (value: StatusFilter) => void;
  hasActiveFilter: boolean;
  onClearFilters: () => void;
};

interface HistoryFiltersProps {
  sourceTab: SourceTab;
  onSourceTabChange: (tab: SourceTab) => void;
  dateFilter: DateFilter;
  onDateFilterChange: (value: DateFilter) => void;
  fileTypeFilter: FileTypeFilter;
  onFileTypeFilterChange: (value: FileTypeFilter) => void;
  statusFilter: StatusFilter;
  onStatusFilterChange: (value: StatusFilter) => void;
  hasActiveFilter: boolean;
  onClearFilters: () => void;
  onRefresh: () => void;
  onCleanup: () => void;
  onDownloadOriginal: () => void;
  onDownloadRedacted: () => void;
  refreshing: boolean;
  loading: boolean;
  tableBusy?: boolean;
  zipLoading: boolean;
  hasSelection: boolean;
  metrics: HistoryFilterMetrics;
  showFilterMenu?: boolean;
}

export function HistoryFilterMenu({
  sourceTab,
  onSourceTabChange,
  dateFilter,
  onDateFilterChange,
  fileTypeFilter,
  onFileTypeFilterChange,
  statusFilter,
  onStatusFilterChange,
  hasActiveFilter,
  onClearFilters,
}: HistoryFilterMenuProps) {
  const t = useT();
  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);
  const filterTabsListClass = 'h-8 w-full rounded-lg border border-border/70 bg-muted/55 p-0.5';
  const filterTabClass =
    'flex-1 rounded-md border border-transparent px-2 py-1 text-xs text-muted-foreground transition-colors data-[state=active]:bg-foreground data-[state=active]:font-semibold data-[state=active]:text-background data-[state=active]:shadow-sm data-[state=active]:ring-1 data-[state=active]:ring-inset data-[state=active]:ring-foreground/45';

  useEffect(() => {
    if (!filterOpen) return;

    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!filterRef.current?.contains(event.target as Node)) {
        setFilterOpen(false);
      }
    };

    document.addEventListener('mousedown', closeOnOutsideClick);
    return () => document.removeEventListener('mousedown', closeOnOutsideClick);
  }, [filterOpen]);

  return (
    <div className="relative flex shrink-0 flex-nowrap items-center gap-1.5" ref={filterRef}>
      <Button
        variant={hasActiveFilter ? 'default' : 'outline'}
        size="sm"
        className="h-8 shrink-0 rounded-lg px-2.5 text-xs whitespace-nowrap"
        onClick={() => setFilterOpen((open) => !open)}
        data-testid="history-filter-menu"
        aria-expanded={filterOpen}
      >
        <SlidersHorizontal data-icon="inline-start" />
        {t('history.filters.kicker')}
      </Button>

      <div
        className="absolute right-0 top-9 z-[80] w-[390px] rounded-xl border border-border bg-popover p-3 shadow-[var(--shadow-lg)]"
        hidden={!filterOpen}
        data-testid="history-filter-popover"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="grid gap-2">
          <FilterGroup label={t('history.sourceLabel')}>
            <Tabs
              value={sourceTab}
              onValueChange={(value) => onSourceTabChange(value as SourceTab)}
              data-testid="history-source-tabs"
            >
              <TabsList className={filterTabsListClass}>
                <TabsTrigger
                  value="all"
                  className={filterTabClass}
                  data-testid="source-tab-all"
                >
                  {t('history.tab.all')}
                </TabsTrigger>
                <TabsTrigger
                  value="playground"
                  className={filterTabClass}
                  data-testid="source-tab-playground"
                >
                  {t('history.tab.playground')}
                </TabsTrigger>
                <TabsTrigger
                  value="batch"
                  className={filterTabClass}
                  data-testid="source-tab-batch"
                >
                  {t('history.tab.batch')}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </FilterGroup>

          <FilterGroup label={t('history.dateLabel')}>
            <Tabs
              value={dateFilter}
              onValueChange={(value) => onDateFilterChange(value as DateFilter)}
              data-testid="history-date-filter"
            >
              <TabsList className={filterTabsListClass}>
                <TabsTrigger value="all" className={filterTabClass}>
                  {t('history.filter.all')}
                </TabsTrigger>
                <TabsTrigger value="7d" className={filterTabClass}>
                  {t('history.filter.last7d')}
                </TabsTrigger>
                <TabsTrigger value="30d" className={filterTabClass}>
                  {t('history.filter.last30d')}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </FilterGroup>

          <FilterGroup label={t('history.typeLabel')}>
            <Tabs
              value={fileTypeFilter}
              onValueChange={(value) => onFileTypeFilterChange(value as FileTypeFilter)}
              data-testid="history-type-filter"
            >
              <TabsList className={filterTabsListClass}>
                <TabsTrigger value="all" className={filterTabClass}>
                  {t('history.filter.allTypes')}
                </TabsTrigger>
                <TabsTrigger value="word" className={filterTabClass}>
                  {t('file.word')}
                </TabsTrigger>
                <TabsTrigger value="pdf" className={filterTabClass}>
                  {t('file.pdf')}
                </TabsTrigger>
                <TabsTrigger value="image" className={filterTabClass}>
                  {t('history.filter.image')}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </FilterGroup>

          <FilterGroup label={t('history.statusLabel')}>
            <Tabs
              value={statusFilter}
              onValueChange={(value) => onStatusFilterChange(value as StatusFilter)}
              data-testid="history-status-filter"
            >
              <TabsList className={filterTabsListClass}>
                <TabsTrigger value="all" className={filterTabClass}>
                  {t('history.filter.allStatus')}
                </TabsTrigger>
                <TabsTrigger value="redacted" className={filterTabClass}>
                  {t('history.filter.redacted')}
                </TabsTrigger>
                <TabsTrigger value="awaiting_review" className={filterTabClass}>
                  {t('job.status.awaiting_review')}
                </TabsTrigger>
                <TabsTrigger value="unredacted" className={filterTabClass}>
                  {t('history.filter.unredacted')}
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </FilterGroup>
        </div>

        {hasActiveFilter && (
          <div className="mt-2 flex justify-end border-t border-border/70 pt-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 rounded-lg px-2 text-xs whitespace-nowrap"
              onClick={onClearFilters}
              data-testid="clear-filters"
            >
              {t('history.clearFilter')}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function FilterGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-2">
      <div className="truncate text-[11px] font-medium text-muted-foreground">{label}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function HistoryFilters({
  sourceTab,
  onSourceTabChange,
  dateFilter,
  onDateFilterChange,
  fileTypeFilter,
  onFileTypeFilterChange,
  statusFilter,
  onStatusFilterChange,
  hasActiveFilter,
  onClearFilters,
  onRefresh,
  onCleanup,
  onDownloadOriginal,
  onDownloadRedacted,
  refreshing,
  loading,
  tableBusy = false,
  zipLoading,
  hasSelection,
  metrics,
  showFilterMenu = true,
}: HistoryFiltersProps) {
  const t = useT();

  return (
    <section className="saas-panel relative z-30 mb-2 grid shrink-0 gap-2.5 overflow-visible rounded-[20px] border-border/70 bg-card/95 p-2.5 shadow-[var(--shadow-control)] xl:grid-cols-[minmax(260px,0.7fr)_minmax(340px,1fr)_auto] xl:items-center 2xl:p-3">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex min-w-0 flex-nowrap items-center gap-x-2">
          <span className="saas-kicker inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap !px-2 !py-1">
            <SlidersHorizontal className="h-3.5 w-3.5" />
            {t('history.filters.kicker')}
          </span>
          <h2 className="page-title truncate text-base">{t('history.filters.title')}</h2>
        </div>
        <p className="page-copy truncate text-xs leading-4">{t('history.filters.desc')}</p>
      </div>

      <div className="grid min-w-0 grid-cols-2 gap-1.5 sm:grid-cols-4">
        <MetricPill label={t('history.metric.total')} value={metrics.totalFiles} />
        <MetricPill label={t('history.metric.redacted')} value={metrics.redactedFiles} />
        <MetricPill label={t('history.metric.awaitingReview')} value={metrics.awaitingReviewFiles} />
        <MetricPill label={t('history.metric.entities')} value={metrics.entitySum} />
      </div>

      <div className="control-cluster min-w-0 !flex-nowrap justify-start overflow-visible pb-0 xl:justify-end">
        {showFilterMenu && (
          <HistoryFilterMenu
            sourceTab={sourceTab}
            onSourceTabChange={onSourceTabChange}
            dateFilter={dateFilter}
            onDateFilterChange={onDateFilterChange}
            fileTypeFilter={fileTypeFilter}
            onFileTypeFilterChange={onFileTypeFilterChange}
            statusFilter={statusFilter}
            onStatusFilterChange={onStatusFilterChange}
            hasActiveFilter={hasActiveFilter}
            onClearFilters={onClearFilters}
          />
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={refreshing || loading || tableBusy}
          onClick={onRefresh}
          data-testid="history-refresh"
          className="h-8 min-w-[7.5rem] shrink-0 justify-center rounded-lg px-2.5 text-xs whitespace-nowrap"
          title={t('jobs.refreshTitle')}
        >
          <RefreshCw data-icon="inline-start" className={cn(refreshing && 'animate-spin')} />
          {refreshing ? t('jobs.refreshing') : t('jobs.clickRefresh')}
        </Button>

        <Button
          variant="outline"
          size="sm"
          className="h-8 shrink-0 rounded-lg border-destructive/25 px-2.5 text-xs whitespace-nowrap text-destructive hover:bg-destructive/10"
          onClick={onCleanup}
          data-testid="history-cleanup"
          title={t('history.cleanupButton')}
          aria-label={t('history.cleanupButton')}
        >
          <Trash2 data-icon="inline-start" />
          {t('history.cleanupButton')}
        </Button>

        <Button
          size="sm"
          disabled={zipLoading || !hasSelection || loading}
          onClick={onDownloadOriginal}
          data-testid="download-original-zip"
          aria-busy={zipLoading}
          title={t('history.downloadOriginalZip')}
          aria-label={t('history.downloadOriginalZip')}
          className="h-8 shrink-0 rounded-lg px-2.5 text-xs whitespace-nowrap"
        >
          <Download data-icon="inline-start" className={cn(zipLoading && 'animate-pulse')} />
          {t('history.downloadOriginalZipShort')}
        </Button>

        <Button
          variant="outline"
          size="sm"
          disabled={zipLoading || !hasSelection || loading}
          onClick={onDownloadRedacted}
          data-testid="download-redacted-zip"
          aria-busy={zipLoading}
          title={t('history.downloadRedactedZip')}
          aria-label={t('history.downloadRedactedZip')}
          className="h-8 shrink-0 rounded-lg px-2.5 text-xs whitespace-nowrap"
        >
          <Download data-icon="inline-start" className={cn(zipLoading && 'animate-pulse')} />
          {t('history.downloadRedactedZipShort')}
        </Button>
      </div>
    </section>
  );
}

function MetricPill({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card/80 px-2 py-1 shadow-[var(--shadow-sm)]">
      <div className="truncate text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div className="truncate text-sm font-semibold leading-4 tabular-nums text-foreground">
        {value}
      </div>
    </div>
  );
}
