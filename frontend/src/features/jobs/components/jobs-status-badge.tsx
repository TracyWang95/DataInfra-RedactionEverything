// Copyright 2026 DataInfra-RedactionEverything Contributors

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  formatAggregateJobStatus,
  getAggregateJobStatusMeta,
  type JobStatusTone,
} from '@/utils/jobStatusLabels';
import type { JobTypeApi } from '@/services/jobsApi';
import { useT } from '@/i18n';
import {
  getRedactionStateLabel,
  REDACTION_STATE_CLASS,
  type RedactionState,
} from '@/utils/redactionState';
import { toneBadgeClass } from '@/utils/toneClasses';

export function toneClass(tone: JobStatusTone): string {
  return toneBadgeClass[tone] ?? toneBadgeClass.neutral;
}

export function statusToneClass(status: string): string {
  return toneClass(getAggregateJobStatusMeta(status).tone);
}

export function JobStatusBadge({ status }: { status: string }) {
  const meta = getAggregateJobStatusMeta(status);
  return (
    <Badge
      variant="outline"
      className={cn('shrink-0 whitespace-nowrap text-2xs font-medium', statusToneClass(status))}
      title={meta.description}
      data-testid="job-status-badge"
    >
      {formatAggregateJobStatus(status)}
    </Badge>
  );
}

export function JobTypeBadge({ jobType }: { jobType: JobTypeApi }) {
  const t = useT();
  return (
    <Badge
      variant="secondary"
      className="shrink-0 whitespace-nowrap text-2xs font-semibold"
      data-testid="job-type-badge"
    >
      {jobType === 'structured_batch' ? t('jobs.structuredTask') : t('jobs.batchTask')}
    </Badge>
  );
}

export function RedactionStateBadge({ state }: { state: RedactionState }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        'shrink-0 whitespace-nowrap text-2xs font-medium',
        REDACTION_STATE_CLASS[state],
      )}
      data-testid="redaction-state-badge"
    >
      {getRedactionStateLabel(state)}
    </Badge>
  );
}
