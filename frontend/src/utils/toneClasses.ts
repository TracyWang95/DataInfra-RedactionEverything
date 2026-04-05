import type { JobStatusTone } from './jobStatusLabels';

export const toneBadgeClass: Record<JobStatusTone, string> = {
  neutral: 'tone-badge-neutral',
  brand: 'tone-badge-brand',
  warning: 'tone-badge-warning',
  review: 'tone-badge-review',
  success: 'tone-badge-success',
  danger: 'tone-badge-danger',
  muted: 'tone-badge-muted',
};

export const tonePanelClass = {
  neutral: 'tone-panel-neutral',
  brand: 'tone-panel-brand',
  review: 'tone-panel-review',
  warning: 'tone-panel-warning',
  success: 'tone-panel-success',
  danger: 'tone-panel-danger',
  muted: 'tone-panel-muted',
} as const;
