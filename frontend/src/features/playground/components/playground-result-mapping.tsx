// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { Dispatch, FC, SetStateAction } from 'react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { getEntityRiskConfig } from '@/config/entityTypes';
import type { VersionHistoryEntry } from '@/types';

export interface MappingColumnProps {
  entityMap: Record<string, string>;
  origToTypeId: Map<string, string>;
  scrollToMatch: (orig: string) => void;
  content?: string;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: Dispatch<SetStateAction<boolean>>;
  className?: string;
  mobileTab: string;
}

export const MappingColumn: FC<MappingColumnProps> = ({
  entityMap,
  origToTypeId,
  scrollToMatch,
  content,
  versionHistory,
  versionHistoryOpen,
  setVersionHistoryOpen,
  className,
  mobileTab,
}) => {
  const t = useT();

  return (
    <div className={cn('flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border bg-background', mobileTab === 'mapping' ? '' : 'hidden', 'md:flex', className)}>
      <div className="flex items-center justify-between border-b border-border/60 bg-muted/30 px-4 py-3">
        <span className="text-xs font-semibold">{t('playground.mappingRecords')}</span>
        <span className="text-[11px] tabular-nums text-muted-foreground">{Object.keys(entityMap).length}</span>
      </div>
      <ScrollArea className="flex-1">
        {Object.entries(entityMap).map(([original, replacement], index) => {
          const config = getEntityRiskConfig(origToTypeId.get(original) ?? 'CUSTOM');
          const count = content ? content.split(original).length - 1 : 0;

          return (
            <button
              key={index}
              onClick={() => scrollToMatch(original)}
              className="mx-2 my-2 w-[calc(100%-1rem)] rounded-2xl border px-3 py-3 text-left shadow-sm transition-all hover:brightness-[0.99]"
              style={{ borderLeft: `3px solid ${config.color}`, backgroundColor: config.bgColor }}
              data-testid={`playground-mapping-${index}`}
            >
              <div className="flex items-center gap-1.5">
                <span className="flex-1 truncate text-[11px] font-medium" style={{ color: config.textColor }}>
                  {original}
                </span>
                {count > 0 && (
                  <span className="rounded px-1 text-[10px] tabular-nums" style={{ backgroundColor: `${config.color}22`, color: config.textColor }}>
                    {count}x
                  </span>
                )}
              </div>
              <div className="mt-1 flex items-center gap-1.5">
                <svg className="h-2.5 w-2.5 flex-shrink-0 opacity-40" style={{ color: config.color }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                </svg>
                <span className="truncate text-[10px] opacity-90" style={{ color: config.textColor }}>
                  {replacement}
                </span>
              </div>
            </button>
          );
        })}
        {Object.keys(entityMap).length === 0 && (
          <p className="py-8 text-center text-xs text-muted-foreground">
            {t('playground.noRecords')}
          </p>
        )}
      </ScrollArea>

      {versionHistory.length > 0 && (
        <div className="border-t border-border/60">
          <Button variant="ghost" className="h-auto w-full justify-between px-4 py-3" onClick={() => setVersionHistoryOpen((open) => !open)}>
            <span className="text-xs font-semibold">{t('playground.versionHistory')}</span>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] tabular-nums text-muted-foreground">{versionHistory.length}</span>
              <svg className={cn('h-3 w-3 transition-transform', versionHistoryOpen && 'rotate-180')} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </Button>

          {versionHistoryOpen && (
            <div className="space-y-1.5 px-3 pb-3">
              {versionHistory.map((version, index) => (
                <div key={index} className="rounded-xl border border-border/60 bg-muted/25 px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs font-medium">v{index + 1}</span>
                    <span className="text-[10px] tabular-nums text-muted-foreground">
                      {version.created_at ? new Date(version.created_at).toLocaleString() : ''}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-[10px] text-muted-foreground">
                      {t('playground.versionItems').replace('{count}', String(version.redacted_count))}
                    </span>
                    <span className="text-[10px] text-muted-foreground">{version.mode}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
