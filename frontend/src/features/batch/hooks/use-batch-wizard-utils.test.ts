// Copyright 2026 DataInfra-RedactionEverything Contributors

import { describe, expect, it } from 'vitest';

import {
  deriveReviewConfirmed,
  isJobConfigLockedError,
  mapBackendStatus,
} from './use-batch-wizard-utils';

describe('mapBackendStatus', () => {
  it('maps terminal and legacy statuses onto the wizard state machine', () => {
    expect(mapBackendStatus('failed')).toBe('failed');
    expect(mapBackendStatus('cancelled')).toBe('failed');
    expect(mapBackendStatus('awaiting_review')).toBe('awaiting_review');
    expect(mapBackendStatus('reviewing')).toBe('awaiting_review');
    expect(mapBackendStatus('review_approved')).toBe('review_approved');
    expect(mapBackendStatus('redacting')).toBe('redacting');
    expect(mapBackendStatus('completed')).toBe('completed');
    expect(mapBackendStatus('reviewed')).toBe('completed');
    expect(mapBackendStatus('redacted')).toBe('completed');
    expect(mapBackendStatus('exported')).toBe('completed');
    expect(mapBackendStatus('processing')).toBe('analyzing');
    expect(mapBackendStatus('parsing')).toBe('analyzing');
    expect(mapBackendStatus('ner')).toBe('analyzing');
    expect(mapBackendStatus('vision')).toBe('analyzing');
  });

  it('falls back to pending for unknown statuses', () => {
    expect(mapBackendStatus('')).toBe('pending');
    expect(mapBackendStatus('queued')).toBe('pending');
    expect(mapBackendStatus('garbage')).toBe('pending');
  });
});

describe('deriveReviewConfirmed', () => {
  it('treats completed-with-output and in-flight redaction states as confirmed', () => {
    expect(deriveReviewConfirmed({ status: 'completed' })).toBe(true);
    expect(deriveReviewConfirmed({ status: 'completed', has_output: true })).toBe(true);
    expect(deriveReviewConfirmed({ status: 'review_approved' })).toBe(true);
    expect(deriveReviewConfirmed({ status: 'redacting' })).toBe(true);
  });

  it('completed without output means the redaction was invalidated', () => {
    expect(deriveReviewConfirmed({ status: 'completed', has_output: false })).toBe(false);
    expect(deriveReviewConfirmed({ status: 'awaiting_review' })).toBe(false);
    expect(deriveReviewConfirmed({ status: 'pending' })).toBe(false);
  });
});

describe('isJobConfigLockedError', () => {
  it('recognises 409 and locked-config messages', () => {
    expect(isJobConfigLockedError({ status: 409 })).toBe(true);
    expect(isJobConfigLockedError({ message: 'Job config is locked' })).toBe(true);
    expect(isJobConfigLockedError({ detail: 'config locked after submit' })).toBe(true);
  });

  it('rejects unrelated errors and non-objects', () => {
    expect(isJobConfigLockedError(null)).toBe(false);
    expect(isJobConfigLockedError('locked')).toBe(false);
    expect(isJobConfigLockedError({ status: 500, message: 'boom' })).toBe(false);
  });
});
