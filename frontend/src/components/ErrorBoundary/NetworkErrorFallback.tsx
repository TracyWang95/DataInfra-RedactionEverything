import React from 'react';
import { AlertTriangle, ShieldAlert, WifiOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { t } from '@/i18n';

export interface NetworkErrorFallbackProps {
  error: Error;
  onRetry?: () => void;
}

export function isNetworkError(error: Error): boolean {
  const message = error.message.toLowerCase();
  return (
    (error.name === 'TypeError' && message.includes('fetch')) ||
    message.includes('network') ||
    message.includes('failed to fetch') ||
    message.includes('networkerror') ||
    message.includes('net::')
  );
}

export function isAuthError(error: Error): boolean {
  const message = error.message.toLowerCase();
  return (
    message.includes('401') ||
    message.includes('403') ||
    message.includes('unauthorized') ||
    message.includes('unauthenticated') ||
    (message.includes('token') && message.includes('expired'))
  );
}

export const NetworkErrorFallback: React.FC<NetworkErrorFallbackProps> = ({
  error,
  onRetry,
}) => {
  if (isAuthError(error)) {
    return (
      <FallbackShell
        icon={<ShieldAlert className="h-5 w-5" />}
        title={t('networkFallback.authTitle')}
        description={t('networkFallback.authDesc')}
        action={(
          <Button
            onClick={() => {
              window.location.href = '/login';
            }}
            variant="outline"
            className="rounded-full px-4"
          >
            {t('networkFallback.login')}
          </Button>
        )}
      />
    );
  }

  if (isNetworkError(error)) {
    return (
      <FallbackShell
        icon={<WifiOff className="h-5 w-5" />}
        title={t('networkFallback.networkTitle')}
        description={t('networkFallback.networkDesc')}
        action={onRetry ? (
          <Button onClick={onRetry} variant="outline" className="rounded-full px-4">
            {t('common.retry')}
          </Button>
        ) : null}
      />
    );
  }

  return (
    <FallbackShell
      icon={<AlertTriangle className="h-5 w-5" />}
      title={t('errorBoundary.title')}
      description={error.message}
      action={onRetry ? (
        <Button onClick={onRetry} variant="outline" className="rounded-full px-4">
          {t('common.retry')}
        </Button>
      ) : null}
    />
  );
};

function FallbackShell({
  icon,
  title,
  description,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex min-h-[320px] flex-col items-center justify-center gap-4 rounded-2xl border border-border/70 bg-card px-6 py-12 text-center shadow-[0_24px_60px_-36px_rgba(15,23,42,0.28)]"
    >
      <div className="flex size-12 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
        {icon}
      </div>
      <div className="space-y-2">
        <p className="text-base font-semibold text-foreground">{title}</p>
        <p className="max-w-md break-all text-xs text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}
