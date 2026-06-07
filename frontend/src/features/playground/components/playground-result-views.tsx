// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { Dispatch, FC, ReactNode, SetStateAction } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import { PaginationRail } from '@/components/PaginationRail';
import type { VersionHistoryEntry } from '@/types';
import type { BoundingBox, FileInfo, VisionTypeConfig } from '../types';
import { MappingColumn } from './playground-result-mapping';

export const TextResultView: FC<{
  renderOriginal: () => ReactNode[];
  renderRedacted: () => ReactNode[];
  content: string;
  entityMap: Record<string, string>;
  origToTypeId: Map<string, string>;
  matchCounts: Map<string, number>;
  scrollToMatch: (orig: string) => void;
  mobileTab: string;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: Dispatch<SetStateAction<boolean>>;
  currentPage?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
}> = ({
  renderOriginal,
  renderRedacted,
  content,
  entityMap,
  origToTypeId,
  matchCounts,
  scrollToMatch,
  mobileTab,
  versionHistory,
  versionHistoryOpen,
  setVersionHistoryOpen,
  currentPage = 1,
  totalPages = 1,
  onPageChange,
}) => {
  const t = useT();

  const paginationRail =
    totalPages > 1 && onPageChange ? (
      <div className="mx-3 mb-2 flex-shrink-0 sm:mx-4">
        <PaginationRail
          page={currentPage}
          pageSize={1}
          totalItems={totalPages}
          totalPages={totalPages}
          compact
          onPageChange={onPageChange}
        />
      </div>
    ) : null;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {paginationRail}
      <div className="flex min-h-0 min-w-0 flex-1 gap-3 overflow-hidden">
        <div
          className={cn(
            'flex min-w-0 flex-1 flex-col overflow-hidden rounded-[20px] border bg-background shadow-[var(--shadow-sm)]',
            mobileTab === 'original' ? '' : 'hidden',
            'md:flex',
          )}
        >
          <div className="flex h-10 flex-shrink-0 items-center border-b border-border/60 bg-muted/30 px-4">
            <span className="truncate text-xs font-semibold">{t('playground.originalDoc')}</span>
          </div>
          <ScrollArea className="flex-1 p-4">
            <div className="font-[system-ui] text-sm leading-relaxed whitespace-pre-wrap">
              {renderOriginal()}
            </div>
          </ScrollArea>
        </div>

        <div
          className={cn(
            'flex min-w-0 flex-1 flex-col overflow-hidden rounded-[20px] border bg-background shadow-[var(--shadow-sm)]',
            mobileTab === 'redacted' ? '' : 'hidden',
            'md:flex',
          )}
        >
          <div className="flex h-10 flex-shrink-0 items-center border-b border-border/60 bg-muted/30 px-4">
            <span className="truncate text-xs font-semibold">{t('playground.redactedResult')}</span>
          </div>
          <ScrollArea className="flex-1 p-4">
            <div className="font-[system-ui] text-sm leading-relaxed whitespace-pre-wrap">
              {renderRedacted()}
            </div>
          </ScrollArea>
        </div>

        <MappingColumn
          entityMap={entityMap}
          origToTypeId={origToTypeId}
          matchCounts={matchCounts}
          scrollToMatch={scrollToMatch}
          content={content}
          className="w-full shadow-[var(--shadow-sm)] md:w-64 md:flex-shrink-0 xl:w-72"
          mobileTab={mobileTab}
          versionHistory={versionHistory}
          versionHistoryOpen={versionHistoryOpen}
          setVersionHistoryOpen={setVersionHistoryOpen}
        />
      </div>
    </div>
  );
};

export const ImageResultView: FC<{
  fileInfo: FileInfo | null;
  imageUrl: string;
  redactedImageUrl?: string;
  redactedImageError?: string | null;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  visibleBoxes: BoundingBox[];
  visionTypes: VisionTypeConfig[];
  getVisionTypeConfig: (typeId: string) => { name: string; color: string };
  entityMap: Record<string, string>;
  origToTypeId: Map<string, string>;
  matchCounts: Map<string, number>;
  scrollToMatch: (orig: string) => void;
  mobileTab: string;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: Dispatch<SetStateAction<boolean>>;
}> = ({
  fileInfo,
  imageUrl,
  redactedImageUrl,
  redactedImageError,
  currentPage,
  totalPages,
  onPageChange,
  visibleBoxes,
  visionTypes,
  getVisionTypeConfig,
  entityMap,
  origToTypeId,
  matchCounts,
  scrollToMatch,
  mobileTab,
  versionHistory,
  versionHistoryOpen,
  setVersionHistoryOpen,
}) => {
  const t = useT();

  return (
    <div className="flex min-h-0 min-w-0 flex-1 gap-3 overflow-hidden">
      <div
        className={cn(
          'flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[20px] border bg-background shadow-[var(--shadow-sm)]',
          mobileTab === 'original' ? '' : 'hidden',
          'md:flex',
        )}
      >
        <div className="flex h-10 flex-shrink-0 items-center border-b border-border/60 bg-muted/30 px-4">
          <span className="truncate text-xs font-semibold">{t('playground.originalImage')}</span>
        </div>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {fileInfo && (
            <ImageBBoxEditor
              readOnly
              imageSrc={imageUrl}
              boxes={visibleBoxes}
              onBoxesChange={() => {}}
              getTypeConfig={getVisionTypeConfig}
              availableTypes={visionTypes.map((visionType) => ({
                id: visionType.id,
                name: visionType.name,
                color: '#6366F1',
              }))}
              defaultType={visionTypes[0]?.id || 'CUSTOM'}
              viewportTopSlot={
                totalPages > 1 ? (
                  <div className="w-full min-w-[320px]">
                    <PaginationRail
                      page={currentPage}
                      pageSize={1}
                      totalItems={totalPages}
                      totalPages={totalPages}
                      compact
                      onPageChange={onPageChange}
                    />
                  </div>
                ) : null
              }
            />
          )}
        </div>
      </div>

      <div
        className={cn(
          'flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[20px] border bg-background shadow-[var(--shadow-sm)]',
          mobileTab === 'redacted' ? '' : 'hidden',
          'md:flex',
        )}
      >
        <div className="flex h-10 flex-shrink-0 items-center border-b border-border/60 bg-muted/30 px-4">
          <span className="truncate text-xs font-semibold">{t('playground.redactedResult')}</span>
        </div>
        <div className="flex min-h-0 min-w-0 flex-1 items-center justify-center overflow-hidden bg-muted/20">
          {redactedImageError ? (
            <div
              className="mx-6 max-w-md rounded-[20px] border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive shadow-[var(--shadow-sm)]"
              role="alert"
              data-testid="redacted-preview-error"
            >
              <p className="line-clamp-2 font-semibold">{redactedImageError}</p>
              <p className="mt-1 text-xs text-destructive/80">
                {t('playground.redactedPreviewFailedDesc')}
              </p>
            </div>
          ) : redactedImageUrl ? (
            <img
              src={redactedImageUrl}
              alt={t('playground.redactedResult')}
              className="block h-auto max-h-full w-auto max-w-full select-none object-contain"
            />
          ) : fileInfo ? (
            <div className="mx-6 rounded-[20px] border border-dashed border-border/70 bg-background px-5 py-4 text-center shadow-[var(--shadow-sm)]">
              <p className="text-sm font-medium text-foreground">
                {t('playground.redactedPreviewPreparing')}
              </p>
            </div>
          ) : null}
        </div>
      </div>

      <MappingColumn
        entityMap={entityMap}
        origToTypeId={origToTypeId}
        matchCounts={matchCounts}
        scrollToMatch={scrollToMatch}
        className="w-full shadow-[var(--shadow-sm)] md:w-56 md:flex-shrink-0 xl:w-64"
        mobileTab={mobileTab}
        versionHistory={versionHistory}
        versionHistoryOpen={versionHistoryOpen}
        setVersionHistoryOpen={setVersionHistoryOpen}
      />
    </div>
  );
};
