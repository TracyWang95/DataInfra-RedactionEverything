// Copyright 2026 DataInfra-RedactionEverything Contributors

import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { ArrowRight, Eye, SlidersHorizontal, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { t, useI18n, useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { EmptyState } from '@/components/EmptyState';
import { AsyncListShell } from '@/components/shared/AsyncListShell';
import {
  clampPageSize,
  interpolateDensity,
  useProportionalRowHeight,
} from '@/components/hooks/useProportionalRowHeight';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { JobSummary } from '@/services/jobsApi';
import type { JobsStatusFilter } from '../hooks/use-jobs';
import {
  buildJobPrimaryNavigationLabels,
  resolveJobPrimaryNavigation,
} from '@/utils/jobPrimaryNavigation';
import { JobStatusBadge, JobTypeBadge } from './jobs-status-badge';
import { canDeleteJob } from '../hooks/use-jobs';

function getJobCounts(job: JobSummary): {
  total: number;
  completed: number;
  awaitingReview: number;
  abnormal: number;
} {
  return {
    total: job.nav_hints?.item_count ?? job.progress.total_items,
    completed: job.progress.completed,
    awaitingReview: job.progress.awaiting_review + job.progress.review_approved,
    abnormal: job.progress.failed + (job.progress.cancelled ?? 0),
  };
}

function getProgressMeter(job: JobSummary): {
  percent: number;
  tone: 'brand' | 'success' | 'danger' | 'warning';
} {
  const counts = getJobCounts(job);
  const activeCount =
    job.progress.pending +
    job.progress.queued +
    job.progress.processing +
    job.progress.parsing +
    job.progress.ner +
    job.progress.vision +
    job.progress.redacting;
  const percent =
    counts.total > 0
      ? Math.min(
          100,
          Math.round(
            ((counts.completed + counts.awaitingReview + counts.abnormal) / counts.total) * 100,
          ),
        )
      : 0;

  if (counts.abnormal > 0) return { percent, tone: 'danger' };
  if (counts.awaitingReview > 0) return { percent, tone: 'warning' };
  if (activeCount > 0) return { percent, tone: 'brand' };
  if (counts.total > 0 && counts.completed >= counts.total) {
    return { percent: 100, tone: 'success' };
  }
  return { percent, tone: 'brand' };
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t('jobs.updatedAtUnknown');
  const locale = useI18n.getState().locale;
  return date.toLocaleString(locale === 'en' ? 'en-US' : 'zh-CN');
}

type JobsTableProps = {
  rows: JobSummary[];
  loading: boolean;
  refreshing: boolean;
  tableLoading?: boolean;
  pageSize: number;
  deletingJobId: string | null;
  tableBusy: boolean;
  onDelete: (job: JobSummary) => void;
  tab?: JobsStatusFilter;
  onTabChange?: (tab: JobsStatusFilter) => void;
};

const jobsGridStyle: CSSProperties = {
  gridTemplateColumns:
    'minmax(210px,1.16fr) minmax(44px,0.24fr) minmax(54px,0.28fr) minmax(54px,0.28fr) minmax(50px,0.26fr) minmax(155px,0.82fr) minmax(96px,0.48fr) minmax(124px,0.58fr) minmax(72px,0.36fr) minmax(72px,0.36fr) minmax(60px,0.3fr)',
  columnGap: '10px',
};

function stopRowClick(event: ReactMouseEvent) {
  event.stopPropagation();
}

const JOBS_MIN_PAGE_SIZE = 10;
const JOBS_MAX_PAGE_SIZE = 20;
const JOBS_TABLE_MIN_CHILD_HEIGHT = 22;
const JOBS_TABLE_MAX_CHILD_HEIGHT = 34;
const JOBS_TABLE_MIN_PADDING_Y = 3;
const JOBS_TABLE_MAX_PADDING_Y = 8;
const JOBS_TABLE_MIN_CHILD_PADDING_Y = 2;
const JOBS_TABLE_MAX_CHILD_PADDING_Y = 6;
const JOB_STATUS_FILTERS: JobsStatusFilter[] = [
  'all',
  'active',
  'awaiting_review',
  'completed',
  'risk',
  'draft',
];

type JobsTableDensity = {
  rowHeight: number;
  childRowHeight: number;
  rowPaddingY: number;
  childRowPaddingY: number;
  skeletonHeight: number;
};

function normalizeJobsPageSize(pageSize: number): number {
  return clampPageSize(pageSize, JOBS_MIN_PAGE_SIZE, JOBS_MAX_PAGE_SIZE);
}

function getJobsTableDensity(pageSize: number, rowHeight: number): JobsTableDensity {
  const interpolate = interpolateDensity(pageSize, JOBS_MIN_PAGE_SIZE, JOBS_MAX_PAGE_SIZE);

  return {
    rowHeight,
    childRowHeight: Math.max(
      10,
      Math.min(
        interpolate(JOBS_TABLE_MAX_CHILD_HEIGHT, JOBS_TABLE_MIN_CHILD_HEIGHT),
        rowHeight * 0.8,
      ),
    ),
    rowPaddingY: Math.max(
      0,
      Math.min(interpolate(JOBS_TABLE_MAX_PADDING_Y, JOBS_TABLE_MIN_PADDING_Y), rowHeight * 0.08),
    ),
    childRowPaddingY: interpolate(JOBS_TABLE_MAX_CHILD_PADDING_Y, JOBS_TABLE_MIN_CHILD_PADDING_Y),
    skeletonHeight: Math.max(8, rowHeight - 4),
  };
}

function getJobsSkeletonCount(pageSize: number): number {
  return normalizeJobsPageSize(pageSize);
}

export function JobsTable({
  rows,
  loading,
  refreshing,
  tableLoading = false,
  pageSize,
  deletingJobId,
  tableBusy: _tableBusy,
  onDelete,
  tab,
  onTabChange,
}: JobsTableProps) {
  const t = useT();
  const bodyRef = useRef<HTMLDivElement>(null);
  const rowHeight = useProportionalRowHeight({
    pageSize,
    minPageSize: JOBS_MIN_PAGE_SIZE,
    maxPageSize: JOBS_MAX_PAGE_SIZE,
    bodyRef,
  });
  const density = useMemo(() => getJobsTableDensity(pageSize, rowHeight), [pageSize, rowHeight]);
  const safePageSize = normalizeJobsPageSize(pageSize);
  const fillerRowCount = Math.max(0, safePageSize - rows.length);
  const bodyStyle: CSSProperties = {
    height: 0,
    minHeight: 0,
    overscrollBehavior: 'contain',
    scrollbarGutter: 'stable',
  };
  const hardLoading = loading && rows.length === 0;
  const showJobType = rows.length > 0 && rows.some((job) => job.job_type !== rows[0].job_type);

  return (
    <div
      className="jobs-surface page-surface flex min-h-0 flex-1 flex-col overflow-hidden w-full rounded-[20px] border border-border/70 bg-card/95 shadow-[var(--shadow-md)]"
      data-testid="jobs-table-surface"
      aria-busy={loading || refreshing || tableLoading}
    >
      <div className="flex shrink-0 flex-nowrap items-center justify-between gap-3 border-b border-border/70 px-3 py-2.5 sm:px-4">
        <div className="page-section-heading min-w-0">
          <h3 className="truncate text-sm font-semibold tracking-[-0.02em]">
            {t('jobs.taskRecords')}
          </h3>
        </div>
        {tab && onTabChange ? (
          <JobsFilterMenu tab={tab} onTabChange={onTabChange} />
        ) : null}
      </div>

      <div
        className="jobs-table-head shrink-0 border-b border-border/70 bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground sm:px-4"
        style={jobsGridStyle}
      >
        <span className="jobs-task-cell">{t('jobs.task')}</span>
        <span className="jobs-count-head">{t('jobs.totalCountHeader')}</span>
        <span className="jobs-count-head">{t('jobs.completedHeader')}</span>
        <span className="jobs-count-head">{t('jobs.awaitingReviewHeader')}</span>
        <span className="jobs-count-head">{t('jobs.abnormalHeader')}</span>
        <span className="jobs-progress-cell">{t('jobs.progress')}</span>
        <span className="jobs-status-cell">{t('jobs.currentStatus')}</span>
        <span className="jobs-updated-cell">{t('jobs.updatedAt')}</span>
        <span className="jobs-action-column-head">{t('jobNav.continueReview')}</span>
        <span className="jobs-action-column-head">{t('jobs.viewDetail')}</span>
        <span className="jobs-action-column-head">{t('jobs.deleteAction')}</span>
      </div>

      <div
        className="jobs-table-body page-surface-body relative flex min-h-0 flex-1 flex-col overflow-x-auto overflow-y-auto"
        ref={bodyRef}
        style={bodyStyle}
        data-testid="jobs-table-body"
      >
        <AsyncListShell
          hardLoading={hardLoading}
          isEmpty={rows.length === 0}
          className="min-h-full"
          skeleton={
            <div className="flex flex-col gap-2 px-4 py-4 pb-7">
              {Array.from({ length: getJobsSkeletonCount(pageSize) }).map((_, i) => (
                <Skeleton
                  key={i}
                  className="w-full rounded-lg"
                  style={{ height: `${density.skeletonHeight}px` }}
                />
              ))}
            </div>
          }
          emptyContent={
            <div
              className="flex min-h-full items-center justify-center px-4"
              data-testid="jobs-table-empty"
            >
              <EmptyState
                title={t('jobs.noRecords')}
                description={t('jobs.noRecordsHint')}
                action={{
                  label: t('jobs.gotoBatch'),
                  onClick: () => {
                    window.location.href = '/batch';
                  },
                }}
              />
            </div>
          }
        >
          <ul className="jobs-table-list flex min-h-full min-w-full flex-col divide-y divide-border/70">
            {rows.map((job, index) => (
              <JobRow
                key={job.id}
                job={job}
                index={index}
                deletingJobId={deletingJobId}
                density={density}
                showJobType={showJobType}
                onDelete={onDelete}
                stopEvent={stopRowClick}
              />
            ))}
            {Array.from({ length: fillerRowCount }).map((_, index) => (
              <li
                key={`jobs-filler-${index}`}
                className="shrink-0 bg-background"
                style={{ height: `${density.rowHeight}px`, minHeight: `${density.rowHeight}px` }}
                aria-hidden
              />
            ))}
          </ul>
        </AsyncListShell>
      </div>
    </div>
  );
}

function getJobsTabLabel(t: (key: string) => string, value: JobsStatusFilter): string {
  if (value === 'all') return t('jobs.tab.all');
  if (value === 'active') return t('jobs.filter.active');
  if (value === 'awaiting_review') return t('jobs.filter.awaitingReview');
  if (value === 'completed') return t('jobs.filter.completed');
  if (value === 'risk') return t('jobs.filter.risk');
  return t('jobs.filter.draft');
}

function JobsFilterMenu({
  tab,
  onTabChange,
}: {
  tab: JobsStatusFilter;
  onTabChange: (tab: JobsStatusFilter) => void;
}) {
  const t = useT();
  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);
  const hasActiveFilter = tab !== 'all';
  const filterTabsListClass = 'h-8 w-full rounded-lg border border-border/70 bg-muted/55 p-0.5';
  const filterTabClass =
    'flex-1 rounded-md border border-transparent px-2 py-1 text-xs text-muted-foreground transition-colors data-[state=active]:bg-foreground data-[state=active]:font-semibold data-[state=active]:text-background data-[state=active]:shadow-sm data-[state=active]:ring-1 data-[state=active]:ring-inset data-[state=active]:ring-foreground/45';

  useEffect(() => {
    if (!filterOpen) return;

    const closeOnOutsideClick = (event: globalThis.MouseEvent) => {
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
        className="h-8 w-16 shrink-0 rounded-lg px-2 text-xs whitespace-nowrap"
        onClick={() => setFilterOpen((open) => !open)}
        data-testid="jobs-filter-menu"
        aria-expanded={filterOpen}
      >
        <SlidersHorizontal data-icon="inline-start" />
        {t('history.filters.kicker')}
      </Button>

      <div
        className="absolute right-0 top-9 z-[80] w-[390px] rounded-xl border border-border bg-popover p-3 shadow-[var(--shadow-lg)]"
        hidden={!filterOpen}
        data-testid="jobs-filter-popover"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-2">
          <div className="truncate text-[11px] font-medium text-muted-foreground">
            {t('jobs.statusLabel')}
          </div>
          <Tabs
            value={tab}
            onValueChange={(value) => onTabChange(value as JobsStatusFilter)}
            data-testid="jobs-status-filter"
          >
            <TabsList className={filterTabsListClass} data-testid="jobs-table-tab-list">
              {JOB_STATUS_FILTERS.map((value) => (
                <TabsTrigger
                  key={value}
                  value={value}
                  className={filterTabClass}
                  data-testid={`jobs-tab-${value}`}
                >
                  {getJobsTabLabel(t, value)}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>

        {hasActiveFilter && (
          <div className="mt-2 flex justify-end border-t border-border/70 pt-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 rounded-lg px-2 text-xs whitespace-nowrap"
              onClick={() => onTabChange('all')}
              data-testid="clear-jobs-filter"
            >
              {t('history.clearFilter')}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

type JobRowProps = {
  job: JobSummary;
  index: number;
  deletingJobId: string | null;
  density: JobsTableDensity;
  showJobType: boolean;
  onDelete: (job: JobSummary) => void;
  stopEvent: (e: ReactMouseEvent) => void;
};

function MetricCell({
  value,
  title,
  testId,
  tone = 'default',
}: {
  value: number;
  title: string;
  testId: string;
  tone?: 'default' | 'muted' | 'danger';
}) {
  return (
    <div className="jobs-metric-cell" title={`${title}: ${value}`} data-testid={testId}>
      <span
        className={cn(
          'jobs-metric-value',
          tone === 'muted' && 'text-muted-foreground/55',
          tone === 'danger' && 'text-[var(--error-foreground)]',
        )}
      >
        {value}
      </span>
    </div>
  );
}

const JobRow = memo(function JobRow({
  job,
  index,
  deletingJobId,
  density,
  showJobType,
  onDelete,
  stopEvent,
}: JobRowProps) {
  const t = useT();
  const navLabels = buildJobPrimaryNavigationLabels(t);
  const primary = resolveJobPrimaryNavigation({
    jobId: job.id,
    status: job.status,
    jobType: job.job_type,
    items: [],
    currentPage: 'other',
    navHints: job.nav_hints,
    jobConfig: job.config,
    labels: navLabels,
  });
  const detailHref = `/jobs/${encodeURIComponent(job.id)}`;
  const showContinueReview =
    primary.kind === 'link' &&
    primary.to !== detailHref &&
    primary.label === navLabels.continueReview;
  const deleteBlocked = !canDeleteJob(job.status);
  const stripe = index % 2 === 1 ? 'bg-muted/30' : 'bg-background';
  const counts = getJobCounts(job);
  const progressMeter = getProgressMeter(job);

  const compactRow = density.rowHeight < 36;
  const actionIconBtnBase = cn(
    'size-7 rounded-lg shadow-none hover:translate-y-0',
    compactRow && 'size-6',
  );
  const actionPlaceholder = (
    <span
      className={cn('jobs-action-placeholder rounded-lg', compactRow ? '!min-h-6' : '!min-h-7')}
    />
  );

  return (
    <li className="shrink-0">
      <div
        className={cn(stripe, 'transition-colors hover:bg-muted/30')}
        data-testid={`job-row-${job.id}`}
      >
        <div
          className="jobs-row-main overflow-hidden whitespace-nowrap px-3 py-2 sm:px-4"
          style={{
            ...jobsGridStyle,
            height: `${density.rowHeight}px`,
            minHeight: `${density.rowHeight}px`,
            paddingTop: `${density.rowPaddingY}px`,
            paddingBottom: `${density.rowPaddingY}px`,
          }}
        >
          <div className="jobs-task-cell min-w-0 overflow-hidden">
            <div className="flex min-w-0 flex-nowrap items-center gap-2">
              {showJobType ? <JobTypeBadge jobType={job.job_type} /> : null}
              <p
                className="truncate text-sm font-medium"
                title={job.title || t('jobs.unnamedTask')}
              >
                {job.title || t('jobs.unnamedTask')}
              </p>
            </div>
          </div>

          <MetricCell
            value={counts.total}
            title={t('jobs.totalCountHeader')}
            testId={`job-total-count-${job.id}`}
          />
          <MetricCell
            value={counts.completed}
            title={t('jobs.completedHeader')}
            testId={`job-completed-count-${job.id}`}
          />
          <MetricCell
            value={counts.awaitingReview}
            title={t('jobs.awaitingReviewHeader')}
            testId={`job-awaiting-review-count-${job.id}`}
          />
          <MetricCell
            value={counts.abnormal}
            title={t('jobs.abnormalHeader')}
            tone={counts.abnormal > 0 ? 'danger' : 'muted'}
            testId={`job-abnormal-count-${job.id}`}
          />

          <div className="jobs-progress-cell min-w-0 overflow-hidden">
            <div className="flex min-w-0 flex-nowrap items-center gap-2 whitespace-nowrap">
              <div className="h-1.5 min-w-[72px] flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    'h-full rounded-full transition-all',
                    progressMeter.tone === 'danger'
                      ? 'tone-progress-danger'
                      : progressMeter.tone === 'success'
                        ? 'tone-progress-success'
                        : progressMeter.tone === 'warning'
                          ? 'tone-progress-warning'
                          : 'tone-progress-brand',
                  )}
                  style={{ width: `${progressMeter.percent}%` }}
                />
              </div>
              <span
                className="shrink-0 text-caption text-muted-foreground tabular-nums"
                data-testid={`job-progress-state-${job.id}`}
              >
                {progressMeter.percent}%
              </span>
            </div>
          </div>

          <div className="jobs-status-cell flex min-w-0 flex-nowrap items-center gap-2">
            <span className="shrink-0 text-xs text-muted-foreground md:hidden">
              {t('jobs.currentStatus')}
            </span>
            <JobStatusBadge status={job.status} />
          </div>

          <div className="jobs-updated-cell hidden md:block text-caption text-muted-foreground tabular-nums whitespace-nowrap">
            {formatUpdatedAt(job.updated_at)}
          </div>

          <div className="jobs-action-cell" onClick={stopEvent}>
            {showContinueReview && primary.kind === 'link' ? (
              <Button
                asChild
                variant="outline"
                size="icon"
                className={cn(actionIconBtnBase, 'bg-background hover:bg-muted')}
              >
                <Link
                  to={primary.to}
                  onClick={stopEvent}
                  title={primary.label}
                  aria-label={primary.label}
                  data-testid={`job-primary-action-${job.id}`}
                >
                  <ArrowRight data-icon="inline-end" />
                  <span className="sr-only">{primary.label}</span>
                </Link>
              </Button>
            ) : (
              actionPlaceholder
            )}
          </div>
          <div className="jobs-action-cell" onClick={stopEvent}>
            <Button
              asChild
              variant="outline"
              size="icon"
              className={cn(actionIconBtnBase, 'bg-background hover:bg-muted')}
            >
              <Link
                to={detailHref}
                onClick={stopEvent}
                title={t('jobs.viewDetail')}
                aria-label={t('jobs.viewDetail')}
                data-testid={`job-detail-link-${job.id}`}
              >
                <Eye data-icon="inline-start" />
                <span className="sr-only">{t('jobs.viewDetail')}</span>
              </Link>
            </Button>
          </div>
          <div className="jobs-action-cell" onClick={stopEvent}>
            {!deleteBlocked ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={deletingJobId === job.id}
                onClick={(e) => {
                  e.stopPropagation();
                  void onDelete(job);
                }}
                className={cn(
                  actionIconBtnBase,
                  'border border-transparent text-muted-foreground hover:border-[var(--error-border)] hover:bg-[var(--error-surface)] hover:text-[var(--error-foreground)] disabled:opacity-50',
                )}
                title={t('jobs.deleteTask')}
                aria-label={t('jobs.deleteTask')}
                data-testid={`job-delete-${job.id}`}
              >
                <Trash2
                  data-icon="inline-start"
                  className={cn(deletingJobId === job.id && 'animate-pulse')}
                />
                <span className="sr-only">
                  {deletingJobId === job.id ? t('jobs.deletingEllipsis') : t('jobs.deleteTask')}
                </span>
              </Button>
            ) : (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled
                className={cn(
                  actionIconBtnBase,
                  'border border-transparent text-muted-foreground opacity-35',
                )}
                title={t('jobs.cancelBeforeDelete')}
                aria-label={t('jobs.deleteTask')}
                data-testid={`job-delete-disabled-${job.id}`}
              >
                <Trash2 data-icon="inline-start" />
                <span className="sr-only">{t('jobs.deleteTask')}</span>
              </Button>
            )}
          </div>
        </div>
      </div>
    </li>
  );
});
