// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import { Button } from '@/components/ui/button';
import { usePlaygroundUIContext } from '../playground-context';
import type { EntityTypeConfig } from '../types';

interface PlaygroundTextSelectionPopoverProps {
  entityTypes: EntityTypeConfig[];
}

export const PlaygroundTextSelectionPopover: FC<PlaygroundTextSelectionPopoverProps> = ({
  entityTypes,
}) => {
  const t = useT();
  const ui = usePlaygroundUIContext();

  if (!ui.selectedText || !ui.selectionPos) return null;

  return (
    <div
      className="fixed z-50 w-[320px] animate-scale-in rounded-xl border border-border bg-popover shadow-lg"
      style={{ left: ui.selectionPos.left, top: ui.selectionPos.top }}
      onMouseDown={(event) => event.stopPropagation()}
      onMouseUp={(event) => event.stopPropagation()}
    >
      <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
        <p className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          &ldquo;{ui.selectedText.text}&rdquo;
        </p>
        <button
          type="button"
          onClick={ui.clearTextSelection}
          className="ml-2 shrink-0 rounded-md p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="Close"
        >
          <svg width="14" height="14" viewBox="0 0 15 15" fill="none">
            <path
              d="M11.782 4.032a.575.575 0 10-.813-.814L7.5 6.687 4.032 3.218a.575.575 0 00-.814.814L6.687 7.5l-3.469 3.468a.575.575 0 00.814.814L7.5 8.313l3.469 3.469a.575.575 0 00.813-.814L8.313 7.5l3.469-3.468z"
              fill="currentColor"
            />
          </svg>
        </button>
      </div>

      <div className="max-h-[240px] overflow-y-auto overscroll-contain px-2 py-2">
        <div className="grid grid-cols-3 gap-1" role="listbox" aria-label="Entity types">
          {entityTypes.map((et) => {
            const risk = getEntityRiskConfig(et.id);
            const active = ui.selectedTypeId === et.id;
            return (
              <button
                key={et.id}
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => ui.setSelectedTypeId(et.id)}
                className={cn(
                  'truncate rounded-lg px-2 py-1.5 text-left text-[11px] transition-colors',
                  active ? 'font-medium shadow-sm ring-1 ring-inset' : 'hover:bg-accent',
                )}
                style={
                  active
                    ? ({
                        backgroundColor: risk.bgColor,
                        color: risk.textColor,
                        '--tw-ring-color': risk.color,
                      } as React.CSSProperties)
                    : undefined
                }
              >
                {getEntityTypeName(et.id)}
              </button>
            );
          })}
          <button
            type="button"
            role="option"
            aria-selected={ui.selectedTypeId === 'CUSTOM'}
            onClick={() => ui.setSelectedTypeId('CUSTOM')}
            className={cn(
              'truncate rounded-lg px-2 py-1.5 text-left text-[11px] transition-colors',
              ui.selectedTypeId === 'CUSTOM'
                ? 'bg-muted font-medium shadow-sm ring-1 ring-inset ring-border'
                : 'hover:bg-accent',
            )}
          >
            {t('playground.customType')}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-1.5 border-t border-border/60 px-3 py-2">
        <Button
          size="sm"
          onClick={() => ui.addManualEntity(ui.selectedTypeId)}
          disabled={!ui.selectedTypeId}
          className="h-7 flex-1 text-xs"
        >
          {ui.selectedOverlapIds.length > 0
            ? t('playground.updateAnnotation')
            : t('playground.addAnnotation')}
        </Button>
        {ui.selectedOverlapIds.length > 0 && (
          <Button
            size="sm"
            variant="ghost"
            onClick={ui.removeSelectedEntities}
            className="h-7 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
          >
            {t('playground.remove')}
          </Button>
        )}
      </div>
    </div>
  );
};
