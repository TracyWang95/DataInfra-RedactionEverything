// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from 'vitest';
import {
  buildAuthHeaders,
  apiClient,
  ApiError,
  API_TIMEOUT,
  VISION_TIMEOUT,
  BATCH_TIMEOUT,
  revokeObjectUrl,
} from '../api-client';
import type { ApiErrorType } from '../api-client';

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

describe('buildAuthHeaders', () => {
  it('returns empty object when no extra headers', () => {
    const headers = buildAuthHeaders();
    expect(headers).toEqual({});
  });

  it('passes through extra headers', () => {
    const headers = buildAuthHeaders({ 'X-Custom': 'value' });
    expect(headers['X-Custom']).toBe('value');
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

  it('defaults errorType to unknown', () => {
    const err = new ApiError('oops');
    expect(err.errorType).toBe('unknown');
  });

  it('stores custom errorType', () => {
    const err = new ApiError('timeout', 0, 'timeout');
    expect(err.errorType).toBe('timeout');
  });

  it('accepts all valid error types', () => {
    const types: ApiErrorType[] = ['network', 'timeout', 'cancelled', 'server', 'auth', 'unknown'];
    types.forEach(t => {
      const err = new ApiError('msg', undefined, t);
      expect(err.errorType).toBe(t);
    });
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

describe('apiClient configuration', () => {
  it('has baseURL set to /api/v1', () => {
    expect(apiClient.defaults.baseURL).toBe('/api/v1');
  });

  it('has timeout set to API_TIMEOUT', () => {
    expect(apiClient.defaults.timeout).toBe(API_TIMEOUT);
  });
});

describe('apiClient response interceptor — error handling', () => {
  it('rejects with ApiError containing status and server errorType', async () => {
    const mockError = {
      response: {
        status: 403,
        data: { message: 'Forbidden' },
      },
      message: 'Request failed with status code 403',
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rejected = (apiClient.interceptors.response as any).handlers[0].rejected!;
    try {
      await rejected(mockError);
      expect.fail('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).message).toBe('Forbidden');
      expect((err as ApiError).status).toBe(403);
      expect((err as ApiError).errorType).toBe('server');
    }
  });

  it('classifies 401 as auth errorType', async () => {
    const mockError = {
      response: {
        status: 401,
        data: { message: 'Unauthorized' },
      },
      message: 'Request failed',
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rejected = (apiClient.interceptors.response as any).handlers[0].rejected!;
    try {
      await rejected(mockError);
      expect.fail('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).errorType).toBe('auth');
      expect((err as ApiError).status).toBe(401);
    }
  });

  it('classifies missing response as network errorType', async () => {
    const mockError = {
      message: 'Network Error',
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rejected = (apiClient.interceptors.response as any).handlers[0].rejected!;
    try {
      await rejected(mockError);
      expect.fail('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).errorType).toBe('network');
    }
  });

  it('classifies ECONNABORTED as timeout errorType', async () => {
    const mockError = {
      code: 'ECONNABORTED',
      message: 'timeout of 60000ms exceeded',
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rejected = (apiClient.interceptors.response as any).handlers[0].rejected!;
    try {
      await rejected(mockError);
      expect.fail('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).errorType).toBe('timeout');
    }
  });

  it('uses detail field when message is missing', async () => {
    const mockError = {
      response: {
        status: 422,
        data: { detail: 'Validation failed' },
      },
      message: 'Request failed',
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rejected = (apiClient.interceptors.response as any).handlers[0].rejected!;
    try {
      await rejected(mockError);
      expect.fail('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).message).toBe('Validation failed');
      expect((err as ApiError).status).toBe(422);
    }
  });

  it('falls back to error.message when response data is empty', async () => {
    const mockError = {
      response: {
        status: 500,
        data: {},
      },
      message: 'Internal Server Error',
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rejected = (apiClient.interceptors.response as any).handlers[0].rejected!;
    try {
      await rejected(mockError);
      expect.fail('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).message).toBe('Internal Server Error');
      expect((err as ApiError).status).toBe(500);
    }
  });

  it('uses "Request failed" when no message is available', async () => {
    const mockError = {};

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rejected = (apiClient.interceptors.response as any).handlers[0].rejected!;
    try {
      await rejected(mockError);
      expect.fail('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).message).toBe('Request failed');
    }
  });
});
