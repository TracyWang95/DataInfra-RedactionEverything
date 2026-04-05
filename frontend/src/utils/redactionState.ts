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
  redacted: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/10',
  awaiting_review: 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/10',
  unredacted: 'bg-gray-50 text-gray-500 ring-1 ring-inset ring-gray-500/10',
};

export const BADGE_BASE = 'inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium whitespace-nowrap';

export const REDACTION_STATE_RING: Record<RedactionState, string> = {
  redacted: 'ring-emerald-200',
  awaiting_review: 'ring-amber-200',
  unredacted: 'ring-gray-200',
};
