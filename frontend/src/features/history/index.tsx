// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useT } from '@/i18n';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { InteractionLockOverlay } from '@/components/InteractionLockOverlay';
import { PaginationRail } from '@/components/PaginationRail';
import { useHistory } from './hooks/use-history';
import { HistoryFilterMenu, HistoryFilters } from './components/history-filters';
import { HistoryTable } from './components/history-table';
import { PAGE_SIZE_OPTIONS } from './hooks/use-history';

export function History() {
  const t = useT();
  const s = useHistory();

  return (
    <div
      className="saas-page flex min-h-0 flex-1 flex-col overflow-hidden bg-background"
      data-testid="history-page"
    >
      <div className="page-shell !max-w-[min(100%,2048px)] !px-3 !py-3 sm:!px-4 2xl:!px-5">
        <HistoryFilters
          sourceTab={s.sourceTab}
          onSourceTabChange={s.changeSourceTab}
          dateFilter={s.dateFilter}
          onDateFilterChange={s.setDateFilter}
          fileTypeFilter={s.fileTypeFilter}
          onFileTypeFilterChange={s.setFileTypeFilter}
          statusFilter={s.statusFilter}
          onStatusFilterChange={s.setStatusFilter}
          hasActiveFilter={s.hasActiveFilter}
          onClearFilters={s.clearFilters}
          onRefresh={() => s.load(true, s.page, s.pageSize)}
          onCleanup={() => s.setCleanupConfirmOpen(true)}
          onDownloadOriginal={() => s.downloadZip(false)}
          onDownloadRedacted={() => s.downloadZip(true)}
          refreshing={s.refreshing}
          loading={s.initialLoading}
          tableBusy={s.tableLoading || s.interactionLocked}
          zipLoading={s.zipLoading}
          hasSelection={s.selectedIds.length > 0}
          showFilterMenu={false}
          metrics={s.statsData}
        />

        {s.msg && (
          <Alert variant={s.msg.tone === 'err' ? 'destructive' : 'default'} className="mb-2">
            <AlertDescription>{s.msg.text}</AlertDescription>
          </Alert>
        )}

        <Card className="page-surface flex min-h-0 flex-1 overflow-visible rounded-[20px] border-border/70 bg-card/95 shadow-[var(--shadow-md)]">
          <CardContent className="flex min-h-0 flex-1 flex-col overflow-visible p-0">
            <div className="flex shrink-0 flex-nowrap items-center justify-between gap-3 border-b border-border/70 px-3 py-2.5 sm:px-4">
              <div className="page-section-heading min-w-0">
                <h3 className="truncate text-sm font-semibold tracking-[-0.02em]">
                  {t('page.history.title')}
                </h3>
              </div>
              <HistoryFilterMenu
                sourceTab={s.sourceTab}
                onSourceTabChange={s.changeSourceTab}
                dateFilter={s.dateFilter}
                onDateFilterChange={s.setDateFilter}
                fileTypeFilter={s.fileTypeFilter}
                onFileTypeFilterChange={s.setFileTypeFilter}
                statusFilter={s.statusFilter}
                onStatusFilterChange={s.setStatusFilter}
                hasActiveFilter={s.hasActiveFilter}
                onClearFilters={s.clearFilters}
              />
            </div>
            <HistoryTable
              rows={s.filteredRows}
              loading={s.initialLoading}
              refreshing={s.refreshing}
              tableLoading={s.tableLoading}
              pageSize={s.displayPageSize}
              selected={s.selected}
              onToggle={s.toggle}
              allSelected={s.allSelected}
              onSelectAll={(checked) => {
                if (checked) s.setSelected(new Set(s.filteredRows.map((row) => row.file_id)));
                else s.setSelected(new Set());
              }}
              expandedBatchIds={s.expandedBatchIds}
              onToggleBatchCollapse={s.toggleBatchCollapse}
              onSelectGroup={(ids, checked) => {
                const next = new Set(s.selected);
                for (const id of ids) {
                  if (checked) next.add(id);
                  else next.delete(id);
                }
                s.setSelected(next);
              }}
              onDownload={(row) => void s.downloadRow(row)}
              onDelete={(row) => s.remove(row.file_id)}
              onDeleteGroup={(rows) => s.removeGroup(rows.map((row) => row.file_id))}
              onCompare={(row) => s.openCompareModal(row)}
            />
          </CardContent>
        </Card>
        <div className="mt-2 shrink-0">
          <PaginationRail
            page={s.page}
            pageSize={s.pageSize}
            totalItems={s.total}
            totalPages={s.totalPages}
            onPageChange={s.goPage}
            onPageSizeChange={s.changePageSize}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
            rangeLabel={t('history.showRange')}
            perPageLabel={t('history.perPage')}
            itemsUnitLabel={t('history.itemsUnit')}
            compact
            disabled={s.initialLoading || s.tableLoading || s.interactionLocked}
            reserveWhenEmpty
            className="history-pagination-rail jobs-pagination-rail !min-h-10 !rounded-xl border-border/70 bg-muted/40"
          />
        </div>
      </div>

      <Dialog
        open={s.compareOpen}
        onOpenChange={(open) => {
          if (!open) s.closeCompareModal();
        }}
      >
        <DialogContent className="max-h-[90vh] w-[calc(100vw-1rem)] max-w-6xl overflow-hidden p-0">
          <DialogHeader className="border-b border-border/70 px-4 py-3 sm:px-5">
            <DialogTitle>{t('history.compareTitle')}</DialogTitle>
            <DialogDescription className="sr-only">
              {t('history.beforeRedaction')} / {t('history.afterRedaction')}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(90vh-4.25rem)] overflow-y-auto p-4 sm:p-5">
            {s.compareLoading ? (
              <Skeleton className="h-40 w-full rounded-xl" />
            ) : s.compareErr ? (
              <p className="text-sm text-destructive">{s.compareErr}</p>
            ) : s.compareData ? (
              <>
                {s.compareBlobUrls && (
                  <div className="space-y-3">
                    {s.compareTotalPages > 1 && (
                      <PaginationRail
                        page={s.comparePage}
                        pageSize={1}
                        totalItems={s.compareTotalPages}
                        totalPages={s.compareTotalPages}
                        compact
                        onPageChange={s.setComparePage}
                      />
                    )}
                    <div
                      className="grid grid-cols-1 gap-3 lg:grid-cols-2"
                      data-testid="history-image-compare-grid"
                    >
                      <div className="min-w-0 rounded-xl border border-border/70 bg-muted/20 p-2.5">
                        <h4 className="mb-2 text-xs font-semibold text-muted-foreground">
                          {t('history.beforeRedaction')}
                        </h4>
                        <img
                          src={s.compareBlobUrls.original}
                          alt={t('history.beforeRedaction')}
                          className="max-h-[36vh] w-full rounded-lg border border-border/70 bg-background object-contain lg:max-h-[52vh]"
                        />
                      </div>
                      <div className="min-w-0 rounded-xl border border-border/70 bg-muted/20 p-2.5">
                        <h4 className="mb-2 text-xs font-semibold text-muted-foreground">
                          {t('history.afterRedaction')}
                        </h4>
                        <img
                          src={s.compareBlobUrls.redacted}
                          alt={t('history.afterRedaction')}
                          className="max-h-[36vh] w-full rounded-lg border border-border/70 bg-background object-contain lg:max-h-[52vh]"
                        />
                      </div>
                    </div>
                  </div>
                )}
                {!s.compareBlobUrls &&
                  (s.compareData.original_content || s.compareData.redacted_content) && (
                    <div
                      className="grid grid-cols-1 gap-3 text-sm lg:grid-cols-2"
                      data-testid="history-text-compare-grid"
                    >
                      <div className="min-w-0 rounded-xl border border-border/70 bg-muted/20 p-2.5">
                        <h4 className="mb-2 text-xs font-semibold text-muted-foreground">
                          {s.compareBlobUrls
                            ? t('history.originalText')
                            : t('history.beforeRedaction')}
                        </h4>
                        <pre className="max-h-[34vh] overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-border/60 bg-background p-3 text-xs leading-5 lg:max-h-[52vh]">
                          {s.compareData.original_content}
                        </pre>
                      </div>
                      <div className="min-w-0 rounded-xl border border-border/70 bg-muted/20 p-2.5">
                        <h4 className="mb-2 text-xs font-semibold text-muted-foreground">
                          {s.compareBlobUrls
                            ? t('history.redactedText')
                            : t('history.afterRedaction')}
                        </h4>
                        <pre className="max-h-[34vh] overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-border/60 bg-background p-3 text-xs leading-5 lg:max-h-[52vh]">
                          {s.compareData.redacted_content}
                        </pre>
                      </div>
                    </div>
                  )}
              </>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={s.cleanupConfirmOpen}
        title={t('history.cleanupTitle')}
        message={t('history.cleanupMsg')}
        danger
        onConfirm={s.handleCleanup}
        onCancel={() => s.setCleanupConfirmOpen(false)}
      />
      {s.confirmDlg && (
        <ConfirmDialog
          open
          title={s.confirmDlg.title}
          message={s.confirmDlg.message}
          danger
          onConfirm={s.confirmDlg.onConfirm}
          onCancel={() => s.setConfirmDlg(null)}
        />
      )}
      <InteractionLockOverlay
        active={s.interactionLocked}
        label={s.zipLoading ? t('common.download') : t('jobs.processingEllipsis')}
      />
    </div>
  );
}
