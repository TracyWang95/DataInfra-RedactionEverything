// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback } from 'react';
import { create } from 'zustand';
import { zh } from './zh';
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

// The en locale is code-split out of the main bundle: it is loaded on demand at
// startup (only when the persisted language is en) and on language switch.
let en: Record<string, string> | null = null;
let enPromise: Promise<void> | null = null;

function loadEn(): Promise<void> {
  enPromise ??= import('./en').then(
    (m) => {
      en = m.en;
    },
    (err) => {
      enPromise = null;
      throw err;
    },
  );
  return enPromise;
}

function translate(locale: Locale, key: string): string {
  const primary = locale === 'en' ? en : zh;
  if (primary && key in primary) return primary[key];

  const fallback = locale === 'en' ? zh : en;
  if (fallback && key in fallback) return fallback[key];

  return key;
}

export const useI18n = create<I18nStore>((set) => ({
  locale: resolveInitialLocale(),
  setLocale: (locale) => {
    localStorage.setItem(STORAGE_KEYS.LOCALE, locale);
    if (locale === 'en' && !en) {
      // Await the locale bundle before applying so the UI never flashes zh.
      loadEn().then(
        () => set({ locale }),
        () => set({ locale }),
      );
      return;
    }
    set({ locale });
  },
}));

/**
 * Resolves once the translations for the initial locale are ready.
 * Called from main.tsx before the first render; zh is bundled statically,
 * so this only awaits a network fetch when the persisted language is en.
 */
export function initI18n(): Promise<void> {
  if (useI18n.getState().locale === 'en') {
    return loadEn().catch(() => {
      // Keep booting with the zh fallback; translate() falls back per key.
    });
  }
  return Promise.resolve();
}

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
