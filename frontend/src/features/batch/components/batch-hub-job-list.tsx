// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useT } from '@/i18n';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import { formatAggregateJobStatus } from '@/utils/jobStatusLabels';
import { resolveJobPrimaryNavigation } from '@/utils/jobPrimaryNavigation';
import { cn } from '@/lib/utils';
import type { JobSummary } from '@/services/jobsApi';

interface BatchHubJobListProps {
  jobs: JobSummary[];
  loading: boolean;
  onContinue: (job: JobSummary) => void;
  footer?: ReactNode;
}

export function BatchHubJobList({ jobs, loading, onContinue, footer }: BatchHubJobListProps) {
  const t = useT();

  return (
    <Card
      className={cn('page-surface min-h-[12.5rem] flex-1')}
      data-testid="recent-jobs-card"
    >
      <CardHeader className="flex flex-row items-center justify-between gap-3 pb-2">
        <div>
          <CardTitle className="text-sm font-semibold">
            {t('batchHub.recentTitle')}
          </CardTitle>
          <CardDescription className="text-xs mt-0.5">
            {t('batchHub.recentDesc')}
          </CardDescription>
        </div>
        <Button variant="link" size="sm" asChild className="text-xs px-0">
          <Link to="/jobs">{t('batchHub.jobCenter')}</Link>
        </Button>
      </CardHeader>

      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        {loading ? (
          <div className="flex flex-1 flex-col gap-3 px-4 py-6">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="flex min-h-0 items-center justify-center px-4 py-6">
            <EmptyState
              title={t('emptyState.noActiveJobs')}
              description={t('emptyState.noActiveJobsDesc')}
            />
          </div>
        ) : (
          <ul className="flex min-h-0 flex-1 flex-col divide-y pb-3" data-testid="recent-jobs-list">
            {jobs.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                onContinue={onContinue}
                t={t}
              />
            ))}
          </ul>
        )}
      </CardContent>
      {footer ? <div className="page-surface-footer">{footer}</div> : null}
    </Card>
  );
}

function JobRow({ job, onContinue, t }: { job: JobSummary; onContinue: (job: JobSummary) => void; t: (key: string) => string }) {
  const primary = resolveJobPrimaryNavigation({
    jobId: job.id,
    status: job.status,
    jobType: job.job_type,
    items: [],
    currentPage: 'other',
    navHints: job.nav_hints,
    jobConfig: job.config,
  });

  return (
    <li
      className="px-4 py-3 flex flex-wrap items-center justify-between gap-3"
      data-testid={`job-row-${job.id}`}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="text-[10px]">
            {t('batchHub.batch')}
          </Badge>
          <span className="text-sm font-medium truncate">
            {job.title || t('batchHub.unnamedTask')}
          </span>
          <span className="text-xs text-muted-foreground">
            {formatAggregateJobStatus(job.status)}
          </span>
        </div>
        <div className="text-xs text-muted-foreground mt-1 tabular-nums">
          {t('batchHub.progressSummary')
            .replace('{total}', String(job.progress.total_items))
            .replace('{awaiting}', String(job.progress.awaiting_review))
            .replace('{completed}', String(job.progress.completed))}
          {job.progress.failed
            ? t('batchHub.failedSuffix').replace('{n}', String(job.progress.failed))
            : ''}
        </div>
      </div>

      <div className="shrink-0 flex items-center gap-2">
        {primary.kind === 'link' ? (
          <Button
            variant="link"
            size="sm"
            className="text-sm px-0"
            onClick={() => onContinue(job)}
            data-testid={`continue-job-${job.id}`}
          >
            {primary.label}
          </Button>
        ) : (
          <Button variant="link" size="sm" className="text-sm px-0" asChild>
            <Link to={`/jobs/${job.id}`}>{t('batchHub.viewDetail')}</Link>
          </Button>
        )}
      </div>
    </li>
  );
}
