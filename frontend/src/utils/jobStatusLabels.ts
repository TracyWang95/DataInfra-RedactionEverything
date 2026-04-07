// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { t } from '@/i18n';

export type JobStatusTone = 'neutral' | 'brand' | 'warning' | 'review' | 'success' | 'danger' | 'muted';

export type JobStatusMeta = {
  label: string;
  description: string;
  tone: JobStatusTone;
};

type StatusConfig = {
  labelKey: string;
  descriptionKey: string;
  tone: JobStatusTone;
};

const AGGREGATE_JOB_STATUS_CONFIG: Record<string, StatusConfig> = {
  draft: {
    labelKey: 'job.status.draft',
    descriptionKey: 'job.statusDesc.draft',
    tone: 'neutral',
  },
  queued: {
    labelKey: 'job.status.queued',
    descriptionKey: 'job.statusDesc.queued',
    tone: 'brand',
  },
  processing: {
    labelKey: 'job.status.processing',
    descriptionKey: 'job.statusDesc.processing',
    tone: 'warning',
  },
  running: {
    labelKey: 'job.status.running',
    descriptionKey: 'job.statusDesc.running',
    tone: 'warning',
  },
  awaiting_review: {
    labelKey: 'job.status.awaiting_review',
    descriptionKey: 'job.statusDesc.awaiting_review',
    tone: 'review',
  },
  redacting: {
    labelKey: 'job.status.redacting',
    descriptionKey: 'job.statusDesc.redacting',
    tone: 'brand',
  },
  completed: {
    labelKey: 'job.status.completed',
    descriptionKey: 'job.statusDesc.completed',
    tone: 'success',
  },
  failed: {
    labelKey: 'job.status.failed',
    descriptionKey: 'job.statusDesc.failed',
    tone: 'danger',
  },
  cancelled: {
    labelKey: 'job.status.cancelled',
    descriptionKey: 'job.statusDesc.cancelled',
    tone: 'muted',
  },
};

const JOB_ITEM_ONLY_CONFIG: Record<string, StatusConfig> = {
  pending: {
    labelKey: 'job.status.pending',
    descriptionKey: 'job.statusDesc.pending',
    tone: 'neutral',
  },
  parsing: {
    labelKey: 'job.status.parsing',
    descriptionKey: 'job.statusDesc.parsing',
    tone: 'warning',
  },
  ner: {
    labelKey: 'job.status.ner',
    descriptionKey: 'job.statusDesc.ner',
    tone: 'warning',
  },
  vision: {
    labelKey: 'job.status.vision',
    descriptionKey: 'job.statusDesc.vision',
    tone: 'warning',
  },
  review_approved: {
    labelKey: 'job.status.review_approved',
    descriptionKey: 'job.statusDesc.review_approved',
    tone: 'review',
  },
};

function buildStatusMeta(config: StatusConfig): JobStatusMeta {
  return {
    label: t(config.labelKey),
    description: t(config.descriptionKey),
    tone: config.tone,
  };
}

function fallbackStatusMeta(status: string): JobStatusMeta {
  return {
    label: status,
    description: t('job.statusDesc.unknown'),
    tone: 'neutral',
  };
}

export function getAggregateJobStatusMeta(status: string): JobStatusMeta {
  const config = AGGREGATE_JOB_STATUS_CONFIG[status];
  return config ? buildStatusMeta(config) : fallbackStatusMeta(status);
}

export function getJobItemStatusMeta(status: string): JobStatusMeta {
  const config = AGGREGATE_JOB_STATUS_CONFIG[status] ?? JOB_ITEM_ONLY_CONFIG[status];
  return config ? buildStatusMeta(config) : fallbackStatusMeta(status);
}

export function formatAggregateJobStatus(status: string): string {
  return getAggregateJobStatusMeta(status).label;
}

export function formatJobItemStatus(status: string): string {
  return getJobItemStatusMeta(status).label;
}
