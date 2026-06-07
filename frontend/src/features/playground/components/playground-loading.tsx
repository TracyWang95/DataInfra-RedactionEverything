// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { type FC, memo, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { useT } from '@/i18n';
import { PLAYGROUND_LOADING_TICK_MS, PLAYGROUND_LONG_RUNNING_HINT_MS } from '@/constants/timing';
import { useInteractionLock } from '@/hooks/use-interaction-lock';

export interface PlaygroundLoadingProps {
  loadingMessage: string;
  isImageMode: boolean;
  onCancel?: () => void;
}

export const PlaygroundLoading: FC<PlaygroundLoadingProps> = memo(
  ({ loadingMessage, isImageMode, onCancel }) => {
    const t = useT();
    const panelRef = useRef<HTMLDivElement>(null);
    const [elapsedMs, setElapsedMs] = useState(0);
    const elapsedSec = Math.floor(elapsedMs / 1_000);
    const safeElapsedSec = Math.max(0, elapsedSec);
    const progressValue = Math.min(92, Math.round(12 + 80 * (1 - Math.exp(-safeElapsedSec / 90))));
    const showLongRunningHint = elapsedMs >= PLAYGROUND_LONG_RUNNING_HINT_MS;
    useInteractionLock(true, panelRef);

    useEffect(() => {
      const startedAt = Date.now();
      const timer = window.setInterval(() => {
        setElapsedMs(Math.max(0, Date.now() - startedAt));
      }, PLAYGROUND_LOADING_TICK_MS);
      return () => window.clearInterval(timer);
    }, []);

    return createPortal(
      <div
        className="fixed inset-0 z-50 flex cursor-wait items-center justify-center bg-background/70 px-4 backdrop-blur-[2px]"
        style={{ pointerEvents: 'auto' }}
        role="status"
        aria-busy="true"
        aria-label={loadingMessage || t('playground.processing')}
        data-testid="playground-loading"
      >
        <div
          ref={panelRef}
          tabIndex={-1}
          className="w-full max-w-md animate-scale-in cursor-default rounded-[20px] border border-border/70 bg-[var(--surface-overlay)] px-4 py-3.5 text-left shadow-[var(--shadow-floating)] outline-none"
        >
          <div className="mb-3 flex items-start gap-3">
            <div className="mt-0.5 h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-foreground">
                {loadingMessage || t('playground.processing')}
              </p>
              <p
                className="mt-1 text-xs tabular-nums text-muted-foreground"
                data-testid="playground-loading-timer"
              >
                {t('playground.waited')} {safeElapsedSec} {t('playground.seconds')}...
              </p>
            </div>
          </div>
          <Progress
            value={progressValue}
            className="mb-3"
            aria-label={t('playground.loadingProgress')}
            data-testid="playground-loading-progress"
          />

          {isImageMode ? (
            <>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {t('playground.imageHint')}{' '}
                <strong className="font-medium text-foreground">
                  {t('playground.cpuWarning')}
                </strong>{' '}
                {t('playground.waitHint')}
              </p>
              {showLongRunningHint && (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  {t('playground.longRunningHint')}
                </p>
              )}
            </>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">{t('playground.processingHint')}</p>
              {showLongRunningHint && (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  {t('playground.longRunningHint')}
                </p>
              )}
            </>
          )}

          {onCancel && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-4 w-full whitespace-nowrap"
              onClick={onCancel}
              data-testid="playground-cancel-processing"
            >
              <XCircle aria-hidden="true" />
              {t('common.cancel')}
            </Button>
          )}
        </div>
      </div>,
      document.body,
    );
  },
);
