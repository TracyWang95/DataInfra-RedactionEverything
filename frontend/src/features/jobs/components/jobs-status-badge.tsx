import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  formatAggregateJobStatus,
  getAggregateJobStatusMeta,
  type JobStatusTone,
} from '@/utils/jobStatusLabels';
import type { JobTypeApi } from '@/services/jobsApi';
import { t } from '@/i18n';
import { getRedactionStateLabel, REDACTION_STATE_CLASS, type RedactionState } from '@/utils/redactionState';

export function toneClass(tone: JobStatusTone): string {
  if (tone === 'success') return 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/10';
  if (tone === 'danger') return 'bg-red-50 text-red-600 ring-1 ring-inset ring-red-600/10';
  if (tone === 'warning') return 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/10';
  if (tone === 'review') return 'bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-600/10';
  if (tone === 'brand') return 'bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-600/10';
  if (tone === 'muted') return 'bg-muted text-muted-foreground ring-1 ring-inset ring-border';
  return 'bg-slate-50 text-slate-600 ring-1 ring-inset ring-slate-500/10';
}

export function statusToneClass(status: string): string {
  return toneClass(getAggregateJobStatusMeta(status).tone);
}

/** Job status badge using ShadCN Badge */
export function JobStatusBadge({ status }: { status: string }) {
  const meta = getAggregateJobStatusMeta(status);
  return (
    <Badge
      variant="outline"
      className={cn('text-2xs font-medium border-0', statusToneClass(status))}
      title={meta.description}
      data-testid="job-status-badge"
    >
      {formatAggregateJobStatus(status)}
    </Badge>
  );
}

/** Job type badge */
export function JobTypeBadge({ jobType: _jobType }: { jobType: JobTypeApi }) {
  return (
    <Badge
      variant="secondary"
      className="text-2xs font-semibold border-0"
      data-testid="job-type-badge"
    >
      {t('jobs.batchTask')}
    </Badge>
  );
}

/** Redaction state badge for file items */
export function RedactionStateBadge({ state }: { state: RedactionState }) {
  return (
    <Badge
      variant="outline"
      className={cn('text-2xs font-medium border-0', REDACTION_STATE_CLASS[state])}
      data-testid="redaction-state-badge"
    >
      {getRedactionStateLabel(state)}
    </Badge>
  );
}
