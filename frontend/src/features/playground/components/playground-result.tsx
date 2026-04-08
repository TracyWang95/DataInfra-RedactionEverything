// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { type CSSProperties, type Dispatch, type FC, type SetStateAction, useRef, useState } from 'react';
import { useT } from '@/i18n';
import { RESULT_MARK_HIGHLIGHT_MS } from '@/constants/timing';
import { cn } from '@/lib/utils';
import { getEntityRiskConfig } from '@/config/entityTypes';
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
    }, RESULT_MARK_HIGHLIGHT_MS);
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
      <PlaygroundResultActionBar
        fileInfo={fileInfo}
        redactedCount={redactedCount}
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
