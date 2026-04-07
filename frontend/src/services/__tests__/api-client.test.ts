import { describe, it, expect, beforeEach } from 'vitest';
import {
  getAuthToken,
  setAuthToken,
  clearAuthToken,
  buildAuthHeaders,
  ApiError,
  API_TIMEOUT,
  VISION_TIMEOUT,
  BATCH_TIMEOUT,
  revokeObjectUrl,
} from '../api-client';

describe('timeout constants', () => {
  it('API_TIMEOUT is 60 seconds', () => {
    expect(API_TIMEOUT).toBe(60_000);
  });

  it('VISION_TIMEOUT is 400 seconds', () => {
    expect(VISION_TIMEOUT).toBe(400_000);
  });

  it('BATCH_TIMEOUT is 120 seconds', () => {
    expect(BATCH_TIMEOUT).toBe(120_000);
  });
});

describe('token management', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('getAuthToken returns null when no token is set', () => {
    expect(getAuthToken()).toBeNull();
  });

  it('setAuthToken stores and getAuthToken retrieves the token', () => {
    setAuthToken('my-jwt-token');
    expect(getAuthToken()).toBe('my-jwt-token');
  });

  it('clearAuthToken removes the stored token', () => {
    setAuthToken('token-to-clear');
    clearAuthToken();
    expect(getAuthToken()).toBeNull();
  });

  it('setAuthToken overwrites a previous token', () => {
    setAuthToken('first');
    setAuthToken('second');
    expect(getAuthToken()).toBe('second');
  });
});

describe('buildAuthHeaders', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns empty object when no token and no extra headers', () => {
    const headers = buildAuthHeaders();
    expect(headers).toEqual({});
  });

  it('includes Authorization header when token is set', () => {
    setAuthToken('test-token');
    const headers = buildAuthHeaders();
    expect(headers['Authorization']).toBe('Bearer test-token');
  });

  it('merges extra headers with Authorization', () => {
    setAuthToken('tok');
    const headers = buildAuthHeaders({ 'Content-Type': 'application/json' });
    expect(headers['Authorization']).toBe('Bearer tok');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('passes through extra headers even without token', () => {
    const headers = buildAuthHeaders({ 'X-Custom': 'value' });
    expect(headers['X-Custom']).toBe('value');
    expect(headers['Authorization']).toBeUndefined();
  });
});

describe('ApiError', () => {
  it('has name "ApiError"', () => {
    const err = new ApiError('test');
    expect(err.name).toBe('ApiError');
  });

  it('stores message and optional status', () => {
    const err = new ApiError('Not found', 404);
    expect(err.message).toBe('Not found');
    expect(err.status).toBe(404);
  });

  it('is an instance of Error', () => {
    const err = new ApiError('fail');
    expect(err).toBeInstanceOf(Error);
  });

  it('has undefined status when not provided', () => {
    const err = new ApiError('oops');
    expect(err.status).toBeUndefined();
  });
});

describe('revokeObjectUrl', () => {
  it('does not throw for null or undefined', () => {
    expect(() => revokeObjectUrl(null)).not.toThrow();
    expect(() => revokeObjectUrl(undefined)).not.toThrow();
  });

  it('does not throw for non-blob URL', () => {
    expect(() => revokeObjectUrl('https://example.com')).not.toThrow();
  });
});
