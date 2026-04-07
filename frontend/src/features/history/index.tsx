// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { useT } from '@/i18n';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { PaginationRail } from '@/components/PaginationRail';
import { useHistory } from './hooks/use-history';
import { HistoryFilters } from './components/history-filters';
import { HistoryTable } from './components/history-table';
import { PAGE_SIZE_OPTIONS } from './hooks/use-history';

export function History() {
  const t = useT();
  const s = useHistory();

  return (
    <div className="saas-page flex min-h-0 flex-1 flex-col overflow-hidden bg-background" data-testid="history-page">
      <div className="page-shell !max-w-[min(100%,2048px)] !px-3 !pt-4 sm:!px-5 sm:!pt-5 2xl:!px-8">
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
          zipLoading={s.zipLoading}
          hasSelection={s.selectedIds.length > 0}
        />

        {s.msg && (
          <Alert variant={s.msg.tone === 'err' ? 'destructive' : 'default'} className="mb-3">
            <AlertDescription>{s.msg.text}</AlertDescription>
          </Alert>
        )}

        <Card className="page-surface flex-1">
          <CardContent className="page-surface flex-1 p-0">
            <HistoryTable
              rows={s.filteredRows}
              loading={s.initialLoading}
              selected={s.selected}
              onToggle={s.toggle}
              allSelected={s.allSelected}
              onSelectAll={(checked) => {
                if (checked) s.setSelected(new Set(s.filteredRows.map((row) => row.file_id)));
                else s.setSelected(new Set());
              }}
              onDownload={(row) => void s.downloadRow(row)}
              onDelete={(row) => s.remove(row.file_id)}
              onCompare={(row) => s.openCompareModal(row)}
            />
            {(s.total > 0 || s.totalPages > 1) && (
              <div className="page-surface-footer">
                <PaginationRail
                  page={s.page}
                  pageSize={s.pageSize}
                  totalItems={s.total}
                  totalPages={s.totalPages}
                  onPageChange={s.goPage}
                  onPageSizeChange={s.changePageSize}
                  pageSizeOptions={PAGE_SIZE_OPTIONS}
                  perPageLabel={t('history.perPage')}
                  itemsUnitLabel={t('history.itemsUnit')}
                />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={s.compareOpen} onOpenChange={(open) => { if (!open) s.closeCompareModal(); }}>
        <DialogContent className="max-h-[80vh] max-w-4xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('history.compareTitle')}</DialogTitle>
            <DialogDescription className="sr-only">
              {t('history.beforeRedaction')} / {t('history.afterRedaction')}
            </DialogDescription>
          </DialogHeader>
          {s.compareLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : s.compareErr ? (
            <p className="text-sm text-destructive">{s.compareErr}</p>
          ) : s.compareData ? (
            <>
              {s.compareBlobUrls && (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <h4 className="mb-2 font-medium">{t('history.beforeRedaction')}</h4>
                    <img
                      src={s.compareBlobUrls.original}
                      alt={t('history.beforeRedaction')}
                      className="max-h-[50vh] w-full rounded-lg border border-border/70 object-contain"
                    />
                  </div>
                  <div>
                    <h4 className="mb-2 font-medium">{t('history.afterRedaction')}</h4>
                    <img
                      src={s.compareBlobUrls.redacted}
                      alt={t('history.afterRedaction')}
                      className="max-h-[50vh] w-full rounded-lg border border-border/70 object-contain"
                    />
                  </div>
                </div>
              )}
              {!s.compareBlobUrls && (s.compareData.original_content || s.compareData.redacted_content) && (
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <h4 className="mb-2 font-medium">
                      {s.compareBlobUrls ? t('history.originalText') : t('history.beforeRedaction')}
                    </h4>
                    <pre className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs">
                      {s.compareData.original_content}
                    </pre>
                  </div>
                  <div>
                    <h4 className="mb-2 font-medium">
                      {s.compareBlobUrls ? t('history.redactedText') : t('history.afterRedaction')}
                    </h4>
                    <pre className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs">
                      {s.compareData.redacted_content}
                    </pre>
                  </div>
                </div>
              )}
            </>
          ) : null}
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
    </div>
  );
}
