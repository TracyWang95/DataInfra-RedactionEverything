// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { InteractionLockOverlay } from '@/components/InteractionLockOverlay';
import { useJobs } from './hooks/use-jobs';
import { JobsFilters } from './components/jobs-filters';
import { JobsTable } from './components/jobs-table';
import { JobsPagination } from './components/jobs-pagination';

export { JobDetailPage } from './job-detail-page';

export function Jobs() {
  const t = useT();
  const s = useJobs();
  const lockLabel = s.deletingJobId
    ? t('jobs.deletingEllipsis')
    : s.requeueingJobId || s.cleanupLoading
      ? t('jobs.processingEllipsis')
      : t('job.status.processing');

  return (
    <div
      className="jobs-root saas-page flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background"
      data-testid="jobs-page"
    >
      <div className="page-shell !max-w-[min(100%,2048px)] !px-3 !py-3 sm:!px-4 2xl:!px-5">
        <JobsFilters
          onRefresh={s.refreshList}
          onCleanup={() => s.setCleanupConfirmOpen(true)}
          refreshing={s.refreshing}
          tableBusy={s.tableBusy}
          metrics={s.pageMetrics}
        />

        {s.notice && (
          <Alert className="mb-2" data-testid="jobs-notice">
            <AlertDescription>{s.notice}</AlertDescription>
          </Alert>
        )}
        {s.err && (
          <Alert variant="destructive" className="mb-2" data-testid="jobs-error">
            <AlertDescription>{s.err}</AlertDescription>
          </Alert>
        )}

        <JobsTable
          rows={s.rows}
          loading={s.loading}
          refreshing={s.refreshing}
          tableLoading={s.tableLoading}
          total={s.total}
          page={s.page}
          pageSize={s.rowsPageSize}
          totalPages={s.totalPages}
          expandedJobIds={s.expandedJobIds}
          jobDetails={s.jobDetails}
          detailLoadingIds={s.detailLoadingIds}
          deletingJobId={s.deletingJobId}
          requeueingJobId={s.requeueingJobId}
          tableBusy={s.tableBusy}
          onToggleExpand={s.toggleExpand}
          onDelete={s.requestDelete}
          onRequeueFailed={s.onRequeueFailed}
          tab={s.tab}
          onTabChange={s.changeTab}
        />
        <div className="mt-2 shrink-0">
          <JobsPagination
            page={s.page}
            pageSize={s.pageSize}
            totalPages={s.totalPages}
            total={s.total}
            rangeStart={s.rangeStart}
            rangeEnd={s.rangeEnd}
            jumpPage={s.jumpPage}
            tableBusy={s.loading || s.tableLoading || s.interactionLocked}
            onGoPage={s.goPage}
            onChangePageSize={s.changePageSize}
            onJumpPageChange={s.setJumpPage}
          />
        </div>
      </div>

      <ConfirmDialog
        open={s.cleanupConfirmOpen}
        title={t('jobs.cleanupTitle')}
        message={t('jobs.cleanupMessage')}
        danger
        onConfirm={s.onCleanup}
        onCancel={() => s.setCleanupConfirmOpen(false)}
      />
      {s.deleteCandidate && (
        <ConfirmDialog
          open
          title={t('jobs.deleteTask')}
          message={t('jobs.confirmDelete').replace(
            '{title}',
            s.deleteCandidate.title?.trim() || t('jobs.unnamedTask'),
          )}
          confirmText={t('jobs.deleteAction')}
          danger
          onConfirm={s.confirmDelete}
          onCancel={s.cancelDelete}
        />
      )}
      <InteractionLockOverlay active={s.interactionLocked} label={lockLabel} />
    </div>
  );
}
