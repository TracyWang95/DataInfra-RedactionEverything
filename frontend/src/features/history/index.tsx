/**
 * History page: file processing history and comparison.
 */
import { useT } from '@/i18n';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { useHistory } from './hooks/use-history';
import { HistoryFilters } from './components/history-filters';
import { HistoryTable } from './components/history-table';
import type { FileListItem } from '@/types';

export function History() {
  const t = useT();
  const s = useHistory();

  const handleDownload = (row: FileListItem) => {
    const url = `/api/v1/files/${row.file_id}/download?redacted=${row.has_output}`;
    const link = document.createElement('a');
    link.href = url;
    link.download = row.original_filename;
    link.click();
  };

  return (
    <div className="saas-page flex min-h-0 flex-1 flex-col overflow-hidden bg-background" data-testid="history-page">
      <div className="mx-auto flex w-full max-w-[min(100%,1920px)] flex-1 min-h-0 flex-col px-3 py-4 sm:px-5 sm:py-5">
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
          pageSize={s.pageSize}
          onPageSizeChange={s.changePageSize}
        />

        {s.msg && (
          <Alert variant={s.msg.tone === 'err' ? 'destructive' : 'default'} className="mb-3">
            <AlertDescription>{s.msg.text}</AlertDescription>
          </Alert>
        )}

        <Card className="flex-1 min-h-0 overflow-hidden">
          <CardContent className="p-0">
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
              onDownload={handleDownload}
              onDelete={(row) => s.remove(row.file_id)}
              onCompare={(row) => s.openCompareModal(row)}
            />
          </CardContent>
        </Card>

        {s.totalPages > 1 && (
          <div className="mt-3 flex items-center justify-between rounded-2xl border border-border/70 bg-muted/25 px-4 py-3 text-sm text-muted-foreground">
            <span>
              {(s.page - 1) * s.pageSize + 1} - {Math.min(s.page * s.pageSize, s.total)} / {s.total}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={s.page <= 1} onClick={() => s.goPage(s.page - 1)}>
                {t('history.prevPage')}
              </Button>
              <Button variant="outline" size="sm" disabled={s.page >= s.totalPages} onClick={() => s.goPage(s.page + 1)}>
                {t('history.nextPage')}
              </Button>
            </div>
          </div>
        )}
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
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <h4 className="mb-2 font-medium">{t('history.beforeRedaction')}</h4>
                <pre className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs">
                  {s.compareData.original_content}
                </pre>
              </div>
              <div>
                <h4 className="mb-2 font-medium">{t('history.afterRedaction')}</h4>
                <pre className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs">
                  {s.compareData.redacted_content}
                </pre>
              </div>
            </div>
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
