import { useState, useEffect, useCallback } from 'react';

/**
 * Dark mode hook.
 * Adds/removes the `dark` class on <html> and persists preference to localStorage.
 *
 * NOTE: Only Layout shell elements have dark: variants right now.
 * Inner page components (dropdowns, modals, etc.) are NOT yet adapted,
 * so we scope the visual change to Layout's own elements via dark: classes.
 * The class is still toggled on <html> so future dark: additions work immediately.
 */
export function useDarkMode() {
  const [dark, setDark] = useState(() => {
    if (typeof window === 'undefined') return false;
    const saved = localStorage.getItem('theme');
    if (saved) return saved === 'dark';
    return false; // default to light until all components are adapted
  });

  useEffect(() => {
    const root = document.documentElement;
    if (dark) {
      root.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      root.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  }, [dark]);

  const toggle = useCallback(() => setDark((d) => !d), []);

  return { dark, toggle };
}
