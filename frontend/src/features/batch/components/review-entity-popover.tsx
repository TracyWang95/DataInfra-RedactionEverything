// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * Extracted from review-text-content.tsx — the clicked entity popover (remove annotation).
 */

import { type FC } from 'react';
import { Button } from '@/components/ui/button';
import { useT } from '@/i18n';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import type { ReviewEntity } from '../types';

export interface ReviewEntityPopoverProps {
  entity: ReviewEntity;
  position: { left: number; top: number };
  onRemove: () => void;
  onClose: () => void;
}

export const ReviewEntityPopover: FC<ReviewEntityPopoverProps> = ({
  entity,
  position,
  onRemove,
  onClose,
}) => {
  const t = useT();
  const risk = getEntityRiskConfig(entity.type);

  return (
    <div
      className="absolute z-50 w-[220px] animate-in fade-in zoom-in-95 rounded-xl border border-border bg-popover p-3 shadow-lg"
      style={{ left: position.left, top: position.top }}
      onMouseDown={(e) => e.stopPropagation()}
      role="dialog"
      aria-label="Entity details"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
            style={{ backgroundColor: risk.bgColor, color: risk.textColor }}
          >
            {getEntityTypeName(entity.type)}
          </span>
          <span className="truncate text-xs text-muted-foreground">{entity.text}</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-md p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
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
      <Button
        size="sm"
        variant="ghost"
        onClick={onRemove}
        className="h-7 w-full text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
      >
        {t('playground.removeAnnotation')}
      </Button>
    </div>
  );
};
