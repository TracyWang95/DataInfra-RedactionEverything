// Copyright 2026 DataInfra-RedactionEverything Contributors

import { Link } from 'react-router-dom';
import { ArrowRight, Clock3 } from 'lucide-react';
import { memo, useMemo } from 'react';
import { useT } from '@/i18n';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { AsyncListShell } from '@/components/shared/AsyncListShell';
import { formatAggregateJobStatus } from '@/utils/jobStatusLabels';
import {
  buildJobPrimaryNavigationLabels,
  resolveJobPrimaryNavigation,
} from '@/utils/jobPrimaryNavigation';
import type { JobSummary } from '@/services/jobsApi';

interface BatchHubJobListProps {
  jobs: JobSummary[];
  loading: boolean;
  tableLoading?: boolean;
  onContinue: (job: JobSummary) => void;
}

const MAX_VISIBLE_JOBS = 4;
const RECENT_JOBS_FRAME_CLASS = 'min-h-[12rem]';

export function BatchHubJobList({
  jobs,
  loading,
  tableLoading = false,
  onContinue,
}: BatchHubJobListProps) {
  const hardLoading = loading && jobs.length === 0;
  const shouldTableLoad = jobs.length > 0 && (loading || tableLoading);
  const visibleJobs = useMemo(() => jobs.slice(0, MAX_VISIBLE_JOBS), [jobs]);
  const hiddenCount = Math.max(0, jobs.length - visibleJobs.length);
  const t = useT();

  return (
    <Card
      className="page-surface min-h-0 !flex-none border-border/70 shadow-[var(--shadow-control)]"
      data-testid="recent-jobs-card"
    >
      <CardHeader className="flex flex-row items-center justify-between gap-3 px-4 pb-2 pt-3.5">
        <div className="min-w-0">
          <CardTitle className="truncate text-sm font-semibold">
            {t('batchHub.recentTitle')}
          </CardTitle>
          <CardDescription className="mt-0.5 truncate text-xs leading-5">
            {t('batchHub.recentDesc')}
          </CardDescription>
        </div>
        <Button variant="ghost" size="sm" asChild className="h-8 shrink-0 rounded-lg px-2 text-xs">
          <Link to="/jobs">
            {t('batchHub.viewAll')}
            <ArrowRight className="ml-1 size-3.5" />
          </Link>
        </Button>
      </CardHeader>

      <CardContent className="flex min-h-0 flex-col p-0">
        <AsyncListShell
          hardLoading={hardLoading}
          isEmpty={jobs.length === 0}
          refreshing={shouldTableLoad}
          refreshingLabel={t('jobs.refreshing')}
          className={RECENT_JOBS_FRAME_CLASS}
          testId="recent-jobs-list-frame"
          skeleton={
            <div
              className={`flex ${RECENT_JOBS_FRAME_CLASS} flex-col divide-y px-4 pb-4`}
              data-testid="recent-jobs-loading-skeleton"
            >
              {Array.from({ length: MAX_VISIBLE_JOBS }, (_, index) => (
                <div
                  key={index}
                  className="grid min-h-12 grid-cols-[minmax(0,1fr)_4.5rem] items-center gap-3 py-1.5"
                  data-testid="recent-jobs-loading-row"
                >
                  <div className="min-w-0 space-y-2">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-3 w-1/2" />
                  </div>
                  <Skeleton className="h-7 w-full rounded-lg" />
                </div>
              ))}
            </div>
          }
          emptyContent={
            <div
              className={`flex ${RECENT_JOBS_FRAME_CLASS} items-start gap-3 px-4 pb-4 pt-1 text-sm text-muted-foreground`}
            >
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl border border-border bg-muted">
                <Clock3 className="size-4" />
              </span>
              <div className="flex min-w-0 flex-col gap-1">
                <span className="truncate font-medium text-foreground">
                  {t('batchHub.noActiveJobs')}
                </span>
                <span className="truncate text-xs leading-5">{t('batchHub.noActiveJobsDesc')}</span>
              </div>
            </div>
          }
        >
          <ul className="flex min-h-0 flex-col divide-y" data-testid="recent-jobs-list">
            {visibleJobs.map((job) => (
              <JobRow key={job.id} job={job} onContinue={onContinue} t={t} />
            ))}
          </ul>
          {hiddenCount > 0 ? (
            <div className="truncate border-t border-border/70 px-4 py-2 text-xs text-muted-foreground">
              {t('batchHub.moreActiveJobs').replace('{n}', String(hiddenCount))}
            </div>
          ) : null}
        </AsyncListShell>
      </CardContent>
    </Card>
  );
}

const JobRow = memo(function JobRow({
  job,
  onContinue,
  t,
}: {
  job: JobSummary;
  onContinue: (job: JobSummary) => void;
  t: (key: string) => string;
}) {
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

  return (
    <li
      className="grid min-h-12 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 py-1.5"
      data-testid={`job-row-${job.id}`}
    >
      <div className="min-w-0 space-y-1">
        <div className="flex min-w-0 flex-nowrap items-center gap-2">
          <Badge variant="secondary" className="shrink-0 rounded-full px-2.5 py-0.5">
            {t('batchHub.batch')}
          </Badge>
          <span
            className="min-w-0 truncate text-sm font-medium leading-5"
            title={job.title || t('batchHub.unnamedTask')}
          >
            {job.title || t('batchHub.unnamedTask')}
          </span>
          <span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground">
            {formatAggregateJobStatus(job.status)}
          </span>
        </div>
        <div className="truncate text-xs leading-5 text-muted-foreground tabular-nums">
          {t('batchHub.progressSummary')
            .replace('{total}', String(job.progress.total_items))
            .replace('{awaiting}', String(job.progress.awaiting_review))
            .replace('{completed}', String(job.progress.completed))}
          {job.progress.failed
            ? t('batchHub.failedSuffix').replace('{n}', String(job.progress.failed))
            : ''}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {primary.kind === 'link' ? (
          <Button
            variant="link"
            size="sm"
            className="h-8 rounded-lg px-2 text-xs whitespace-nowrap"
            onClick={() => onContinue(job)}
            data-testid={`continue-job-${job.id}`}
          >
            {primary.label}
          </Button>
        ) : (
          <Button
            variant="link"
            size="sm"
            className="h-8 rounded-lg px-2 text-xs whitespace-nowrap"
            asChild
          >
            <Link to={`/jobs/${job.id}`}>{t('batchHub.viewDetail')}</Link>
          </Button>
        )}
      </div>
    </li>
  );
});
