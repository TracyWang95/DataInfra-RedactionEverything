/**
 * Playground toolbar: file name, guidance, undo/redo, popout, and reset.
 */
import { type FC } from 'react';
import { ArrowUpRight, FileText, Redo2, RotateCcw, Undo2 } from 'lucide-react';
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
      className="flex shrink-0 items-center justify-between gap-4 border-b border-border/60 bg-background/80 px-4 py-3 backdrop-blur-xl"
      data-testid="playground-toolbar"
    >
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl border border-border/70 bg-muted/60 text-foreground">
          <FileText className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold tracking-[-0.01em] text-foreground">
            {filename || t('playground.title')}
          </h3>
          <p className="truncate text-xs text-muted-foreground">{hintText}</p>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1 rounded-2xl border border-border/70 bg-card/80 p-1 shadow-[0_18px_32px_-28px_rgba(15,23,42,0.35)]">
        {isImageMode && onPopout && (
          <Button
            variant="outline"
            size="sm"
            onClick={onPopout}
            className="h-9 rounded-xl border-0 bg-transparent px-3 text-xs shadow-none"
            data-testid="playground-popout-btn"
          >
            <ArrowUpRight data-icon="inline-start" />
            {t('playground.popout') || 'Pop Out'}
          </Button>
        )}

        <Button
          variant="ghost"
          size="sm"
          onClick={onUndo}
          disabled={!canUndo}
          title={t('playground.undo') || 'Undo (Ctrl+Z)'}
          data-testid="playground-undo-btn"
          className="h-9 rounded-xl px-3 text-xs"
        >
          <Undo2 data-icon="inline-start" />
          {t('playground.undo') || 'Undo'}
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={onRedo}
          disabled={!canRedo}
          title={t('playground.redo') || 'Redo (Ctrl+Y)'}
          data-testid="playground-redo-btn"
          className="h-9 rounded-xl px-3 text-xs"
        >
          <Redo2 data-icon="inline-start" />
          {t('playground.redo') || 'Redo'}
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={onReset}
          className="h-9 rounded-xl px-3 text-xs text-muted-foreground"
          data-testid="playground-reset-btn"
        >
          <RotateCcw data-icon="inline-start" />
          {t('playground.reupload') || 'Start Over'}
        </Button>
      </div>
    </div>
  );
};
