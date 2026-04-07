// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { t } from '@/i18n';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info);
  }

  private handleReset = () => {
    this.props.onReset?.();
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <div
          role="alert"
          aria-live="assertive"
          className="flex min-h-[320px] flex-col items-center justify-center gap-4 rounded-2xl border border-border/70 bg-[var(--surface-control)] px-6 py-12 text-center shadow-[var(--shadow-md)]"
        >
          <div className="flex size-12 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div className="space-y-2">
            <p className="text-base font-semibold text-foreground">{t('errorBoundary.title')}</p>
            <p className="max-w-md break-all text-xs text-muted-foreground">
              {this.state.error?.message}
            </p>
          </div>
          <Button onClick={this.handleReset} variant="outline" className="rounded-full px-4">
            {t('common.retry')}
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}
