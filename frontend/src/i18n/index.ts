import { create } from 'zustand';
import { zh } from './zh';
import { en } from './en';

export type Locale = 'zh' | 'en';

interface I18nStore {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

export const useI18n = create<I18nStore>((set) => ({
  locale: (localStorage.getItem('locale') as Locale) || 'en',
  setLocale: (locale) => {
    localStorage.setItem('locale', locale);
    set({ locale });
  },
}));

/** Non-reactive translation helper (use outside React components) */
export function t(key: string): string {
  const locale = useI18n.getState().locale;
  const translations = locale === 'en' ? en : zh;
  return translations[key] || key;
}

/** Reactive translation hook (use inside React components) */
export function useT() {
  const locale = useI18n((s) => s.locale);
  return (key: string): string => {
    const translations = locale === 'en' ? en : zh;
    return translations[key] || key;
  };
}
