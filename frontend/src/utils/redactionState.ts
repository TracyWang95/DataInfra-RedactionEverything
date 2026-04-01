/**
 * 三态脱敏状态：已脱敏 / 待审核 / 未脱敏
 */
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
    // 脏数据兜底：status=completed 但没有输出文件，视为待审核（允许重新走审阅流程）
    itemStatus === 'completed'
  )
    return 'awaiting_review';
  return 'unredacted';
}

export const REDACTION_STATE_LABEL: Record<RedactionState, string> = {
  redacted: '已脱敏',
  awaiting_review: '待审核',
  unredacted: '未脱敏',
};

export const REDACTION_STATE_CLASS: Record<RedactionState, string> = {
  redacted: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-600/10',
  awaiting_review: 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-600/10',
  unredacted: 'bg-gray-50 text-gray-500 ring-1 ring-inset ring-gray-500/10',
};

/** 统一 badge 外壳样式，和配色类组合使用：className={`${BADGE_BASE} ${REDACTION_STATE_CLASS[state]}`} */
export const BADGE_BASE = 'inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium whitespace-nowrap';

export const REDACTION_STATE_RING: Record<RedactionState, string> = {
  redacted: 'ring-emerald-200',
  awaiting_review: 'ring-amber-200',
  unredacted: 'ring-gray-200',
};
