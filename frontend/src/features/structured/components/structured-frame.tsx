// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { cn } from '@/lib/utils';
import type { NoticeState } from '../hooks/use-notice';

export function StructuredFrame({
  eyebrow,
  title,
  description,
  actions,
  notices,
  fit,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
  notices?: NoticeState;
  fit?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="saas-page flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,2048px)] !px-3 !py-3 sm:!px-4 2xl:!px-5">
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
          <header className="flex flex-none flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <span className="saas-kicker">{eyebrow}</span>
              <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
              <p className="max-w-4xl text-sm leading-6 text-muted-foreground">{description}</p>
            </div>
            {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
          </header>
          <NoticeStack notices={notices} />
          <main className={cn('min-h-0 flex-1 pr-1', fit ? 'overflow-hidden' : 'overflow-auto')}>
            <div className={cn('grid gap-3', fit ? 'h-full min-h-0' : 'pb-3')}>{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
}

function NoticeStack({ notices }: { notices?: NoticeState }) {
  if (!notices) return null;
  return (
    <>
      {notices.error ? (
        <Alert variant="destructive" className="flex-none">
          <AlertDescription>{notices.error}</AlertDescription>
        </Alert>
      ) : null}
      {notices.message ? (
        <Alert className="flex-none">
          <AlertDescription>{notices.message}</AlertDescription>
        </Alert>
      ) : null}
    </>
  );
}
