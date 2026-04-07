// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import type { FileInfo } from '../types';

export interface PlaygroundResultActionBarProps {
  fileInfo: FileInfo | null;
  redactedCount: number;
  onBackToEdit: () => void;
  onReset: () => void;
  onDownload: () => void;
}

export const PlaygroundResultActionBar: FC<PlaygroundResultActionBarProps> = ({
  fileInfo,
  redactedCount,
  onBackToEdit,
  onReset,
  onDownload,
}) => {
  const t = useT();

  return (
    <div className="mx-3 mb-3 mt-3 flex-shrink-0 sm:mx-4 sm:mt-4">
      <Card className="border-0 bg-foreground text-background shadow-[var(--shadow-floating)]">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 px-6 py-5">
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-background/10 backdrop-blur-sm">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-semibold">{t('playground.redactComplete')}</p>
              <p className="text-xs text-background/70">
                {redactedCount} {t('playground.itemsProcessed')}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onBackToEdit} data-testid="playground-back-edit">
              {t('playground.backToEdit')}
            </Button>
            <Button variant="secondary" size="sm" onClick={onReset}>
              {t('playground.newFile')}
            </Button>
            {fileInfo && (
              <Button
                size="sm"
                variant="outline"
                onClick={onDownload}
                data-testid="playground-download"
                className="border-background/20 bg-background/10 text-background hover:bg-background/15"
              >
                {t('playground.downloadFile')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export const RedactionReportSection: FC<{
  report: Record<string, unknown>;
  open: boolean;
  onToggle: () => void;
}> = ({ report, open, onToggle }) => {
  const t = useT();
  const normalized = report as Record<string, number | string | Record<string, number>>;

  return (
    <div className="mx-3 mb-3 flex-shrink-0 sm:mx-4">
      <Button variant="outline" className="h-auto w-full justify-between rounded-2xl px-5 py-3" onClick={onToggle}>
        <span className="text-xs font-semibold">{t('playground.qualityReport')}</span>
        <svg className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </Button>
      {open && (
        <Card className="-mt-1 rounded-t-none px-5 pb-4 pt-3">
          <CardContent className="flex flex-wrap gap-6 p-0 text-xs">
            <div className="flex flex-col">
              <span className="text-[10px] uppercase text-muted-foreground">
                {t('playground.totalEntities')}
              </span>
              <span className="text-lg font-bold tabular-nums">{String(normalized.total_entities ?? '')}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] uppercase text-muted-foreground">
                {t('playground.redactedEntities')}
              </span>
              <span className="text-lg font-bold tabular-nums">{String(normalized.redacted_entities ?? '')}</span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
