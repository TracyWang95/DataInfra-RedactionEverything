import { Download, RefreshCw, SlidersHorizontal, Trash2 } from 'lucide-react';
import { t } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { PAGE_SIZE_OPTIONS } from '../hooks/use-history';
import type { DateFilter, FileTypeFilter, SourceTab, StatusFilter } from '../hooks/use-history';

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
  zipLoading: boolean;
  hasSelection: boolean;
  pageSize: number;
  onPageSizeChange: (pageSize: number) => void;
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
  zipLoading,
  hasSelection,
  pageSize,
  onPageSizeChange,
}: HistoryFiltersProps) {
  return (
    <section className="saas-panel mb-4 flex shrink-0 flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <span className="saas-kicker inline-flex items-center gap-2">
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Filters
          </span>
          <div>
            <h2 className="text-lg font-semibold tracking-[-0.03em] text-foreground">
              Delivery History
            </h2>
            <p className="text-sm text-muted-foreground">
              Review completed files, compare outputs, and export clean bundles without leaving the page.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={refreshing || loading}
            onClick={onRefresh}
            data-testid="history-refresh"
            className="h-9 rounded-xl px-3"
          >
            <RefreshCw data-icon="inline-start" className={cn(refreshing && 'animate-spin')} />
            {t('history.refresh')}
          </Button>

          <Button
            variant="outline"
            size="sm"
            className="h-9 rounded-xl border-destructive/30 text-destructive hover:bg-destructive/10"
            onClick={onCleanup}
            data-testid="history-cleanup"
          >
            <Trash2 data-icon="inline-start" />
            Clear History
          </Button>

          <Button
            size="sm"
            disabled={zipLoading || !hasSelection || loading}
            onClick={onDownloadOriginal}
            data-testid="download-original-zip"
            className="h-9 rounded-xl px-3"
          >
            <Download data-icon="inline-start" />
            {zipLoading ? t('history.packing') || 'Preparing...' : t('history.downloadOriginalZip') || 'Original ZIP'}
          </Button>

          <Button
            variant="outline"
            size="sm"
            disabled={zipLoading || !hasSelection || loading}
            onClick={onDownloadRedacted}
            data-testid="download-redacted-zip"
            className="h-9 rounded-xl px-3"
          >
            <Download data-icon="inline-start" />
            {zipLoading ? t('history.packing') || 'Preparing...' : t('history.downloadRedactedZip') || 'Redacted ZIP'}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Tabs value={sourceTab} onValueChange={(value) => onSourceTabChange(value as SourceTab)} data-testid="history-source-tabs">
          <TabsList className="h-auto p-1">
            <TabsTrigger value="all" className="px-3 py-1.5 text-xs" data-testid="source-tab-all">
              {t('history.tab.all')}
            </TabsTrigger>
            <TabsTrigger value="playground" className="px-3 py-1.5 text-xs" data-testid="source-tab-playground">
              Playground
            </TabsTrigger>
            <TabsTrigger value="batch" className="px-3 py-1.5 text-xs" data-testid="source-tab-batch">
              {t('history.tab.batch')}
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <Tabs value={dateFilter} onValueChange={(value) => onDateFilterChange(value as DateFilter)} data-testid="history-date-filter">
          <TabsList className="h-auto p-1">
            <TabsTrigger value="all" className="px-3 py-1.5 text-xs">{t('history.filter.all')}</TabsTrigger>
            <TabsTrigger value="7d" className="px-3 py-1.5 text-xs">{t('history.filter.last7d')}</TabsTrigger>
            <TabsTrigger value="30d" className="px-3 py-1.5 text-xs">{t('history.filter.last30d')}</TabsTrigger>
          </TabsList>
        </Tabs>

        <Select value={fileTypeFilter} onValueChange={(value) => onFileTypeFilterChange(value as FileTypeFilter)}>
          <SelectTrigger className="h-10 min-w-[118px] rounded-xl text-xs" data-testid="history-type-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('history.filter.allTypes')}</SelectItem>
            <SelectItem value="word">Word</SelectItem>
            <SelectItem value="pdf">PDF</SelectItem>
            <SelectItem value="image">{t('history.filter.image')}</SelectItem>
          </SelectContent>
        </Select>

        <Select value={statusFilter} onValueChange={(value) => onStatusFilterChange(value as StatusFilter)}>
          <SelectTrigger className="h-10 min-w-[138px] rounded-xl text-xs" data-testid="history-status-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('history.filter.allStatus')}</SelectItem>
            <SelectItem value="redacted">{t('history.filter.redacted')}</SelectItem>
            <SelectItem value="awaiting_review">{t('job.status.awaiting_review')}</SelectItem>
            <SelectItem value="unredacted">{t('history.filter.unredacted')}</SelectItem>
          </SelectContent>
        </Select>

        {hasActiveFilter && (
          <Button variant="ghost" size="sm" className="h-10 rounded-xl px-3 text-xs" onClick={onClearFilters} data-testid="clear-filters">
            {t('history.clearFilter') || 'Clear Filters'}
          </Button>
        )}

        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <span>{t('history.perPage') || 'Per page'}</span>
          <Select value={String(pageSize)} onValueChange={(value) => onPageSizeChange(Number(value))}>
            <SelectTrigger className="h-10 min-w-[92px] rounded-xl text-xs" data-testid="page-size-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {option} {t('history.itemsUnit') || 'items'}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </section>
  );
}
