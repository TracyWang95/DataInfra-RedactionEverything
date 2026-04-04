/**
 * Playground loading overlay with progress and step labels.
 */
import { type FC } from 'react';
import { Progress } from '@/components/ui/progress';
import { t } from '@/i18n';

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
  const progressValue = Math.min(90, 10 + (elapsedSec % 60) * 1.3);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      role="alertdialog"
      aria-busy="true"
      aria-label={loadingMessage || t('playground.processing') || 'Processing'}
      data-testid="playground-loading"
    >
      <div className="max-w-sm animate-scale-in rounded-[28px] border border-border/50 bg-background px-8 py-8 text-center shadow-[0_34px_80px_-40px_rgba(15,23,42,0.5)]">
        <div className="mx-auto mb-5 h-12 w-12 animate-spin rounded-full border-[3px] border-primary/30 border-t-primary" />
        <p className="mb-2 text-base font-medium text-foreground">
          {loadingMessage || t('playground.processing') || 'Processing...'}
        </p>
        <Progress value={progressValue} className="mb-3" />

        {isImageMode ? (
          <>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {t('playground.imageHint') || 'OCR and image analysis can take longer on larger files.'}{' '}
              <strong className="font-medium text-foreground">
                {t('playground.cpuWarning') || 'CPU-only runs may take 30 to 90 seconds.'}
              </strong>{' '}
              {t('playground.waitHint') || 'That is expected. Keep this window open while processing completes.'}
            </p>
            {elapsedSec > 0 && (
              <p className="mt-2 text-xs tabular-nums text-muted-foreground" data-testid="playground-loading-timer">
                {t('playground.waited') || 'Waiting'} {elapsedSec} {t('playground.seconds') || 'seconds'}...
              </p>
            )}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            {t('playground.processingHint') || 'Processing your file. This usually finishes quickly.'}
          </p>
        )}
      </div>
    </div>
  );
};
