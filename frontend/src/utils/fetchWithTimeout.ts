/**
 * 原生 fetch 无默认超时，后端不可达时会长时间挂起 → 页面一直转圈。
 */
export function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit & { timeoutMs?: number } = {}
): Promise<Response> {
  const { timeoutMs = 30000, signal: outerSignal, ...rest } = init;
  const ac = new AbortController();
  const timer = window.setTimeout(() => ac.abort(), timeoutMs);

  if (outerSignal) {
    if (outerSignal.aborted) {
      clearTimeout(timer);
      return Promise.reject(new DOMException('Aborted', 'AbortError'));
    }
    outerSignal.addEventListener('abort', () => {
      clearTimeout(timer);
      ac.abort();
    });
  }

  return fetch(input, { ...rest, signal: ac.signal }).finally(() => {
    window.clearTimeout(timer);
  });
}
