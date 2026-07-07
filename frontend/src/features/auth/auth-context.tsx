// Copyright 2026 DataInfra-RedactionEverything Contributors

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { AUTH_UNAUTHORIZED_EVENT, authFetch } from '@/services/api-client';
import { STORAGE_KEYS } from '@/constants/storage-keys';
import { localizeErrorMessage } from '@/utils/localizeError';

export interface AuthStatus {
  auth_enabled: boolean;
  password_set: boolean | null;
  authenticated: boolean;
  username?: string | null;
  role?: string | null;
  is_super_admin?: boolean;
  can_bulk_confirm?: boolean;
  multi_user?: boolean;
}

interface AuthContextValue {
  status: AuthStatus | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<AuthStatus | null>;
  login: (username: string, password: string) => Promise<void>;
  setup: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function parseJson<T>(res: Response): Promise<T | null> {
  try {
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function ensureOk<T>(res: Response): Promise<T> {
  const body = await parseJson<T & { detail?: string; message?: string }>(res);
  if (!res.ok) {
    const message =
      (body && typeof body.detail === 'string' && body.detail) ||
      (body && typeof body.message === 'string' && body.message) ||
      `HTTP ${res.status}`;
    throw new Error(message);
  }
  if (body == null) throw new Error(`HTTP ${res.status}`);
  return body as T;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const statusRef = useRef<AuthStatus | null>(null);
  const refreshPromiseRef = useRef<Promise<AuthStatus | null> | null>(null);

  useEffect(() => {
    statusRef.current = status;
    try {
      if (status?.authenticated && status.username) {
        localStorage.setItem(STORAGE_KEYS.CURRENT_USER, status.username.toLowerCase());
      } else {
        localStorage.removeItem(STORAGE_KEYS.CURRENT_USER);
      }
    } catch {
      // localStorage may be unavailable in restricted browsers.
    }
  }, [status]);

  const runRefresh = useCallback((background = false): Promise<AuthStatus | null> => {
    if (refreshPromiseRef.current) {
      return refreshPromiseRef.current;
    }

    const shouldShowLoading = !background || statusRef.current == null;
    if (shouldShowLoading) {
      setLoading(true);
    }

    let request: Promise<AuthStatus | null> | null = null;
    request = (async (): Promise<AuthStatus | null> => {
      try {
        const res = await authFetch('/api/v1/auth/status');
        const next = await ensureOk<AuthStatus>(res);
        statusRef.current = next;
        setStatus(next);
        setError(null);
        return next;
      } catch (err) {
        if (!background || statusRef.current == null) {
          statusRef.current = null;
          setStatus(null);
        }
        setError(err instanceof Error ? err.message : 'Unable to load authentication status.');
        return null;
      } finally {
        if (request && refreshPromiseRef.current === request) {
          refreshPromiseRef.current = null;
        }
        if (shouldShowLoading) {
          setLoading(false);
        }
      }
    })();

    refreshPromiseRef.current = request;
    return request;
  }, []);

  const refresh = useCallback(
    async (): Promise<AuthStatus | null> => runRefresh(false),
    [runRefresh],
  );

  useEffect(() => {
    void runRefresh(false);
  }, [runRefresh]);

  const markUnauthenticated = useCallback((clearError = true) => {
    if (clearError) {
      setError(null);
    }
    setStatus((current) => {
      const next = current
        ? { ...current, authenticated: false }
        : { auth_enabled: true, password_set: true, authenticated: false };
      statusRef.current = next;
      return next;
    });
  }, []);

  useEffect(() => {
    const handleUnauthorized = () => {
      markUnauthenticated(true);
      void runRefresh(true);
    };

    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
  }, [markUnauthenticated, runRefresh]);

  const confirmAuthenticated = useCallback(async () => {
    const next = await runRefresh(true);
    if (!next?.authenticated) {
      throw new Error('Authentication session was not established.');
    }
  }, [runRefresh]);

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await authFetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      await ensureOk<TokenResponse>(res);
      setError(null);
      await confirmAuthenticated();
    },
    [confirmAuthenticated],
  );

  const setup = useCallback(
    async (username: string, password: string) => {
      const res = await authFetch('/api/v1/auth/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      await ensureOk<TokenResponse>(res);
      setError(null);
      await confirmAuthenticated();
    },
    [confirmAuthenticated],
  );

  const register = useCallback(
    async (username: string, password: string) => {
      const res = await authFetch('/api/v1/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      await ensureOk<TokenResponse>(res);
      setError(null);
      await confirmAuthenticated();
    },
    [confirmAuthenticated],
  );

  const logout = useCallback(async () => {
    let shouldRefresh = false;
    try {
      const res = await authFetch('/api/v1/auth/logout', { method: 'POST' });
      await ensureOk<{ message: string }>(res);
      shouldRefresh = true;
      setError(null);
    } catch (err) {
      setError(localizeErrorMessage(err, 'auth.error.logoutFailed'));
    } finally {
      markUnauthenticated(shouldRefresh);
      if (shouldRefresh) {
        void runRefresh(true);
      }
    }
  }, [markUnauthenticated, runRefresh]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      loading,
      error,
      refresh,
      login,
      setup,
      register,
      logout,
    }),
    [error, login, loading, logout, refresh, register, setup, status],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
