// Copyright 2026 DataInfra-RedactionEverything Contributors

import {
  type CSSProperties,
  type Dispatch,
  type FC,
  type SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useT } from '@/i18n';
import { RESULT_MARK_HIGHLIGHT_MS } from '@/constants/timing';
import { cn } from '@/lib/utils';
import { getEntityRiskConfig } from '@/config/entityTypes';
import { buildTextSegments } from '@/utils/textRedactionSegments';
import type { VersionHistoryEntry } from '@/types';
import type { BoundingBox, Entity, FileInfo, VisionTypeConfig } from '../types';
import { PlaygroundResultActionBar, RedactionReportSection } from './playground-result-action-bar';
import { TextResultView, ImageResultView } from './playground-result-views';

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
  redactedImageError?: string | null;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
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
  redactedImageError,
  currentPage,
  totalPages,
  onPageChange,
  visibleBoxes,
  visionTypes,
  getVisionTypeConfig,
  onBackToEdit,
  onReset,
  onDownload,
}) => {
  const t = useT();
  const [mobileTab, setMobileTab] = useState<'original' | 'redacted' | 'mapping'>('original');
  const rootRef = useRef<HTMLDivElement | null>(null);
  const clickCounterRef = useRef<Record<string, number>>({});
  const activeMarkTimeoutRef = useRef<number | null>(null);
  const activeMarksRef = useRef<HTMLElement[]>([]);
  const resultReady = !isImageMode || Boolean(redactedImageUrl);

  const isTextPaginated = !isImageMode && totalPages > 1;
  const pageEntities = useMemo(
    () =>
      isTextPaginated
        ? entities.filter((entity) => Number(entity.page || 1) === currentPage)
        : entities,
    [currentPage, entities, isTextPaginated],
  );
  const pages = fileInfo?.pages;
  const displayContent = useMemo(
    () =>
      isTextPaginated && Array.isArray(pages) && pages.length === totalPages
        ? (pages[currentPage - 1] ?? content)
        : content,
    [content, currentPage, isTextPaginated, pages, totalPages],
  );
  const displayEntityMap = useMemo(() => {
    if (!isTextPaginated) return entityMap;
    const selectedTexts = new Set(
      pageEntities.filter((entity) => entity.selected !== false).map((entity) => entity.text),
    );
    return Object.fromEntries(Object.entries(entityMap).filter(([key]) => selectedTexts.has(key)));
  }, [entityMap, isTextPaginated, pageEntities]);

  const origToTypeId = useMemo(() => {
    const out = new Map<string, string>();
    const fullContent = content || '';
    for (const entity of pageEntities) {
      if (!entity.selected || displayEntityMap[entity.text] === undefined) continue;
      out.set(entity.text, String(entity.type));
      if (
        typeof entity.start === 'number' &&
        typeof entity.end === 'number' &&
        entity.end <= fullContent.length
      ) {
        const slice = fullContent.slice(entity.start, entity.end);
        if (slice && slice !== entity.text) out.set(slice, String(entity.type));
      }
    }
    return out;
  }, [content, displayEntityMap, pageEntities]);

  const segments = useMemo(
    () => buildTextSegments(displayContent, displayEntityMap),
    [displayContent, displayEntityMap],
  );
  const matchCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const segment of segments) {
      if (segment.isMatch) {
        counts.set(segment.origKey, (counts.get(segment.origKey) || 0) + 1);
      }
    }
    return counts;
  }, [segments]);

  const markStyleForOrig = useCallback(
    (origKey: string): CSSProperties => {
      const typeId = origToTypeId.get(origKey) ?? '';
      const config = getEntityRiskConfig(typeId || 'CUSTOM');
      return {
        backgroundColor: config.bgColor,
        color: config.textColor,
        boxShadow: `inset 0 -2px 0 ${config.color}55`,
      };
    },
    [origToTypeId],
  );

  const clearActiveMarks = useCallback(() => {
    if (activeMarkTimeoutRef.current !== null) {
      window.clearTimeout(activeMarkTimeoutRef.current);
      activeMarkTimeoutRef.current = null;
    }
    for (const element of activeMarksRef.current) {
      element.classList.remove(
        'result-mark-active',
        'ring-2',
        'ring-offset-1',
        'ring-blue-400/80',
        'scale-105',
      );
    }
    activeMarksRef.current = [];
  }, []);

  useEffect(() => () => clearActiveMarks(), [clearActiveMarks]);

  const scrollToMatch = useCallback(
    (original: string) => {
      const safeKey = original.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
      const root = rootRef.current;
      if (!root) return;
      const originalMarks = root.querySelectorAll(`.result-mark-orig[data-match-key="${safeKey}"]`);
      const redactedMarks = root.querySelectorAll(
        `.result-mark-redacted[data-match-key="${safeKey}"]`,
      );
      const total = Math.max(originalMarks.length, redactedMarks.length);
      if (total === 0) return;

      const index = (clickCounterRef.current[safeKey] || 0) % total;
      clickCounterRef.current[safeKey] = index + 1;

      clearActiveMarks();

      const originalElement = originalMarks[Math.min(index, originalMarks.length - 1)] as
        | HTMLElement
        | undefined;
      originalElement?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      originalElement?.classList.add(
        'result-mark-active',
        'ring-2',
        'ring-offset-1',
        'ring-blue-400/80',
        'scale-105',
      );

      const redactedElement = redactedMarks[Math.min(index, redactedMarks.length - 1)] as
        | HTMLElement
        | undefined;
      redactedElement?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      redactedElement?.classList.add(
        'result-mark-active',
        'ring-2',
        'ring-offset-1',
        'ring-blue-400/80',
        'scale-105',
      );

      activeMarksRef.current = [originalElement, redactedElement].filter(Boolean) as HTMLElement[];
      activeMarkTimeoutRef.current = window.setTimeout(() => {
        clearActiveMarks();
      }, RESULT_MARK_HIGHLIGHT_MS);
    },
    [clearActiveMarks],
  );

  const renderOriginal = useCallback(
    () =>
      segments.map((segment, index) =>
        segment.isMatch ? (
          <mark
            key={index}
            data-match-key={segment.safeKey}
            data-match-idx={segment.matchIdx}
            style={markStyleForOrig(segment.origKey)}
            className="result-mark-orig rounded-md px-0.5 transition-all duration-300"
          >
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      ),
    [markStyleForOrig, segments],
  );

  const renderRedacted = useCallback(
    () =>
      segments.map((segment, index) =>
        segment.isMatch ? (
          <mark
            key={index}
            data-match-key={segment.safeKey}
            data-match-idx={segment.matchIdx}
            style={markStyleForOrig(segment.origKey)}
            className="result-mark-redacted rounded-md px-0.5 transition-all duration-300"
          >
            {displayEntityMap[segment.origKey]}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      ),
    [displayEntityMap, markStyleForOrig, segments],
  );

  return (
    <div
      ref={rootRef}
      className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
      data-testid="playground-result"
    >
      <PlaygroundResultActionBar
        fileInfo={fileInfo}
        redactedCount={redactedCount}
        resultReady={resultReady}
        canDownload={resultReady}
        onBackToEdit={onBackToEdit}
        onReset={onReset}
        onDownload={onDownload}
      />

      {redactionReport && (
        <RedactionReportSection
          report={redactionReport}
          open={reportOpen}
          onToggle={() => setReportOpen((open) => !open)}
        />
      )}

      <div className="mx-3 flex shrink-0 gap-1 rounded-t-[20px] border border-border/60 border-b-0 bg-background px-2 pt-2 md:hidden">
        {(
          [
            ['original', t('playground.mobile.original')],
            ['redacted', t('playground.mobile.redacted')],
            ['mapping', t('playground.mobile.mapping')],
          ] as const
        ).map(([key, label]) => (
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
          redactedImageError={redactedImageError}
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={onPageChange}
          visibleBoxes={visibleBoxes}
          visionTypes={visionTypes}
          getVisionTypeConfig={getVisionTypeConfig}
          entityMap={entityMap}
          origToTypeId={origToTypeId}
          matchCounts={matchCounts}
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
          content={displayContent}
          entityMap={displayEntityMap}
          origToTypeId={origToTypeId}
          matchCounts={matchCounts}
          scrollToMatch={scrollToMatch}
          mobileTab={mobileTab}
          versionHistory={versionHistory}
          versionHistoryOpen={versionHistoryOpen}
          setVersionHistoryOpen={setVersionHistoryOpen}
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={onPageChange}
        />
      )}
    </div>
  );
};
