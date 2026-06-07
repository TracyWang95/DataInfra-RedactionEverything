// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { type FC, memo } from 'react';
import { ArrowUpRight, FileText, Redo2, RotateCcw, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useT } from '@/i18n';

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

export const PlaygroundToolbar: FC<PlaygroundToolbarProps> = memo(
  ({ filename, isImageMode, canUndo, canRedo, onUndo, onRedo, onReset, onPopout, hintText }) => {
    const t = useT();

    return (
      <div
        className="flex shrink-0 items-center justify-between gap-3 border-b border-border/60 bg-background/80 px-4 py-2.5 backdrop-blur-xl"
        data-testid="playground-toolbar"
      >
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-2xl border border-border/70 bg-muted/60 text-foreground">
            <FileText className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold tracking-[-0.01em] text-foreground">
              {filename || t('playground.title')}
            </h3>
            <p className="truncate text-xs text-muted-foreground">{hintText}</p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1 rounded-2xl border border-border/70 bg-[var(--surface-control)] p-1 shadow-[var(--shadow-control)]">
          {isImageMode && onPopout && (
            <Button
              variant="outline"
              size="sm"
              onClick={onPopout}
              className="h-8 whitespace-nowrap rounded-xl border-0 bg-transparent px-3 text-xs shadow-none"
              data-testid="playground-popout-btn"
            >
              <ArrowUpRight data-icon="inline-start" />
              {t('playground.popout')}
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            onClick={onUndo}
            disabled={!canUndo}
            title={t('playground.undo')}
            data-testid="playground-undo-btn"
            className="h-8 whitespace-nowrap rounded-xl px-3 text-xs"
          >
            <Undo2 data-icon="inline-start" />
            {t('playground.undo')}
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={onRedo}
            disabled={!canRedo}
            title={t('playground.redo')}
            data-testid="playground-redo-btn"
            className="h-8 whitespace-nowrap rounded-xl px-3 text-xs"
          >
            <Redo2 data-icon="inline-start" />
            {t('playground.redo')}
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={onReset}
            className="h-8 whitespace-nowrap rounded-xl px-3 text-xs text-muted-foreground"
            data-testid="playground-reset-btn"
          >
            <RotateCcw data-icon="inline-start" />
            {t('playground.reupload')}
          </Button>
        </div>
      </div>
    );
  },
);
