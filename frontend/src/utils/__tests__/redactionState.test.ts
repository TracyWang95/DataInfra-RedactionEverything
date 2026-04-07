// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from 'vitest';
import {
  resolveRedactionState,
  REDACTION_STATE_CLASS,
  REDACTION_STATE_RING,
  BADGE_BASE,
} from '../redactionState';

describe('resolveRedactionState', () => {
  it('returns "redacted" when hasOutput is true regardless of status', () => {
    expect(resolveRedactionState(true)).toBe('redacted');
    expect(resolveRedactionState(true, 'awaiting_review')).toBe('redacted');
    expect(resolveRedactionState(true, 'draft')).toBe('redacted');
  });

  it('returns "awaiting_review" for review-related statuses without output', () => {
    expect(resolveRedactionState(false, 'awaiting_review')).toBe('awaiting_review');
    expect(resolveRedactionState(false, 'review_approved')).toBe('awaiting_review');
    expect(resolveRedactionState(false, 'redacting')).toBe('awaiting_review');
    expect(resolveRedactionState(false, 'completed')).toBe('awaiting_review');
  });

  it('returns "unredacted" for other statuses without output', () => {
    expect(resolveRedactionState(false)).toBe('unredacted');
    expect(resolveRedactionState(false, null)).toBe('unredacted');
    expect(resolveRedactionState(false, 'draft')).toBe('unredacted');
    expect(resolveRedactionState(false, 'processing')).toBe('unredacted');
    expect(resolveRedactionState(false, 'unknown_status')).toBe('unredacted');
  });
});

describe('REDACTION_STATE_CLASS', () => {
  it('maps all three states to CSS classes', () => {
    expect(REDACTION_STATE_CLASS.redacted).toBe('tone-badge-success');
    expect(REDACTION_STATE_CLASS.awaiting_review).toBe('tone-badge-warning');
    expect(REDACTION_STATE_CLASS.unredacted).toBe('tone-badge-muted');
  });
});

describe('REDACTION_STATE_RING', () => {
  it('maps all three states to ring classes', () => {
    expect(REDACTION_STATE_RING.redacted).toContain('success');
    expect(REDACTION_STATE_RING.awaiting_review).toContain('warning');
    expect(REDACTION_STATE_RING.unredacted).toContain('ring-border');
  });
});

describe('BADGE_BASE', () => {
  it('is a non-empty string of utility classes', () => {
    expect(BADGE_BASE).toBeTruthy();
    expect(BADGE_BASE).toContain('inline-flex');
    expect(BADGE_BASE).toContain('rounded-full');
  });
});
