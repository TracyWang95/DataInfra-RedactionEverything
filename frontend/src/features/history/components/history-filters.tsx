import { RefreshCw, Trash2, Download } from 'lucide-react';
import { t } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { PAGE_SIZE_OPTIONS } from '../hooks/use-history';
import type { SourceTab, DateFilter, FileTypeFilter, StatusFilter } from '../hooks/use-history';

interface HistoryFiltersProps {
  sourceTab: SourceTab;
  onSourceTabChange: (tab: SourceTab) => void;
  dateFilter: DateFilter;
  onDateFilterChange: (v: DateFilter) => void;
  fileTypeFilter: FileTypeFilter;
  onFileTypeFilterChange: (v: FileTypeFilter) => void;
  statusFilter: StatusFilter;
  onStatusFilterChange: (v: StatusFilter) => void;
  hasActiveFilter: boolean;
  onClearFilters: () => void;
  /* action bar */
  onRefresh: () => void;
  onCleanup: () => void;
  onDownloadOriginal: () => void;
  onDownloadRedacted: () => void;
  refreshing: boolean;
  loading: boolean;
  zipLoading: boolean;
  hasSelection: boolean;
  pageSize: number;
  onPageSizeChange: (ps: number) => void;
}

export function HistoryFilters({
  sourceTab, onSourceTabChange,
  dateFilter, onDateFilterChange,
  fileTypeFilter, onFileTypeFilterChange,
  statusFilter, onStatusFilterChange,
  hasActiveFilter, onClearFilters,
  onRefresh, onCleanup, onDownloadOriginal, onDownloadRedacted,
  refreshing, loading, zipLoading, hasSelection,
  pageSize, onPageSizeChange,
}: HistoryFiltersProps) {
  return (
    <>
      {/* Row 1: Source tab + secondary filters */}
      <div className="flex flex-wrap items-center gap-2 mb-3 flex-shrink-0">
        <Tabs
          value={sourceTab}
          onValueChange={v => onSourceTabChange(v as SourceTab)}
          data-testid="history-source-tabs"
        >
          <TabsList className="h-8">
            <TabsTrigger value="all" className="text-xs px-2.5" data-testid="source-tab-all">
              {t('history.tab.all')}
            </TabsTrigger>
            <TabsTrigger value="playground" className="text-xs px-2.5" data-testid="source-tab-playground">
              Playground
            </TabsTrigger>
            <TabsTrigger value="batch" className="text-xs px-2.5" data-testid="source-tab-batch">
              {t('history.tab.batch')}
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <span className="w-px h-5 bg-border" />

        <Tabs
          value={dateFilter}
          onValueChange={v => onDateFilterChange(v as DateFilter)}
          data-testid="history-date-filter"
        >
          <TabsList className="h-8">
            <TabsTrigger value="all" className="text-xs px-2.5">{t('history.filter.all')}</TabsTrigger>
            <TabsTrigger value="7d" className="text-xs px-2.5">{t('history.filter.last7d')}</TabsTrigger>
            <TabsTrigger value="30d" className="text-xs px-2.5">{t('history.filter.last30d')}</TabsTrigger>
          </TabsList>
        </Tabs>

        <Select value={fileTypeFilter} onValueChange={v => onFileTypeFilterChange(v as FileTypeFilter)}>
          <SelectTrigger className="h-8 w-auto min-w-[90px] text-xs" data-testid="history-type-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('history.filter.allTypes')}</SelectItem>
            <SelectItem value="word">Word</SelectItem>
            <SelectItem value="pdf">PDF</SelectItem>
            <SelectItem value="image">{t('history.filter.image')}</SelectItem>
          </SelectContent>
        </Select>

        <Select value={statusFilter} onValueChange={v => onStatusFilterChange(v as StatusFilter)}>
          <SelectTrigger className="h-8 w-auto min-w-[90px] text-xs" data-testid="history-status-filter">
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
          <Button variant="ghost" size="sm" className="text-xs h-8" onClick={onClearFilters} data-testid="clear-filters">
            {t('history.clearFilter')}
          </Button>
        )}
      </div>

      {/* Row 2: Action buttons + page size */}
      <div className="flex flex-wrap items-center gap-2 mb-3 flex-shrink-0">
        <Button
          variant="outline" size="sm"
          disabled={refreshing || loading}
          onClick={onRefresh}
          data-testid="history-refresh"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
          {t('history.refresh')}
        </Button>

        <Button
          variant="outline" size="sm"
          className="border-destructive/30 text-destructive hover:bg-destructive/10"
          onClick={onCleanup}
          data-testid="history-cleanup"
        >
          <Trash2 className="h-3.5 w-3.5" />
          一键清空
        </Button>

        <Button
          size="sm"
          disabled={zipLoading || !hasSelection || loading}
          onClick={onDownloadOriginal}
          data-testid="download-original-zip"
        >
          <Download className="h-3.5 w-3.5" />
          {zipLoading ? t('history.packing') : t('history.downloadOriginalZip')}
        </Button>

        <Button
          variant="outline" size="sm"
          disabled={zipLoading || !hasSelection || loading}
          onClick={onDownloadRedacted}
          data-testid="download-redacted-zip"
        >
          <Download className="h-3.5 w-3.5" />
          {zipLoading ? t('history.packing') : t('history.downloadRedactedZip')}
        </Button>

        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <span>{t('history.perPage')}</span>
          <Select value={String(pageSize)} onValueChange={v => onPageSizeChange(Number(v))}>
            <SelectTrigger className="h-8 w-auto min-w-[70px] text-xs" data-testid="page-size-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map(n => (
                <SelectItem key={n} value={String(n)}>
                  {n} {t('history.itemsUnit')}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </>
  );
}
