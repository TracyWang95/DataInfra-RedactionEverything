import { Link } from 'react-router-dom';
import { t } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type { JobDetail, JobItemRow, JobSummary } from '@/services/jobsApi';
import { resolveJobPrimaryNavigation, buildBatchWorkbenchUrl } from '@/utils/jobPrimaryNavigation';
import { resolveRedactionState } from '@/utils/redactionState';
import { JobStatusBadge, JobTypeBadge, RedactionStateBadge } from './jobs-status-badge';
import { ACTIVE_STATUSES, buildProgressHeadline, buildProgressSummary, canDeleteJob } from '../hooks/use-jobs';

function executionLabel(config: Record<string, unknown>): string {
  return String(config.preferred_execution ?? 'queue') === 'local' ? t('jobs.localExec') : t('jobs.queueExec');
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t('jobs.updatedAtUnknown');
  const locale = (typeof window !== 'undefined' && localStorage.getItem('locale')) || 'zh';
  return date.toLocaleString(locale === 'en' ? 'en-US' : 'zh-CN');
}

type JobsTableProps = {
  rows: JobSummary[];
  loading: boolean;
  refreshing: boolean;
  total: number;
  page: number;
  totalPages: number;
  expandedJobIds: Set<string>;
  jobDetails: Record<string, JobDetail>;
  detailLoadingIds: Set<string>;
  deletingJobId: string | null;
  requeueingJobId: string | null;
  tableBusy: boolean;
  onToggleExpand: (job: JobSummary) => void;
  onDelete: (job: JobSummary) => void;
  onRequeueFailed: (job: JobSummary) => void;
};

export function JobsTable({
  rows, loading, refreshing, total, page, totalPages,
  expandedJobIds, jobDetails, detailLoadingIds,
  deletingJobId, requeueingJobId, tableBusy: _tableBusy,
  onToggleExpand, onDelete, onRequeueFailed,
}: JobsTableProps) {
  const stopEvent = (event: React.MouseEvent) => { event.stopPropagation(); };

  return (
    <div className="jobs-surface w-full flex flex-col flex-1 min-h-0 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm dark:shadow-gray-900/30 overflow-hidden overflow-x-auto">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-700 flex flex-wrap items-center justify-between gap-2 flex-shrink-0">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 text-sm">{t('jobs.taskRecords')}</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {t('jobs.totalAndPage').replace('{total}', String(total)).replace('{page}', String(page)).replace('{totalPages}', String(totalPages))}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-2xs text-muted-foreground">
          <span>{t('jobs.expandHint')}</span>
          <span className="text-gray-300">|</span>
          <span className="text-amber-700">{t('jobs.cancelBeforeDelete')}</span>
        </div>
      </div>

      {/* Column header */}
      {rows.length > 0 && (
        <div className="jobs-table-head px-4 py-2 border-b border-gray-50 dark:border-gray-700 bg-[#fafafa] dark:bg-gray-900 text-xs text-muted-foreground font-medium flex-shrink-0">
          <span className="jobs-tree-cell" />
          <span className="jobs-task-cell">{t('jobs.task')}</span>
          <span className="jobs-exec-cell">{t('jobs.execMethod')}</span>
          <span className="jobs-progress-cell">{t('jobs.progress')}</span>
          <span className="jobs-status-cell">{t('jobs.currentStatus')}</span>
          <span className="jobs-updated-cell">{t('jobs.updatedAt')}</span>
          <span className="jobs-actions-cell jobs-head-actions">
            <span className="jobs-action-head">{'\u4e3b\u64cd\u4f5c'}</span>
            <span className="jobs-action-head">{'\u8be6\u60c5'}</span>
            <span className="jobs-action-head">{'\u5220\u9664'}</span>
          </span>
        </div>
      )}

      {/* Body */}
      <div className="relative flex-1 min-h-0 overflow-y-auto flex flex-col">
        {refreshing && rows.length > 0 && (
          <div className="absolute inset-0 bg-white/60 dark:bg-gray-800/60 flex items-center justify-center z-10 backdrop-blur-[1px]">
            <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
          </div>
        )}

        {loading && rows.length === 0 ? (
          <div className="px-4 py-6 space-y-3">
            {[1, 2, 3].map(i => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="flex w-full flex-col divide-y divide-gray-100 dark:divide-gray-700">
            {rows.map((job, index) => (
              <JobRow
                key={job.id}
                job={job}
                index={index}
                expanded={expandedJobIds.has(job.id)}
                detail={jobDetails[job.id]}
                detailLoading={detailLoadingIds.has(job.id)}
                deletingJobId={deletingJobId}
                requeueingJobId={requeueingJobId}
                onToggleExpand={onToggleExpand}
                onDelete={onDelete}
                onRequeueFailed={onRequeueFailed}
                stopEvent={stopEvent}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-4">
      <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center">
        <svg className="w-8 h-8 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      </div>
      <div className="text-center">
        <p className="text-sm text-muted-foreground mb-1">{t('jobs.noRecords')}</p>
        <p className="text-xs text-muted-foreground">{t('jobs.noRecordsHint')}</p>
      </div>
      <Button variant="outline" size="sm" asChild data-testid="jobs-goto-batch">
        <Link to="/batch">{t('jobs.gotoBatch')}</Link>
      </Button>
    </div>
  );
}

type JobRowProps = {
  job: JobSummary;
  index: number;
  expanded: boolean;
  detail: JobDetail | undefined;
  detailLoading: boolean;
  deletingJobId: string | null;
  requeueingJobId: string | null;
  onToggleExpand: (job: JobSummary) => void;
  onDelete: (job: JobSummary) => void;
  onRequeueFailed: (job: JobSummary) => void;
  stopEvent: (e: React.MouseEvent) => void;
};

function JobRow({
  job, index, expanded, detail, detailLoading,
  deletingJobId, requeueingJobId,
  onToggleExpand, onDelete, onRequeueFailed, stopEvent,
}: JobRowProps) {
  const primary = resolveJobPrimaryNavigation({
    jobId: job.id, status: job.status, jobType: job.job_type,
    items: [], currentPage: 'other', navHints: job.nav_hints, jobConfig: job.config,
  });
  const detailHref = `/jobs/${encodeURIComponent(job.id)}`;
  const showPrimaryAction = primary.kind === 'link' && primary.to !== detailHref;
  const showWorkbenchShortcut = ACTIVE_STATUSES.has(job.status);
  const deleteBlocked = !canDeleteJob(job.status);
  const stripe = index % 2 === 1 ? 'bg-[#fafafa] dark:bg-gray-900' : 'bg-white dark:bg-gray-800';
  const itemCount = job.nav_hints?.item_count ?? job.progress.total_items;
  const finishedCount = job.progress.completed + job.progress.failed + (job.progress.cancelled ?? 0);
  const progressPercent = itemCount > 0 ? Math.min(100, Math.round((finishedCount / itemCount) * 100)) : 0;
  const liveHints = detail?.items ? (() => {
    let r = 0, a = 0;
    for (const it of detail.items) {
      if (it.has_output) r++; else if (['awaiting_review', 'review_approved', 'completed'].includes(it.status)) a++;
    }
    return { redacted_count: r, awaiting_review_count: a };
  })() : job.nav_hints;
  const progressHeadline = buildProgressHeadline(job.progress, liveHints);
  const progressSummary = buildProgressSummary(job.progress, itemCount, finishedCount);
  const expandable = itemCount > 0;

  const actionBtnBase = 'inline-flex items-center justify-center text-xs font-medium rounded-lg px-3 py-1.5 min-w-[60px] text-center transition-colors';

  return (
    <li>
      <div
        className={cn(stripe, 'transition-colors', expandable ? 'cursor-pointer hover:bg-gray-50/90 dark:hover:bg-gray-700/50' : 'hover:bg-gray-50/70 dark:hover:bg-gray-700/30')}
        onClick={expandable ? () => void onToggleExpand(job) : undefined}
        data-testid={`job-row-${job.id}`}
      >
        <div className="jobs-row-main px-3 sm:px-4 py-2.5">
          {/* Expand toggle */}
          <div className="jobs-tree-cell jobs-expand-cell">
            {itemCount > 0 ? (
              <button type="button"
                onClick={e => { e.stopPropagation(); void onToggleExpand(job); }}
                className="w-6 h-6 rounded-md border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors flex items-center justify-center"
                title={expanded ? t('jobs.collapseFiles') : t('jobs.expandFiles')}
                aria-expanded={expanded}
                data-testid={`job-expand-${job.id}`}
              >
                <svg className={cn('w-3.5 h-3.5 transition-transform', expanded && 'rotate-90')} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            ) : (
              <span className="w-6 h-6 rounded-md bg-gray-100 text-gray-300 flex items-center justify-center text-xs">{'\u00b7'}</span>
            )}
          </div>

          {/* Task info */}
          <div className="jobs-task-cell min-w-0">
            <div className="flex flex-nowrap items-center gap-2 min-w-0">
              <JobTypeBadge jobType={job.job_type} />
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate" title={job.title || t('jobs.unnamedTask')}>
                {job.title || t('jobs.unnamedTask')}
              </p>
            </div>
            <p className="text-caption text-muted-foreground mt-0.5">ID {job.id.slice(0, 8)}... <span className="hidden sm:inline">{'\u00b7'} {t('jobs.itemCount').replace('{n}', String(itemCount))}</span></p>
            <p className="text-caption text-muted-foreground mt-0.5 md:hidden">{t('jobs.updatedAtLabel').replace('{time}', formatUpdatedAt(job.updated_at))}</p>
          </div>

          {/* Execution */}
          <div className="jobs-exec-cell flex items-center gap-2">
            <span className="text-xs text-muted-foreground md:hidden">{t('jobs.execMethod')}</span>
            <span className="inline-flex px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 text-2xs whitespace-nowrap">
              {executionLabel(job.config)}
            </span>
          </div>

          {/* Progress */}
          <div className="jobs-progress-cell min-w-0">
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-gray-700 tabular-nums truncate">{progressHeadline}</span>
                <span className="text-caption text-muted-foreground tabular-nums shrink-0">{progressPercent}%</span>
              </div>
              <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
                <div
                  className={cn('h-full rounded-full', job.status === 'failed' ? 'bg-red-400' : job.status === 'completed' ? 'bg-emerald-500' : 'bg-[#1d1d1f]')}
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <p className="text-caption text-muted-foreground truncate">{progressSummary}</p>
            </div>
          </div>

          {/* Status */}
          <div className="jobs-status-cell flex items-center gap-2">
            <span className="text-xs text-muted-foreground md:hidden">{t('jobs.currentStatus')}</span>
            <JobStatusBadge status={job.status} />
          </div>

          {/* Updated at */}
          <div className="jobs-updated-cell hidden md:block text-caption text-muted-foreground tabular-nums whitespace-nowrap">
            {formatUpdatedAt(job.updated_at)}
          </div>

          {/* Actions */}
          <div className="jobs-actions-cell" onClick={stopEvent}>
            {showPrimaryAction ? (
              <Link to={primary.to} onClick={stopEvent}
                className={`${actionBtnBase} w-full whitespace-nowrap border border-[#007AFF]/30 bg-[#007AFF]/[0.08] text-[#0a4a8c] dark:text-[#5aafff] dark:border-[#5aafff]/30 dark:bg-[#5aafff]/[0.08] hover:bg-[#007AFF]/[0.14] dark:hover:bg-[#5aafff]/[0.14]`}
                data-testid={`job-primary-action-${job.id}`}>
                {primary.label}
              </Link>
            ) : showWorkbenchShortcut ? (
              <Link to={buildBatchWorkbenchUrl(job.id, job.job_type, 3)} onClick={stopEvent}
                className={`${actionBtnBase} w-full whitespace-nowrap border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-[#1d1d1f] dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700`}
                data-testid={`job-workbench-${job.id}`}>
                {t('jobs.openWorkbench')}
              </Link>
            ) : job.progress.failed > 0 ? (
              <button type="button" disabled={requeueingJobId === job.id}
                onClick={e => { e.stopPropagation(); void onRequeueFailed(job); }}
                className={`${actionBtnBase} w-full whitespace-nowrap border border-amber-200 dark:border-amber-700 text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20 disabled:opacity-50`}
                data-testid={`job-requeue-${job.id}`}>
                {requeueingJobId === job.id ? t('jobs.processingEllipsis') : t('jobs.requeueBtn').replace('{n}', String(job.progress.failed))}
              </button>
            ) : <span className="jobs-action-placeholder" />}
            <Link to={detailHref} onClick={stopEvent}
              className={`${actionBtnBase} w-full whitespace-nowrap border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-[#1d1d1f] dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700`}
              data-testid={`job-detail-link-${job.id}`}>
              {job.status === 'completed' ? '\u8be6\u60c5' : t('jobs.viewDetail')}
            </Link>
            {!deleteBlocked ? (
              <button type="button" disabled={deletingJobId === job.id}
                onClick={e => { e.stopPropagation(); void onDelete(job); }}
                className={`${actionBtnBase} w-full whitespace-nowrap border border-gray-200 dark:border-gray-600 text-gray-400 dark:text-gray-500 hover:border-red-300 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50`}
                data-testid={`job-delete-${job.id}`}>
                {deletingJobId === job.id ? t('jobs.deletingEllipsis') : t('jobs.deleteTask')}
              </button>
            ) : <span className="jobs-action-placeholder" />}
          </div>
        </div>

        {/* Expanded detail rows */}
        {expanded && (
          <ExpandedDetail detail={detail} detailLoading={detailLoading} stopEvent={stopEvent} />
        )}
      </div>
    </li>
  );
}

function ExpandedDetail({
  detail, detailLoading, stopEvent,
}: {
  detail: JobDetail | undefined;
  detailLoading: boolean;
  stopEvent: (e: React.MouseEvent) => void;
}) {
  return (
    <div className="border-t border-gray-100 dark:border-gray-700" onClick={stopEvent}>
      {detailLoading ? (
        <div className="px-3 sm:px-4 py-4 text-xs text-muted-foreground flex items-center gap-2">
          <div className="w-4 h-4 border-2 border-[#e5e5e5] border-t-[#1d1d1f] rounded-full animate-spin" />
          {t('jobs.loadingFileDetail')}
        </div>
      ) : detail && detail.items.length > 0 ? (
        <div className="py-0.5 animate-fadeIn">
          {detail.items.map((item: JobItemRow, itemIndex: number) => {
            const rs = resolveRedactionState(Boolean(item.has_output), item.status);
            const isLast = itemIndex === detail.items.length - 1;
            return (
              <div key={item.id}
                className={cn('jobs-row-main jobs-child-row px-3 sm:px-4 py-1.5', !isLast && 'border-b border-gray-50 dark:border-gray-800')}>
                <span className="text-gray-300 dark:text-gray-600 text-xs text-center select-none" aria-hidden>
                  {isLast ? '\u2514' : '\u251c'}
                </span>
                <div className="jobs-task-cell jobs-child-task min-w-0">
                  <p className="text-xs text-gray-600 dark:text-gray-300 truncate" title={item.filename || item.file_id}>
                    {item.filename || item.file_id}
                  </p>
                  <p className="text-2xs text-muted-foreground">
                    {item.file_type ? String(item.file_type).toUpperCase() : '\u2014'} {'\u00b7'} {t('jobs.recognize').replace('{n}', String(item.entity_count ?? 0))}
                  </p>
                </div>
                <span />
                <span />
                <div className="jobs-status-cell flex items-center">
                  <RedactionStateBadge state={rs} />
                </div>
                <span className="jobs-updated-cell text-caption text-muted-foreground tabular-nums whitespace-nowrap">
                  {formatUpdatedAt(item.updated_at)}
                </span>
                <span />
              </div>
            );
          })}
        </div>
      ) : (
        <div className="px-3 sm:px-4 py-4 text-xs text-muted-foreground">{t('jobs.noFileDetail')}</div>
      )}
    </div>
  );
}
