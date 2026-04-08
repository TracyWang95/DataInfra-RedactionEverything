// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import axios, { type AxiosRequestConfig } from 'axios';

// ─── Timeout constants ───────────────────────────────────────
export const API_TIMEOUT = 60_000;
export const VISION_TIMEOUT = 400_000;
export const BATCH_TIMEOUT = 120_000;

// ─── Error types ─────────────────────────────────────────────

export type ApiErrorType = 'network' | 'timeout' | 'cancelled' | 'server' | 'auth' | 'unknown';

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
    public errorType: ApiErrorType = 'unknown',
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ─── Client ──────────────────────────────────────────────────

export const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: API_TIMEOUT,
  withCredentials: true, // Send httpOnly cookies automatically
});

// Response: unwrap data, handle errors with classified error types
apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message =
      error.response?.data?.message ||
      error.response?.data?.detail ||
      error.message ||
      'Request failed';

    let errorType: ApiErrorType;
    if (axios.isCancel(error)) {
      errorType = 'cancelled';
    } else if (error.code === 'ECONNABORTED') {
      errorType = 'timeout';
    } else if (!error.response) {
      errorType = 'network';
    } else if (error.response.status === 401) {
      errorType = 'auth';
    } else {
      errorType = 'server';
    }

    if (import.meta.env.DEV) {
      console.error(`API Error [${errorType}]:`, message);
    }
    return Promise.reject(new ApiError(message, error.response?.status, errorType));
  },
);

// ─── Typed request helpers ────────────────────────────────────

export function get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return apiClient.get(url, config) as Promise<T>;
}

export function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return apiClient.post(url, data, config) as Promise<T>;
}

export function put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return apiClient.put(url, data, config) as Promise<T>;
}

export function del<T = void>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return apiClient.delete(url, config) as Promise<T>;
}

// ─── Authenticated fetch helpers ─────────────────────────────

export function buildAuthHeaders(extra?: Record<string, string>): Record<string, string> {
  return { ...extra };
}

/** Drop-in replacement for `fetch()` that sends cookies automatically. */
export function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, {
    ...init,
    credentials: 'include',
    headers: init?.headers,
  });
}

export async function downloadFile(url: string, filename: string): Promise<void> {
  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) throw new ApiError(`Download failed: ${res.status}`, res.status, 'server');
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(objectUrl);
}

export async function authenticatedBlobUrl(url: string, mime?: string): Promise<string> {
  const blob = await fetchBlob(url);
  return URL.createObjectURL(mime ? new Blob([blob], { type: mime }) : blob);
}

export async function fetchBlob(url: string, init?: RequestInit): Promise<Blob> {
  const res = await fetch(url, {
    ...init,
    credentials: 'include',
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail ?? err);
    } catch { /* ignore */ }
    throw new ApiError(msg, res.status, 'server');
  }
  return res.blob();
}

export function revokeObjectUrl(url: string | null | undefined): void {
  if (url?.startsWith('blob:')) {
    URL.revokeObjectURL(url);
  }
}
