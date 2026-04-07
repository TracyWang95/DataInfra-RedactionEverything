// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { Dispatch, FC, ReactNode, SetStateAction } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import type { VersionHistoryEntry } from '@/types';
import type { BoundingBox, FileInfo, VisionTypeConfig } from '../types';
import { MappingColumn } from './playground-result-mapping';

export const TextResultView: FC<{
  renderOriginal: () => ReactNode[];
  renderRedacted: () => ReactNode[];
  content: string;
  entityMap: Record<string, string>;
  origToTypeId: Map<string, string>;
  scrollToMatch: (orig: string) => void;
  mobileTab: string;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: Dispatch<SetStateAction<boolean>>;
}> = ({
  renderOriginal,
  renderRedacted,
  content,
  entityMap,
  origToTypeId,
  scrollToMatch,
  mobileTab,
  versionHistory,
  versionHistoryOpen,
  setVersionHistoryOpen,
}) => {
  const t = useT();

  return (
    <div className="flex min-h-0 min-w-0 flex-1 gap-2 px-3 pb-3 sm:gap-3 sm:px-4 sm:pb-4">
    <div className={cn('flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-background', mobileTab === 'original' ? '' : 'hidden', 'md:flex')}>
      <div className="flex-shrink-0 border-b border-border/60 bg-muted/30 px-4 py-3">
        <span className="text-xs font-semibold">{t('playground.originalDoc')}</span>
      </div>
      <ScrollArea className="flex-1 p-4">
        <div className="font-[system-ui] text-sm leading-relaxed whitespace-pre-wrap">{renderOriginal()}</div>
      </ScrollArea>
    </div>

    <div className={cn('flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-background', mobileTab === 'redacted' ? '' : 'hidden', 'md:flex')}>
      <div className="flex-shrink-0 border-b border-border/60 bg-muted/30 px-4 py-3">
        <span className="text-xs font-semibold">{t('playground.redactedResult')}</span>
      </div>
      <ScrollArea className="flex-1 p-4">
        <div className="font-[system-ui] text-sm leading-relaxed whitespace-pre-wrap">{renderRedacted()}</div>
      </ScrollArea>
    </div>

    <MappingColumn
      entityMap={entityMap}
      origToTypeId={origToTypeId}
      scrollToMatch={scrollToMatch}
      content={content}
      className="w-full md:w-64 md:flex-shrink-0"
      mobileTab={mobileTab}
      versionHistory={versionHistory}
      versionHistoryOpen={versionHistoryOpen}
      setVersionHistoryOpen={setVersionHistoryOpen}
    />
  </div>
  );
};

export const ImageResultView: FC<{
  fileInfo: FileInfo | null;
  imageUrl: string;
  redactedImageUrl?: string;
  visibleBoxes: BoundingBox[];
  visionTypes: VisionTypeConfig[];
  getVisionTypeConfig: (typeId: string) => { name: string; color: string };
  entityMap: Record<string, string>;
  origToTypeId: Map<string, string>;
  scrollToMatch: (orig: string) => void;
  mobileTab: string;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: Dispatch<SetStateAction<boolean>>;
}> = ({
  fileInfo,
  imageUrl,
  redactedImageUrl,
  visibleBoxes,
  visionTypes,
  getVisionTypeConfig,
  entityMap,
  origToTypeId,
  scrollToMatch,
  mobileTab,
  versionHistory,
  versionHistoryOpen,
  setVersionHistoryOpen,
}) => {
  const t = useT();

  return (
    <div className="flex min-h-0 min-w-0 flex-1 gap-2 px-3 pb-3 sm:gap-3 sm:px-4 sm:pb-4">
    <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-background', mobileTab === 'original' ? '' : 'hidden', 'md:flex')}>
      <div className="flex-shrink-0 border-b border-border/60 bg-muted/30 px-4 py-3">
        <span className="text-xs font-semibold">{t('playground.originalImage')}</span>
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
          />
        )}
      </div>
    </div>

    <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-background', mobileTab === 'redacted' ? '' : 'hidden', 'md:flex')}>
      <div className="flex-shrink-0 border-b border-border/60 bg-muted/30 px-4 py-3">
        <span className="text-xs font-semibold">{t('playground.redactedResult')}</span>
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 items-center justify-center overflow-hidden bg-muted/20">
        {fileInfo && (
          <img
            src={redactedImageUrl || `/api/v1/files/${fileInfo.file_id}/download?redacted=true`}
            alt={t('playground.redactedResult')}
            className="block h-auto max-h-full w-auto max-w-full select-none object-contain"
          />
        )}
      </div>
    </div>

    <MappingColumn
      entityMap={entityMap}
      origToTypeId={origToTypeId}
      scrollToMatch={scrollToMatch}
      className="w-full md:w-52 md:flex-shrink-0"
      mobileTab={mobileTab}
      versionHistory={versionHistory}
      versionHistoryOpen={versionHistoryOpen}
      setVersionHistoryOpen={setVersionHistoryOpen}
    />
  </div>
  );
};
