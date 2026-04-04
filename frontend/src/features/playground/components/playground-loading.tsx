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
  // Indeterminate progress: oscillate between 10-90 based on elapsed time
  const progressValue = Math.min(90, 10 + (elapsedSec % 60) * 1.3);

  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center"
      role="alertdialog"
      aria-busy="true"
      aria-label={loadingMessage || t('playground.processing') || '处理中'}
      data-testid="playground-loading"
    >
      <div className="bg-background rounded-2xl shadow-2xl px-8 py-6 text-center max-w-sm">
        <div className="w-12 h-12 border-[3px] border-primary border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-base font-medium mb-2">
          {loadingMessage || t('playground.processing') || '处理中...'}
        </p>
        <Progress value={progressValue} className="mb-3" />
        {isImageMode ? (
          <>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {t('playground.imageHint') || '仅勾选「文字 OCR+HaS」时才会跑 Paddle；只勾选「HaS Image」则不走 OCR。'}
              {' '}
              <strong className="font-medium text-foreground">
                {t('playground.cpuWarning') || 'CPU 跑 Paddle 时常需 30-90 秒甚至更久'}
              </strong>
              {t('playground.waitHint') || '，等待较久为正常现象，请勿刷新。'}
            </p>
            {elapsedSec > 0 && (
              <p className="text-xs text-muted-foreground mt-2 tabular-nums" data-testid="playground-loading-timer">
                {t('playground.waited') || '已等待'} {elapsedSec} {t('playground.seconds') || '秒'}...
              </p>
            )}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            {t('playground.processingHint') || '处理中，请稍候'}
          </p>
        )}
      </div>
    </div>
  );
};
