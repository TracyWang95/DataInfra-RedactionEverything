// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useIsMobile } from '../use-mobile';

function setViewportWidth(width: number) {
  Object.defineProperty(window, 'innerWidth', {
    writable: true,
    configurable: true,
    value: width,
  });
}

// Stub matchMedia so it works in jsdom
function stubMatchMedia(matches: boolean) {
  const listeners: Array<(e: MediaQueryListEvent) => void> = [];
  const mql: Partial<MediaQueryList> = {
    matches,
    media: '',
    onchange: null,
    addEventListener: vi.fn((_event: string, cb: EventListenerOrEventListenerObject) => {
      listeners.push(cb as (e: MediaQueryListEvent) => void);
    }),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  };
  window.matchMedia = vi.fn().mockReturnValue(mql);
  return { mql, listeners };
}

describe('useIsMobile', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('returns true when viewport is below 768px', () => {
    setViewportWidth(500);
    stubMatchMedia(true);

    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it('returns false when viewport is 768px or above', () => {
    setViewportWidth(1024);
    stubMatchMedia(false);

    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });

  it('returns false at exactly 768px', () => {
    setViewportWidth(768);
    stubMatchMedia(false);

    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });

  it('returns true at 767px (just below breakpoint)', () => {
    setViewportWidth(767);
    stubMatchMedia(true);

    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it('updates when the viewport changes via matchMedia listener', () => {
    setViewportWidth(1024);
    const { listeners } = stubMatchMedia(false);

    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    // Simulate viewport shrinking below breakpoint
    act(() => {
      setViewportWidth(500);
      for (const cb of listeners) {
        cb({ matches: true } as MediaQueryListEvent);
      }
    });

    expect(result.current).toBe(true);
  });

  it('cleans up matchMedia listener on unmount', () => {
    setViewportWidth(1024);
    const { mql } = stubMatchMedia(false);

    const { unmount } = renderHook(() => useIsMobile());
    unmount();

    expect(mql.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function));
  });
});
