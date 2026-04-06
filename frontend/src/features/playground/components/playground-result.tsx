
import { type CSSProperties, type Dispatch, type FC, type ReactNode, type SetStateAction, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import { getEntityRiskConfig } from '@/config/entityTypes';
import type { VersionHistoryEntry } from '@/types';
import type { BoundingBox, Entity, FileInfo, VisionTypeConfig } from '../types';

export interface PlaygroundResultProps {
  fileInfo: FileInfo | null;
  content: string;
  entities: Entity[];
  entityMap: Record<string, string>;
  redactedCount: number;
  redactionReport: Record<string, unknown> | null;
  reportOpen: boolean;
  setReportOpen: Dispatch<SetStateAction<boolean>>;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: Dispatch<SetStateAction<boolean>>;
  isImageMode: boolean;
  imageUrl: string;
  redactedImageUrl?: string;
  visibleBoxes: BoundingBox[];
  visionTypes: VisionTypeConfig[];
  getVisionTypeConfig: (typeId: string) => { name: string; color: string };
  onBackToEdit: () => void;
  onReset: () => void;
  onDownload: () => void;
}

export const PlaygroundResult: FC<PlaygroundResultProps> = ({
  fileInfo,
  content,
  entities,
  entityMap,
  redactedCount,
  redactionReport,
  reportOpen,
  setReportOpen,
  versionHistory,
  versionHistoryOpen,
  setVersionHistoryOpen,
  isImageMode,
  imageUrl,
  redactedImageUrl,
  visibleBoxes,
  visionTypes,
  getVisionTypeConfig,
  onBackToEdit,
  onReset,
  onDownload,
}) => {
  const t = useT();
  const [mobileTab, setMobileTab] = useState<'original' | 'redacted' | 'mapping'>('original');
  const clickCounterRef = useRef<Record<string, number>>({});

  const origToTypeId = new Map<string, string>();
  for (const entity of entities) {
    if (!entity.selected || entityMap[entity.text] === undefined) continue;
    origToTypeId.set(entity.text, String(entity.type));
    if (typeof entity.start === 'number' && typeof entity.end === 'number' && entity.end <= (content || '').length) {
      const slice = (content || '').slice(entity.start, entity.end);
      if (slice && slice !== entity.text) origToTypeId.set(slice, String(entity.type));
    }
  }

  const buildSegments = (text: string, map: Record<string, string>) => {
    if (!text || Object.keys(map).length === 0) return [{ text, isMatch: false as const }];
    const sortedKeys = Object.keys(map).sort((left, right) => right.length - left.length);
    const regex = new RegExp(`(${sortedKeys.map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
    const parts = text.split(regex);
    const counters: Record<string, number> = {};

    return parts.map((part) => {
      if (map[part] !== undefined) {
        const safeKey = part.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
        const matchIndex = counters[safeKey] || 0;
        counters[safeKey] = matchIndex + 1;
        return { text: part, isMatch: true as const, origKey: part, safeKey, matchIdx: matchIndex };
      }
      return { text: part, isMatch: false as const };
    });
  };

  const segments = buildSegments(content, entityMap);

  const markStyleForOrig = (origKey: string): CSSProperties => {
    const typeId = origToTypeId.get(origKey) ?? '';
    const config = getEntityRiskConfig(typeId || 'CUSTOM');
    return {
      backgroundColor: config.bgColor,
      color: config.textColor,
      boxShadow: `inset 0 -2px 0 ${config.color}55`,
    };
  };

  const scrollToMatch = (original: string) => {
    const safeKey = original.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
    const originalMarks = document.querySelectorAll(`.result-mark-orig[data-match-key="${safeKey}"]`);
    const redactedMarks = document.querySelectorAll(`.result-mark-redacted[data-match-key="${safeKey}"]`);
    const total = Math.max(originalMarks.length, redactedMarks.length);
    if (total === 0) return;

    const index = (clickCounterRef.current[safeKey] || 0) % total;
    clickCounterRef.current[safeKey] = index + 1;

    document.querySelectorAll('.result-mark-active').forEach((element) => {
      element.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
    });

    const originalElement = originalMarks[Math.min(index, originalMarks.length - 1)] as HTMLElement | undefined;
    originalElement?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    originalElement?.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');

    const redactedElement = redactedMarks[Math.min(index, redactedMarks.length - 1)] as HTMLElement | undefined;
    redactedElement?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    redactedElement?.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');

    setTimeout(() => {
      document.querySelectorAll('.result-mark-active').forEach((element) => {
        element.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
      });
    }, 2500);
  };

  const renderOriginal = () => segments.map((segment, index) =>
    segment.isMatch
      ? (
        <mark
          key={index}
          data-match-key={segment.safeKey}
          data-match-idx={segment.matchIdx}
          style={markStyleForOrig(segment.origKey)}
          className="result-mark-orig rounded-md px-0.5 transition-all duration-300"
        >
          {segment.text}
        </mark>
      )
      : <span key={index}>{segment.text}</span>,
  );

  const renderRedacted = () => segments.map((segment, index) =>
    segment.isMatch
      ? (
        <mark
          key={index}
          data-match-key={segment.safeKey}
          data-match-idx={segment.matchIdx}
          style={markStyleForOrig(segment.origKey)}
          className="result-mark-redacted rounded-md px-0.5 transition-all duration-300"
        >
          {entityMap[segment.origKey]}
        </mark>
      )
      : <span key={index}>{segment.text}</span>,
  );

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden" data-testid="playground-result">
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

      {redactionReport && (
        <RedactionReportSection
          report={redactionReport}
          open={reportOpen}
          onToggle={() => setReportOpen((open) => !open)}
        />
      )}

      <div className="mx-3 flex shrink-0 gap-1 rounded-t-2xl border border-border/60 border-b-0 bg-background px-2 pt-2 md:hidden">
        {([
          ['original', t('playground.mobile.original')],
          ['redacted', t('playground.mobile.redacted')],
          ['mapping', t('playground.mobile.mapping')],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setMobileTab(key)}
            className={cn(
              'rounded-xl px-3 py-2 text-xs font-medium transition-colors',
              mobileTab === key ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {isImageMode ? (
        <ImageResultView
          fileInfo={fileInfo}
          imageUrl={imageUrl}
          redactedImageUrl={redactedImageUrl}
          visibleBoxes={visibleBoxes}
          visionTypes={visionTypes}
          getVisionTypeConfig={getVisionTypeConfig}
          entityMap={entityMap}
          origToTypeId={origToTypeId}
          scrollToMatch={scrollToMatch}
          mobileTab={mobileTab}
          versionHistory={versionHistory}
          versionHistoryOpen={versionHistoryOpen}
          setVersionHistoryOpen={setVersionHistoryOpen}
        />
      ) : (
        <TextResultView
          renderOriginal={renderOriginal}
          renderRedacted={renderRedacted}
          content={content}
          entityMap={entityMap}
          origToTypeId={origToTypeId}
          scrollToMatch={scrollToMatch}
          mobileTab={mobileTab}
          versionHistory={versionHistory}
          versionHistoryOpen={versionHistoryOpen}
          setVersionHistoryOpen={setVersionHistoryOpen}
        />
      )}
    </div>
  );
};

const RedactionReportSection: FC<{ report: Record<string, unknown>; open: boolean; onToggle: () => void }> = ({ report, open, onToggle }) => {
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

const MappingColumn: FC<{
  entityMap: Record<string, string>;
  origToTypeId: Map<string, string>;
  scrollToMatch: (orig: string) => void;
  content?: string;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: Dispatch<SetStateAction<boolean>>;
  className?: string;
  mobileTab: string;
}> = ({
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

const TextResultView: FC<{
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

const ImageResultView: FC<{
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
