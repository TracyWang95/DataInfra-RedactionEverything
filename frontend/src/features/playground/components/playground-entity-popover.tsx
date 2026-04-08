// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react';
import { useT } from '@/i18n';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import { Button } from '@/components/ui/button';
import { usePlaygroundUIContext } from '../playground-context';

export const PlaygroundEntityPopover: FC = () => {
  const t = useT();
  const ui = usePlaygroundUIContext();

  if (!ui.clickedEntity || !ui.entityPopupPos) return null;

  const risk = getEntityRiskConfig(ui.clickedEntity.type);

  return (
    <div
      className="fixed z-50 w-[240px] animate-scale-in rounded-xl border border-border bg-popover p-3 shadow-lg"
      style={{ left: ui.entityPopupPos.left, top: ui.entityPopupPos.top }}
      onMouseDown={(event) => event.stopPropagation()}
      onMouseUp={(event) => event.stopPropagation()}
      role="dialog"
      aria-label="Entity details"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
            style={{ backgroundColor: risk.bgColor, color: risk.textColor }}
          >
            {getEntityTypeName(ui.clickedEntity.type)}
          </span>
          <span className="truncate text-xs text-muted-foreground">{ui.clickedEntity.text}</span>
        </div>
        <button
          type="button"
          onClick={() => { ui.setClickedEntity(null); ui.setEntityPopupPos(null); }}
          className="shrink-0 rounded-md p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="Close"
        >
          <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><path d="M11.782 4.032a.575.575 0 10-.813-.814L7.5 6.687 4.032 3.218a.575.575 0 00-.814.814L6.687 7.5l-3.469 3.468a.575.575 0 00.814.814L7.5 8.313l3.469 3.469a.575.575 0 00.813-.814L8.313 7.5l3.469-3.468z" fill="currentColor"/></svg>
        </button>
      </div>
      <Button size="sm" variant="ghost" onClick={ui.confirmRemoveEntity} className="h-7 w-full text-xs text-destructive hover:bg-destructive/10 hover:text-destructive">
        {t('playground.removeAnnotation')}
      </Button>
    </div>
  );
};
