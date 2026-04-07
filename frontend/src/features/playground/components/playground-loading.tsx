// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { type FC } from 'react';
import { createPortal } from 'react-dom';
import { Progress } from '@/components/ui/progress';
import { useT } from '@/i18n';

export interface PlaygroundLoadingProps {
  loadingMessage: string;
  isImageMode: boolean;
  elapsedSec: number;
}

export const PlaygroundLoading: FC<PlaygroundLoadingProps> = ({
  loadingMessage,
  isImageMode,
  elapsedSec,
}) => {
  const t = useT();
  const progressValue = Math.min(90, 10 + (elapsedSec % 60) * 1.3);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay-backdrop)] backdrop-blur-sm"
      role="alertdialog"
      aria-busy="true"
      aria-label={loadingMessage || t('playground.processing')}
      data-testid="playground-loading"
    >
      <div className="max-w-sm animate-scale-in rounded-[28px] border border-border/50 bg-[var(--surface-overlay)] px-8 py-8 text-center shadow-[var(--shadow-floating)]">
        <div className="mx-auto mb-5 h-12 w-12 animate-spin rounded-full border-[3px] border-primary/30 border-t-primary" />
        <p className="mb-2 text-base font-medium text-foreground">
          {loadingMessage || t('playground.processing')}
        </p>
        <Progress value={progressValue} className="mb-3" />

        {isImageMode ? (
          <>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {t('playground.imageHint')}{' '}
              <strong className="font-medium text-foreground">
                {t('playground.cpuWarning')}
              </strong>{' '}
              {t('playground.waitHint')}
            </p>
            {elapsedSec > 0 && (
              <p className="mt-2 text-xs tabular-nums text-muted-foreground" data-testid="playground-loading-timer">
                {t('playground.waited')} {elapsedSec} {t('playground.seconds')}...
              </p>
            )}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            {t('playground.processingHint')}
          </p>
        )}
      </div>
    </div>,
    document.body,
  );
};
