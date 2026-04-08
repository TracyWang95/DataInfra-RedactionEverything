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

/**
 * Fetch with automatic retry for transient failures.
 *
 * - Only retries on network errors and 5xx responses (never 4xx).
 * - Only retries GET requests — mutations are never auto-retried.
 * - Max 2 retries with exponential back-off (1 s, 2 s).
 */
export async function fetchWithRetry(
  input: RequestInfo | URL,
  init: RequestInit & { timeoutMs?: number; maxRetries?: number } = {},
): Promise<Response> {
  const { maxRetries = 2, ...fetchInit } = init;
  const method = (fetchInit.method ?? 'GET').toUpperCase();

  // Never auto-retry mutations
  if (method !== 'GET') {
    return fetchWithTimeout(input, fetchInit);
  }

  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetchWithTimeout(input, fetchInit);

      // Don't retry client errors (4xx) — only server errors (5xx)
      if (res.status < 500) return res;

      // On 5xx, treat as retryable
      lastError = new Error(`Server error: ${res.status}`);
    } catch (error) {
      // Abort errors are not retryable
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw error;
      }
      lastError = error;
    }

    // If we still have retries remaining, wait with exponential backoff
    if (attempt < maxRetries) {
      const delayMs = 1000 * Math.pow(2, attempt); // 1s, 2s
      await new Promise(resolve => setTimeout(resolve, delayMs));
    }
  }

  throw lastError;
}
