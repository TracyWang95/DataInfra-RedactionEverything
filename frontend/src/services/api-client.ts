// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import axios, { type AxiosRequestConfig } from 'axios';

// ─── Timeout constants ───────────────────────────────────────
export const API_TIMEOUT = 60_000;
export const VISION_TIMEOUT = 400_000;
export const BATCH_TIMEOUT = 120_000;

const AUTH_TOKEN_KEY = 'auth_token';

export function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

export const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: API_TIMEOUT,
});

apiClient.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response: unwrap data, handle errors
apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message =
      error.response?.data?.message ||
      error.response?.data?.detail ||
      error.message ||
      'Request failed';
    if (import.meta.env.DEV) {
      console.error('API Error:', message);
    }
    return Promise.reject(new ApiError(message, error.response?.status));
  },
);

// ─── Error class ──────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

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

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = getAuthToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

export function buildAuthHeaders(extra?: Record<string, string>): Record<string, string> {
  return authHeaders(extra);
}

/** Drop-in replacement for `fetch()` that attaches the JWT Bearer token. */
export function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, {
    ...init,
    headers: authHeaders(init?.headers as Record<string, string> | undefined),
  });
}

export async function downloadFile(url: string, filename: string): Promise<void> {
  const token = getAuthToken();
  if (!token) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    return;
  }
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Download failed: ${res.status}`, res.status);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(objectUrl);
}

export async function authenticatedBlobUrl(url: string, mime?: string): Promise<string> {
  const token = getAuthToken();
  if (!token) return url;
  const blob = await fetchBlob(url, { headers: authHeaders() });
  return URL.createObjectURL(mime ? new Blob([blob], { type: mime }) : blob);
}

export async function fetchBlob(url: string, init?: RequestInit): Promise<Blob> {
  const res = await fetch(url, {
    ...init,
    headers: authHeaders(init?.headers as Record<string, string>),
    credentials: 'same-origin',
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail ?? err);
    } catch { /* ignore */ }
    throw new ApiError(msg, res.status);
  }
  return res.blob();
}

export function revokeObjectUrl(url: string | null | undefined): void {
  if (url?.startsWith('blob:')) {
    URL.revokeObjectURL(url);
  }
}
