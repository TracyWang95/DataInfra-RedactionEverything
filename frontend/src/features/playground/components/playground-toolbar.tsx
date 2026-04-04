/**
 * Playground toolbar: file name, hint, undo/redo, popout, and reset.
 */
import { type FC } from 'react';
import { Button } from '@/components/ui/button';
import { t } from '@/i18n';

export interface PlaygroundToolbarProps {
  filename?: string;
  isImageMode: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onReset: () => void;
  onPopout?: () => void;
  hintText: string;
}

export const PlaygroundToolbar: FC<PlaygroundToolbarProps> = ({
  filename,
  isImageMode,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onReset,
  onPopout,
  hintText,
}) => {
  return (
    <div
      className="px-3 py-2 border-b flex items-center justify-between bg-muted/40 flex-shrink-0"
      data-testid="playground-toolbar"
    >
      <div className="min-w-0 flex-1">
        <h3 className="font-semibold text-sm truncate">{filename}</h3>
        <p className="text-xs text-muted-foreground">{hintText}</p>
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        {isImageMode && onPopout && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onPopout}
            className="text-xs"
            data-testid="playground-popout-btn"
          >
            {t('playground.popout') || '新窗口标注'}
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={onUndo}
          disabled={!canUndo}
          title={t('playground.undo') || '撤销 (Ctrl+Z)'}
          data-testid="playground-undo-btn"
        >
          <span className="text-xs">↩ {t('playground.undo') || '撤销'}</span>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onRedo}
          disabled={!canRedo}
          title={t('playground.redo') || '重做 (Ctrl+Y)'}
          data-testid="playground-redo-btn"
        >
          <span className="text-xs">↪ {t('playground.redo') || '重做'}</span>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onReset}
          className="text-xs text-muted-foreground"
          data-testid="playground-reset-btn"
        >
          {t('playground.reupload') || '重新上传'}
        </Button>
      </div>
    </div>
  );
};
