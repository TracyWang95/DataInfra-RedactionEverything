// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { authFetch } from '@/services/api-client';


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

  return authFetch(input, { ...rest, signal: ac.signal }).finally(() => {
    window.clearTimeout(timer);
  });
}
