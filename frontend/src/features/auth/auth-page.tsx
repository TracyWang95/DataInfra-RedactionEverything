// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { LockKeyhole, ShieldCheck } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useT } from '@/i18n';
import { resolveAuthMode, resolveAuthNext, type AuthMode } from './auth-routing';
import { useAuth } from './auth-context';

export function AuthPage() {
  const t = useT();
  const location = useLocation();
  const navigate = useNavigate();
  const { status, login, setup, register } = useAuth();
  const [mode, setMode] = useState<AuthMode>(() => resolveAuthMode(location.search));
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsSetup = status?.password_set === false;
  const isRegister = !needsSetup && mode === 'register';
  const next = useMemo(() => resolveAuthNext(location.search), [location.search]);

  function switchMode(nextMode: AuthMode) {
    setError(null);
    setConfirmPassword('');
    setMode(nextMode);
    const params = new URLSearchParams(location.search);
    if (nextMode === 'register') {
      params.set('mode', 'register');
    } else {
      params.delete('mode');
    }
    const search = params.toString();
    navigate(`${location.pathname}${search ? `?${search}` : ''}`, { replace: true });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if ((needsSetup || isRegister) && password !== confirmPassword) {
      setError(t('auth.error.passwordMismatch'));
      return;
    }

    setSubmitting(true);
    try {
      if (needsSetup) {
        await setup(username, password);
      } else if (isRegister) {
        await register(username, password);
      } else {
        await login(username, password);
      }
      navigate(isRegister ? '/' : next, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('auth.error.generic'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_top,_rgba(16,185,129,0.18),_transparent_42%),linear-gradient(160deg,#f4f7f4_0%,#eef2ef_45%,#dde6df_100%)] px-6 py-10">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(135deg,rgba(15,23,42,0.04)_0%,transparent_38%,rgba(15,23,42,0.03)_100%)]" />
      <Card className="relative z-10 w-full max-w-md border-border/70 bg-background/92">
        <CardHeader className="space-y-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-foreground text-background shadow-[var(--shadow-md)]">
            {needsSetup ? <ShieldCheck className="h-5 w-5" /> : <LockKeyhole className="h-5 w-5" />}
          </div>
          <div className="space-y-2">
            <CardTitle className="text-2xl tracking-[-0.04em]">
              {needsSetup
                ? t('auth.setup.title')
                : isRegister
                  ? t('auth.register.title')
                  : t('auth.login.title')}
            </CardTitle>
            <CardDescription>
              {needsSetup
                ? t('auth.setup.description')
                : isRegister
                  ? t('auth.register.description')
                  : t('auth.login.description')}
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent>
          <form className="space-y-5" onSubmit={(event) => void handleSubmit(event)}>
            {error && (
              <Alert variant="destructive">
                <AlertTitle>{t('auth.error.title')}</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-2">
              <Label htmlFor="auth-username">{t('auth.username')}</Label>
              <Input
                id="auth-username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder={t('auth.username.placeholder')}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="auth-password">{t('auth.password')}</Label>
              <Input
                id="auth-password"
                type="password"
                autoComplete={needsSetup || isRegister ? 'new-password' : 'current-password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={t('auth.password.placeholder')}
                required
              />
            </div>

            {(needsSetup || isRegister) && (
              <div className="space-y-2">
                <Label htmlFor="auth-confirm-password">{t('auth.confirmPassword')}</Label>
                <Input
                  id="auth-confirm-password"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  placeholder={t('auth.confirmPassword.placeholder')}
                  required
                />
              </div>
            )}

            <Button className="w-full" type="submit" disabled={submitting}>
              {submitting
                ? t('auth.submitting')
                : needsSetup
                  ? t('auth.setup.submit')
                  : isRegister
                    ? t('auth.register.submit')
                    : t('auth.login.submit')}
            </Button>

            {needsSetup ? (
              <p className="text-sm leading-6 text-muted-foreground">{t('auth.setup.hint')}</p>
            ) : (
              <div className="space-y-3 text-sm leading-6 text-muted-foreground">
                <p>{isRegister ? t('auth.register.hint') : t('auth.login.hint')}</p>
                <button
                  type="button"
                  className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
                  onClick={() => switchMode(isRegister ? 'login' : 'register')}
                >
                  {isRegister ? t('auth.register.switchToLogin') : t('auth.login.switchToRegister')}
                </button>
              </div>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export default AuthPage;
