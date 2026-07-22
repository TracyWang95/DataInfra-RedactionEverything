// Copyright 2026 DataInfra-RedactionEverything Contributors

/**
 * Extracted from review-text-content.tsx — the text selection annotation popover.
 */

import { type FC } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { useT } from '@/i18n';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import type { TextEntityType } from '../types';

export interface ReviewAnnotationPopoverProps {
  selectedText: string;
  selectionPos: { left: number; top: number };
  selectedTypeId: string | null;
  textTypes: TextEntityType[];
  onTypeSelect: (typeId: string) => void;
  onAdd: () => void;
  onClose: () => void;
}

export const ReviewAnnotationPopover: FC<ReviewAnnotationPopoverProps> = ({
  selectedText,
  selectionPos,
  selectedTypeId,
  textTypes,
  onTypeSelect,
  onAdd,
  onClose,
}) => {
  const t = useT();

  return (
    <div
      className="absolute z-50 w-[280px] animate-in fade-in zoom-in-95 rounded-xl border border-border bg-popover shadow-lg"
      style={{ left: selectionPos.left, top: selectionPos.top }}
      onMouseDown={(e) => e.stopPropagation()}
      onMouseUp={(e) => e.stopPropagation()}
    >
      {/* Header: selected text + close */}
      <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
        <p className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          &ldquo;{selectedText}&rdquo;
        </p>
        <button
          type="button"
          onClick={onClose}
          className="ml-2 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="Close"
        >
          <svg width="16" height="16" viewBox="0 0 15 15" fill="none">
            <path
              d="M11.782 4.032a.575.575 0 10-.813-.814L7.5 6.687 4.032 3.218a.575.575 0 00-.814.814L6.687 7.5l-3.469 3.468a.575.575 0 00.814.814L7.5 8.313l3.469 3.469a.575.575 0 00.813-.814L8.313 7.5l3.469-3.468z"
              fill="currentColor"
            />
          </svg>
        </button>
      </div>

      {/* Type pills grid — larger targets for remote desktop */}
      <div className="max-h-[220px] overflow-y-auto overscroll-contain px-2 py-2">
        <div className="grid grid-cols-2 gap-1.5" role="listbox" aria-label="Entity types">
          {textTypes.map((et) => {
            const risk = getEntityRiskConfig(et.id);
            const active = selectedTypeId === et.id;
            return (
              <button
                key={et.id}
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => onTypeSelect(et.id)}
                className={cn(
                  'min-h-9 truncate rounded-lg px-2.5 py-2 text-left text-xs transition-colors',
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
                {et.name ?? getEntityTypeName(et.id)}
              </button>
            );
          })}
          <button
            type="button"
            role="option"
            aria-selected={selectedTypeId === 'CUSTOM'}
            onClick={() => onTypeSelect('CUSTOM')}
            className={cn(
              'min-h-9 truncate rounded-lg px-2.5 py-2 text-left text-xs transition-colors',
              selectedTypeId === 'CUSTOM'
                ? 'bg-muted font-medium shadow-sm ring-1 ring-inset ring-border'
                : 'hover:bg-accent',
            )}
          >
            {t('playground.customType')}
          </button>
        </div>
      </div>

      {/* Add button */}
      <div className="flex items-center gap-1.5 border-t border-border/60 px-3 py-2.5">
        <Button size="sm" onClick={onAdd} disabled={!selectedTypeId} className="h-9 flex-1 text-xs">
          {t('playground.addAnnotation')}
        </Button>
      </div>
    </div>
  );
};
