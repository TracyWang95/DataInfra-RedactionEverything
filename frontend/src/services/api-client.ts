/**
 * Unified API client for DataInfra-RedactionEverything
 *
 * Consolidates the three different patterns previously used:
 * - api.ts (Axios with interceptors)
 * - jobsApi.ts (raw fetch with manual authHeaders)
 * - presetsApi.ts (raw fetch without auth)
 *
 * All API calls should go through this module.
 */
import axios, { type AxiosRequestConfig } from 'axios';

// ─── Auth helpers ─────────────────────────────────────────────

const AUTH_TOKEN_KEY = 'auth_token';

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

export function getCsrfToken(): string | null {
  return getCookie('csrf_token');
}

export function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

// ─── Axios instance ───────────────────────────────────────────

export const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 60_000,
});

// Request: attach JWT + CSRF
apiClient.interceptors.request.use((config) => {
  const token = getAuthToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  const method = (config.method || 'get').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
    const csrf = getCsrfToken();
    if (csrf) {
      config.headers['X-CSRF-Token'] = csrf;
    }
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

// ─── Authenticated fetch helpers (for blob downloads) ─────────

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = getAuthToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const csrf = getCsrfToken();
  if (csrf) headers['X-CSRF-Token'] = csrf;
  return headers;
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
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) throw new ApiError(`Failed to load file: ${res.status}`, res.status);
  const buf = await res.arrayBuffer();
  const blob = mime ? new Blob([buf], { type: mime }) : new Blob([buf]);
  return URL.createObjectURL(blob);
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
