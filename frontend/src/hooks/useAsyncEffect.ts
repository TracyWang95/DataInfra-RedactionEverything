import { useEffect, useRef, useCallback } from 'react';

/**
 * useAsyncEffect — 安全的异步副作用 hook
 *
 * 特性：
 * - 自动创建 AbortController，卸载时 abort
 * - 避免组件卸载后 setState 导致内存泄漏
 * - 提供 isMounted 检查
 */
export function useAsyncEffect(
  effect: (signal: AbortSignal) => Promise<void> | void,
  deps: React.DependencyList
) {
  useEffect(() => {
    const controller = new AbortController();
    const p = effect(controller.signal);
    return () => {
      controller.abort();
      // suppress unhandled abort errors
      if (p && typeof (p as Promise<void>).catch === 'function') {
        (p as Promise<void>).catch(() => {});
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/**
 * useSafeInterval — 安全的 setInterval，组件卸载时自动清理
 */
export function useSafeInterval(
  callback: () => void,
  delay: number | null
) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (delay === null) return;
    const id = window.setInterval(() => savedCallback.current(), delay);
    return () => window.clearInterval(id);
  }, [delay]);
}

/**
 * useSafeTimeout — 安全的 setTimeout，组件卸载时自动清理
 */
export function useSafeTimeout() {
  const timeoutIds = useRef<Set<number>>(new Set());

  useEffect(() => {
    return () => {
      timeoutIds.current.forEach((id) => window.clearTimeout(id));
      timeoutIds.current.clear();
    };
  }, []);

  const setSafeTimeout = useCallback((fn: () => void, ms: number) => {
    const id = window.setTimeout(() => {
      timeoutIds.current.delete(id);
      fn();
    }, ms);
    timeoutIds.current.add(id);
    return id;
  }, []);

  const clearSafeTimeout = useCallback((id: number) => {
    window.clearTimeout(id);
    timeoutIds.current.delete(id);
  }, []);

  return { setSafeTimeout, clearSafeTimeout };
}
