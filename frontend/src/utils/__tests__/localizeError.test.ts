// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach } from 'vitest';
import { localizeErrorMessage } from '../localizeError';
import { useI18n } from '@/i18n';

beforeEach(() => {
  localStorage.clear();
  useI18n.setState({ locale: 'en' });
});

describe('localizeErrorMessage — network errors', () => {
  it('returns friendly message for "Failed to fetch"', () => {
    const result = localizeErrorMessage(new Error('Failed to fetch'));
    expect(result).toBe('Network connection failed. Check that the service is running.');
  });

  it('returns friendly message for "Network Error"', () => {
    const result = localizeErrorMessage(new Error('Network Error'));
    expect(result).toBe('Network connection failed. Check that the service is running.');
  });

  it('returns friendly message for "NetworkError"', () => {
    const result = localizeErrorMessage(new Error('NetworkError'));
    expect(result).toBe('Network connection failed. Check that the service is running.');
  });

  it('returns Chinese network error message when locale is zh', () => {
    useI18n.setState({ locale: 'zh' });
    const result = localizeErrorMessage(new Error('Failed to fetch'));
    expect(result).toBe('网络连接失败，请检查服务是否已经启动。');
  });
});

describe('localizeErrorMessage — string messages', () => {
  it('passes through a plain English string when locale is en', () => {
    const result = localizeErrorMessage('Something went wrong with processing');
    expect(result).toBe('Something went wrong with processing');
  });

  it('passes through a Chinese string regardless of locale', () => {
    useI18n.setState({ locale: 'en' });
    const result = localizeErrorMessage('处理出错了');
    expect(result).toBe('处理出错了');
  });

  it('returns fallback for non-English, non-Chinese raw strings in zh locale', () => {
    useI18n.setState({ locale: 'zh' });
    // English text in zh locale falls back to t(fallbackKey)
    const result = localizeErrorMessage('Something went wrong');
    expect(result).toBe('操作失败');
  });
});

describe('localizeErrorMessage — Error objects', () => {
  it('extracts message from Error object', () => {
    const err = new Error('File not found on server');
    const result = localizeErrorMessage(err);
    expect(result).toBe('File not found on server');
  });

  it('handles Error with response.data.message', () => {
    const err = {
      message: 'Request failed with status code 404',
      response: {
        status: 404,
        data: { message: 'Resource not found' },
      },
    };
    const result = localizeErrorMessage(err);
    expect(result).toBe('Resource not found');
  });

  it('handles Error with response.data.detail', () => {
    const err = {
      message: 'Request failed',
      response: {
        status: 422,
        data: { detail: 'Validation error in field X' },
      },
    };
    const result = localizeErrorMessage(err);
    expect(result).toBe('Validation error in field X');
  });

  it('maps "Request failed with status code 500" to server error', () => {
    const err = {
      message: 'Request failed with status code 500',
      response: { status: 500, data: {} },
    };
    const result = localizeErrorMessage(err);
    expect(result).toBe('Server error (500).');
  });

  it('maps "Request failed with status code 400" to request failed', () => {
    const err = {
      message: 'Request failed with status code 400',
      response: { status: 400, data: {} },
    };
    const result = localizeErrorMessage(err);
    expect(result).toBe('Request failed (400).');
  });
});

describe('localizeErrorMessage — unknown error types', () => {
  it('returns fallback for null', () => {
    const result = localizeErrorMessage(null);
    expect(result).toBe('Error');
  });

  it('returns fallback for undefined', () => {
    const result = localizeErrorMessage(undefined);
    expect(result).toBe('Error');
  });

  it('returns fallback for empty object', () => {
    const result = localizeErrorMessage({});
    expect(result).toBe('Error');
  });

  it('returns fallback for number', () => {
    const result = localizeErrorMessage(42);
    expect(result).toBe('Error');
  });

  it('returns Chinese fallback when locale is zh', () => {
    useI18n.setState({ locale: 'zh' });
    const result = localizeErrorMessage(null);
    expect(result).toBe('操作失败');
  });

  it('uses custom fallbackKey when provided', () => {
    const result = localizeErrorMessage(null, 'common.retry');
    expect(result).toBe('Retry');
  });
});
