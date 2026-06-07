// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { t } from '@/i18n';

export type RedactionState = 'redacted' | 'awaiting_review' | 'unredacted';

export function resolveRedactionState(
  hasOutput: boolean,
  itemStatus?: string | null,
): RedactionState {
  if (hasOutput) return 'redacted';
  if (
    itemStatus === 'awaiting_review' ||
    itemStatus === 'review_approved' ||
    itemStatus === 'redacting' ||
    itemStatus === 'completed'
  ) {
    return 'awaiting_review';
  }
  return 'unredacted';
}

export function getRedactionStateLabel(state: RedactionState): string {
  if (state === 'redacted') return t('redactionState.redacted');
  if (state === 'awaiting_review') return t('redactionState.awaiting_review');
  return t('redactionState.unredacted');
}

export const REDACTION_STATE_CLASS: Record<RedactionState, string> = {
  redacted: 'tone-badge-success',
  awaiting_review: 'tone-badge-warning',
  unredacted: 'tone-badge-muted',
};

export const BADGE_BASE =
  'inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium whitespace-nowrap';

export const REDACTION_STATE_RING: Record<RedactionState, string> = {
  redacted: 'ring-[var(--success-border)]',
  awaiting_review: 'ring-[var(--warning-border)]',
  unredacted: 'ring-border',
};
