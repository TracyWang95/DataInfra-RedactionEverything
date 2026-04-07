// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

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
      className={cn('text-2xs font-medium', statusToneClass(status))}
      title={meta.description}
      data-testid="job-status-badge"
    >
      {formatAggregateJobStatus(status)}
    </Badge>
  );
}

export function JobTypeBadge({ jobType: _jobType }: { jobType: JobTypeApi }) {
  return (
    <Badge
      variant="secondary"
      className="text-2xs font-semibold"
      data-testid="job-type-badge"
    >
      {t('jobs.batchTask')}
    </Badge>
  );
}

export function RedactionStateBadge({ state }: { state: RedactionState }) {
  return (
    <Badge
      variant="outline"
      className={cn('text-2xs font-medium', REDACTION_STATE_CLASS[state])}
      data-testid="redaction-state-badge"
    >
      {getRedactionStateLabel(state)}
    </Badge>
  );
}
