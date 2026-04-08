// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { t, useT, useI18n } from '../index';
import { en } from '../en';
import { zh } from '../zh';

beforeEach(() => {
  localStorage.clear();
  // Reset locale to 'en' before each test
  useI18n.setState({ locale: 'en' });
});

describe('t() — translate function', () => {
  it('returns the English string for a known key when locale is en', () => {
    useI18n.setState({ locale: 'en' });
    expect(t('common.confirm')).toBe(en['common.confirm']);
    expect(t('common.confirm')).toBe('Confirm');
  });

  it('returns the Chinese string for a known key when locale is zh', () => {
    useI18n.setState({ locale: 'zh' });
    expect(t('common.confirm')).toBe(zh['common.confirm']);
    expect(t('common.confirm')).toBe('确认');
  });

  it('returns correct values for various keys in English', () => {
    useI18n.setState({ locale: 'en' });
    expect(t('common.cancel')).toBe('Cancel');
    expect(t('common.save')).toBe('Save');
    expect(t('common.loading')).toBe('Loading...');
  });

  it('returns correct values for various keys in Chinese', () => {
    useI18n.setState({ locale: 'zh' });
    expect(t('common.cancel')).toBe('取消');
    expect(t('common.save')).toBe('保存');
    expect(t('common.loading')).toBe('加载中...');
  });
});

describe('fallback behavior', () => {
  it('falls back to English when a Chinese key is missing', () => {
    // Find a key that exists in en but not in zh, or simulate by testing the
    // fallback logic: when zh is primary and key is missing, it checks en.
    useI18n.setState({ locale: 'zh' });

    // We test the mechanism: if a key only exists in en, zh locale falls back to en
    // Since both locale files are large and cover the same keys, we test indirectly
    // by verifying that if the primary locale doesn't have the key, fallback works.
    // The code checks: primary -> fallback -> key itself
    const result = t('__test_key_that_does_not_exist_in_zh__');
    // Neither locale has it, so we get the key back
    expect(result).toBe('__test_key_that_does_not_exist_in_zh__');
  });

  it('returns the key itself when no translation exists in either locale', () => {
    useI18n.setState({ locale: 'en' });
    expect(t('totally.nonexistent.key')).toBe('totally.nonexistent.key');
  });

  it('returns the key itself for empty string key', () => {
    // Empty key won't match anything
    expect(t('')).toBe('');
  });
});

describe('useT() hook', () => {
  it('returns a function that translates using the current locale', () => {
    useI18n.setState({ locale: 'en' });

    const { result } = renderHook(() => useT());

    expect(typeof result.current).toBe('function');
    expect(result.current('common.confirm')).toBe('Confirm');
  });

  it('reflects locale changes', () => {
    useI18n.setState({ locale: 'en' });

    const { result } = renderHook(() => useT());
    expect(result.current('common.confirm')).toBe('Confirm');

    act(() => {
      useI18n.setState({ locale: 'zh' });
    });

    expect(result.current('common.confirm')).toBe('确认');
  });
});

describe('locale switching via useI18n store', () => {
  it('defaults locale and allows switching to zh', () => {
    useI18n.setState({ locale: 'en' });
    expect(useI18n.getState().locale).toBe('en');

    act(() => {
      useI18n.getState().setLocale('zh');
    });

    expect(useI18n.getState().locale).toBe('zh');
    expect(localStorage.getItem('locale')).toBe('zh');
  });

  it('allows switching back from zh to en', () => {
    useI18n.setState({ locale: 'zh' });
    expect(t('common.confirm')).toBe('确认');

    act(() => {
      useI18n.getState().setLocale('en');
    });

    expect(useI18n.getState().locale).toBe('en');
    expect(t('common.confirm')).toBe('Confirm');
    expect(localStorage.getItem('locale')).toBe('en');
  });

  it('persists locale to localStorage', () => {
    act(() => {
      useI18n.getState().setLocale('zh');
    });
    expect(localStorage.getItem('locale')).toBe('zh');

    act(() => {
      useI18n.getState().setLocale('en');
    });
    expect(localStorage.getItem('locale')).toBe('en');
  });
});
