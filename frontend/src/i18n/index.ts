// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback } from 'react';
import { create } from 'zustand';
import { zh } from './zh';
import { en } from './en';
import { STORAGE_KEYS } from '@/constants/storage-keys';

export type Locale = 'zh' | 'en';

interface I18nStore {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

function resolveInitialLocale(): Locale {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(STORAGE_KEYS.LOCALE);
  } catch {
    stored = null;
  }

  if (stored === 'zh' || stored === 'en') return stored;

  if (typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('zh')) {
    return 'zh';
  }

  return 'en';
}

function getTranslations(locale: Locale) {
  return locale === 'en' ? en : zh;
}

function translate(locale: Locale, key: string): string {
  const primary = getTranslations(locale);
  if (key in primary) return primary[key];

  const fallback = getTranslations(locale === 'en' ? 'zh' : 'en');
  if (key in fallback) return fallback[key];

  return key;
}

export const useI18n = create<I18nStore>((set) => ({
  locale: resolveInitialLocale(),
  setLocale: (locale) => {
    localStorage.setItem(STORAGE_KEYS.LOCALE, locale);
    set({ locale });
  },
}));

/**
 * Non-reactive — use only in event handlers, callbacks, and utilities.
 * For render-time translations, use the {@link useT} hook instead.
 */
export function t(key: string): string {
  return translate(useI18n.getState().locale, key);
}

/**
 * Reactive translation hook — re-renders when the locale changes.
 * Always prefer this over {@link t} inside React component render bodies.
 */
export function useT() {
  const locale = useI18n((s) => s.locale);
  return useCallback((key: string): string => translate(locale, key), [locale]);
}
