// Copyright 2026 DataInfra-RedactionEverything Contributors

import axios, { AxiosHeaders, type AxiosRequestConfig } from 'axios';

// ─── Timeout constants ───────────────────────────────────────
export const API_TIMEOUT = 60_000;
export const VISION_TIMEOUT = 900_000;
export const BATCH_TIMEOUT = 120_000;
export const AUTH_UNAUTHORIZED_EVENT = 'auth:unauthorized';
const HTTP_STATUS_UNAUTHORIZED = 401;
const DEFAULT_API_PREFIX = '/api/v1';
const RAW_API_PREFIX = import.meta.env.VITE_API_PREFIX ?? DEFAULT_API_PREFIX;

export function normalizeApiPrefix(prefix: string): string {
  const trimmed = String(prefix || '').trim();
  if (!trimmed) return DEFAULT_API_PREFIX;
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed.replace(/\/+$/, '') || DEFAULT_API_PREFIX;
  }
  const withLeadingSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  const normalized = withLeadingSlash.replace(/\/+$/, '');
  return normalized || DEFAULT_API_PREFIX;
}

export const API_PREFIX = normalizeApiPrefix(RAW_API_PREFIX);

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
  baseURL: API_PREFIX,
  timeout: API_TIMEOUT,
  withCredentials: true, // Send httpOnly cookies automatically
});

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
const AUTH_EVENT_SUPPRESSED_PATHS = ['/api/v1/auth/login', '/api/v1/auth/setup'];

function getRequestUrl(input: RequestInfo | URL): string | undefined {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  if (typeof Request !== 'undefined' && input instanceof Request) return input.url;
  return undefined;
}

function shouldEmitUnauthorized(url?: string): boolean {
  if (!url) return true;
  return !AUTH_EVENT_SUPPRESSED_PATHS.some((prefix) => {
    if (url.includes(prefix)) return true;
    const suffix = prefix.replace(DEFAULT_API_PREFIX, '');
    return url.endsWith(suffix) || url.includes(`${API_PREFIX}${suffix}`);
  });
}

function emitUnauthorized(url?: string): void {
  if (typeof window === 'undefined' || !shouldEmitUnauthorized(url)) return;
  window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT, { detail: { url } }));
}

function rewriteLegacyApiPath(path: string): string {
  if (API_PREFIX === DEFAULT_API_PREFIX) return path;
  if (path === DEFAULT_API_PREFIX) return API_PREFIX;
  if (path.startsWith(`${DEFAULT_API_PREFIX}/`)) {
    return `${API_PREFIX}${path.slice(DEFAULT_API_PREFIX.length)}`;
  }
  return path;
}

function normalizeApiInput(input: RequestInfo | URL): RequestInfo | URL {
  if (typeof input === 'string') {
    return rewriteLegacyApiPath(input);
  }
  if (input instanceof URL) {
    const rewritten = new URL(input.toString());
    rewritten.pathname = rewriteLegacyApiPath(rewritten.pathname);
    return rewritten;
  }
  return input;
}

export function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const raw = document.cookie.split('; ').find((cookie) => cookie.startsWith('csrf_token='));
  if (!raw) return null;
  return decodeURIComponent(raw.slice('csrf_token='.length));
}

function shouldAttachCsrf(method?: string): boolean {
  return !SAFE_METHODS.has((method ?? 'GET').toUpperCase());
}

function mergeCsrfHeader(headers: HeadersInit | undefined, method?: string): Headers {
  const merged = new Headers(headers);
  if (shouldAttachCsrf(method) && !merged.has('X-CSRF-Token')) {
    const token = getCsrfToken();
    if (token) merged.set('X-CSRF-Token', token);
  }
  return merged;
}

apiClient.interceptors.request.use((config) => {
  if (!shouldAttachCsrf(config.method)) return config;

  const token = getCsrfToken();
  if (!token) return config;

  const headers = config.headers;
  if (headers && typeof headers.set === 'function') {
    headers.set('X-CSRF-Token', token);
  } else {
    config.headers = AxiosHeaders.from(headers ?? {});
    config.headers.set('X-CSRF-Token', token);
  }
  return config;
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
    } else if (error.response.status === HTTP_STATUS_UNAUTHORIZED) {
      errorType = 'auth';
      emitUnauthorized(error.config?.url);
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

/** Drop-in replacement for `fetch()` that sends cookies automatically. */
export function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const normalizedInput = normalizeApiInput(input);
  const headers = mergeCsrfHeader(init?.headers, init?.method);
  const url = getRequestUrl(normalizedInput);
  return fetch(normalizedInput, {
    ...init,
    credentials: 'include',
    headers,
  }).then((response) => {
    if (response.status === HTTP_STATUS_UNAUTHORIZED) emitUnauthorized(url);
    return response;
  });
}

export async function downloadFile(url: string, filename: string): Promise<void> {
  const normalizedUrl = rewriteLegacyApiPath(url);
  const res = await fetch(normalizedUrl, { credentials: 'include' });
  if (!res.ok) {
    const isAuthError = res.status === HTTP_STATUS_UNAUTHORIZED;
    if (isAuthError) emitUnauthorized(normalizedUrl);
    throw new ApiError(
      isAuthError ? 'Authentication required.' : `Download failed: ${res.status}`,
      res.status,
      isAuthError ? 'auth' : 'server',
    );
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  a.click();
  // Revoke later so the browser has time to start the download (a synchronous
  // revoke can cancel it in some browsers).
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
}

export async function authenticatedBlobUrl(url: string, mime?: string): Promise<string> {
  const blob = await fetchBlob(url);
  return URL.createObjectURL(mime ? new Blob([blob], { type: mime }) : blob);
}

export async function fetchBlob(url: string, init?: RequestInit): Promise<Blob> {
  const normalizedUrl = rewriteLegacyApiPath(url);
  const res = await fetch(normalizedUrl, {
    ...init,
    credentials: 'include',
  });
  if (!res.ok) {
    const isAuthError = res.status === HTTP_STATUS_UNAUTHORIZED;
    if (isAuthError) emitUnauthorized(normalizedUrl);
    let msg = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      msg = typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail ?? err);
    } catch {
      /* ignore */
    }
    throw new ApiError(msg, res.status, isAuthError ? 'auth' : 'server');
  }
  return res.blob();
}

export function revokeObjectUrl(url: string | null | undefined): void {
  if (url?.startsWith('blob:')) {
    URL.revokeObjectURL(url);
  }
}
