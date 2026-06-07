// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type React from 'react';
import { memo, useCallback, useMemo, useRef, useState } from 'react';

import { useT } from '@/i18n';
import { Card } from '@/components/ui/card';
import { PaginationRail } from '@/components/PaginationRail';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import { clampPopoverInCanvas } from '@/utils/domSelection';
import { buildTextSegments, type TextSegment } from '@/utils/textRedactionSegments';

import type { ReviewEntity, TextEntityType } from '../types';
import { ReviewAnnotationPopover } from './review-annotation-popover';
import { ReviewEntityPopover } from './review-entity-popover';
import { ReviewEntityList, type ReviewEntityOccurrenceGroup } from './review-entity-list';
import { useTextSelection } from './use-text-selection';

const DEFAULT_BATCH_MARK_STYLE = (() => {
  const riskCfg = getEntityRiskConfig('CUSTOM');
  return { backgroundColor: riskCfg.bgColor, color: riskCfg.textColor };
})();

export interface ReviewTextContentProps {
  reviewEntities: ReviewEntity[];
  visibleReviewEntities: ReviewEntity[];
  reviewTextContent: string;
  reviewPageContent: string;
  reviewTextContentRef: React.RefObject<HTMLDivElement | null>;
  reviewTextScrollRef: React.RefObject<HTMLDivElement | null>;
  selectedReviewEntityCount: number;
  reviewCurrentPage: number;
  reviewTotalPages: number;
  onReviewPageChange: (page: number) => void;
  displayPreviewMap: Record<string, string>;
  textPreviewSegments: TextSegment[];
  applyReviewEntities: (
    updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[]),
  ) => void;
  textTypes: TextEntityType[];
  reviewFileReadOnly: boolean;
}

interface ReviewEntityMarkProps {
  entity: ReviewEntity;
  occurrenceId?: string;
  text: string;
  entityLabel: string;
  entityTypeName: string;
  reviewFileReadOnly: boolean;
  onEntityClick: (entity: ReviewEntity, element: HTMLElement) => void;
}

function ReviewEntityMarkInner({
  entity,
  occurrenceId,
  text,
  entityLabel,
  entityTypeName,
  reviewFileReadOnly,
  onEntityClick,
}: ReviewEntityMarkProps) {
  const risk = getEntityRiskConfig(entity.type);
  const markStyle = useMemo<React.CSSProperties>(
    () => ({
      backgroundColor: risk.bgColor,
      color: risk.textColor,
      opacity: entity.selected ? 1 : 0.45,
    }),
    [entity.selected, risk.bgColor, risk.textColor],
  );
  const handleClick = useCallback((event: React.MouseEvent<HTMLElement>) => {
    onEntityClick(entity, event.currentTarget);
  }, [entity, onEntityClick]);
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLElement>) => {
      if (reviewFileReadOnly || (event.key !== 'Enter' && event.key !== ' ')) return;
      event.preventDefault();
      onEntityClick(entity, event.currentTarget);
    },
    [entity, onEntityClick, reviewFileReadOnly],
  );

  return (
    <mark
      data-review-entity-id={entity.id}
      data-review-occurrence-id={occurrenceId}
      role={reviewFileReadOnly ? undefined : 'button'}
      tabIndex={reviewFileReadOnly ? undefined : 0}
      aria-label={entityLabel}
      className="inline cursor-pointer rounded-sm px-0.5 py-[1px] transition-all hover:brightness-95 hover:ring-2 hover:ring-offset-1 hover:ring-blue-400/20 hover:shadow-sm"
      style={markStyle}
      title={entityTypeName}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
    >
      {text}
    </mark>
  );
}

const ReviewEntityMark = memo(ReviewEntityMarkInner, (prev, next) => {
  const prevEntity = prev.entity;
  const nextEntity = next.entity;
  return (
    prev.text === next.text &&
    prev.occurrenceId === next.occurrenceId &&
    prev.entityLabel === next.entityLabel &&
    prev.entityTypeName === next.entityTypeName &&
    prev.reviewFileReadOnly === next.reviewFileReadOnly &&
    prev.onEntityClick === next.onEntityClick &&
    prevEntity.id === nextEntity.id &&
    prevEntity.type === nextEntity.type &&
    prevEntity.text === nextEntity.text &&
    prevEntity.start === nextEntity.start &&
    prevEntity.end === nextEntity.end &&
    prevEntity.selected === nextEntity.selected
  );
});

function ReviewTextContentInner({
  reviewEntities,
  visibleReviewEntities,
  reviewTextContent,
  reviewPageContent,
  reviewTextContentRef,
  reviewTextScrollRef,
  selectedReviewEntityCount,
  reviewCurrentPage,
  reviewTotalPages,
  onReviewPageChange,
  displayPreviewMap,
  textPreviewSegments,
  applyReviewEntities,
  textTypes,
  reviewFileReadOnly,
}: ReviewTextContentProps) {
  const t = useT();
  const cardRef = useRef<HTMLDivElement | null>(null);
  const previewScrollRef = useRef<HTMLDivElement>(null);

  // ── Clicked entity popover (remove annotation) ──
  const [clickedEntity, setClickedEntity] = useState<ReviewEntity | null>(null);
  const [entityPopupPos, setEntityPopupPos] = useState<{ left: number; top: number } | null>(null);

  // ── Text selection hook ──
  const {
    selectedText,
    selectionPos,
    selectedTypeId,
    setSelectedTypeId,
    clearTextSelection,
    handleTextSelect,
    addManualAnnotation,
  } = useTextSelection({
    reviewTextContent,
    reviewTextContentRef,
    reviewTextScrollRef,
    cardRef,
    textTypes,
    reviewFileReadOnly,
    applyReviewEntities,
  });

  const handleEntityClick = useCallback(
    (entity: ReviewEntity, element: HTMLElement) => {
      if (reviewFileReadOnly) return;
      clearTextSelection();
      setClickedEntity(entity);
      const card = cardRef.current;
      if (card) {
        const elRect = element.getBoundingClientRect();
        const cardRect = card.getBoundingClientRect();
        const clamped = clampPopoverInCanvas(elRect, cardRect, 220, 120);
        setEntityPopupPos({
          left: clamped.left - cardRect.left,
          top: clamped.top - cardRect.top,
        });
      }
    },
    [reviewFileReadOnly, clearTextSelection],
  );

  const removeClickedEntity = useCallback(() => {
    if (!clickedEntity) return;
    applyReviewEntities((prev) => prev.filter((e) => e.id !== clickedEntity.id));
    setClickedEntity(null);
    setEntityPopupPos(null);
  }, [clickedEntity, applyReviewEntities]);

  const closeClickedEntity = useCallback(() => {
    setClickedEntity(null);
    setEntityPopupPos(null);
  }, []);

  const handleOriginalScroll = useCallback(() => {
    if (clickedEntity) {
      setClickedEntity(null);
      setEntityPopupPos(null);
    }
    const orig = reviewTextScrollRef.current;
    const prev = previewScrollRef.current;
    if (orig && prev && orig.scrollHeight > orig.clientHeight) {
      const ratio = orig.scrollTop / (orig.scrollHeight - orig.clientHeight);
      prev.scrollTop = ratio * (prev.scrollHeight - prev.clientHeight);
    }
  }, [clickedEntity, reviewTextScrollRef]);

  const sortedVisibleReviewEntities = useMemo(
    () => [...visibleReviewEntities].sort((a, b) => a.start - b.start),
    [visibleReviewEntities],
  );

  const entityByText = useMemo(() => {
    const map = new Map<string, ReviewEntity>();
    for (const entity of reviewEntities) {
      if (entity.selected === false || map.has(entity.text)) continue;
      map.set(entity.text, entity);
    }
    return map;
  }, [reviewEntities]);

  const redactionOccurrenceSegments = useMemo(
    () => buildTextSegments(reviewPageContent, displayPreviewMap),
    [displayPreviewMap, reviewPageContent],
  );
  const redactionOccurrenceGroups = useMemo<ReviewEntityOccurrenceGroup[]>(() => {
    const groups = new Map<string, ReviewEntityOccurrenceGroup>();
    for (const seg of redactionOccurrenceSegments) {
      if (!seg.isMatch) continue;
      const entity = entityByText.get(seg.origKey);
      const type = entity?.type ?? 'CUSTOM';
      const key = `${type}::${seg.origKey}`;
      const occurrenceId = `occ-${seg.safeKey}-${seg.matchIdx}`;
      const group =
        groups.get(key) ??
        ({
          type,
          text: seg.origKey,
          entityIds: entity ? [entity.id] : [],
          occurrenceIds: [],
          selected: 0,
          total: 0,
        } satisfies ReviewEntityOccurrenceGroup);
      if (entity && !group.entityIds.includes(entity.id)) group.entityIds.push(entity.id);
      group.occurrenceIds.push(occurrenceId);
      group.total++;
      if (!entity || entity.selected !== false) group.selected++;
      groups.set(key, group);
    }
    return Array.from(groups.values());
  }, [entityByText, redactionOccurrenceSegments]);
  const redactionOccurrenceCount = useMemo(
    () => redactionOccurrenceGroups.reduce((sum, group) => sum + group.total, 0),
    [redactionOccurrenceGroups],
  );
  const displaySelectedReviewCount =
    redactionOccurrenceCount > 0 ? redactionOccurrenceCount : selectedReviewEntityCount;
  const displayTotalReviewCount =
    redactionOccurrenceCount > 0
      ? redactionOccurrenceCount
      : reviewTotalPages > 1
        ? visibleReviewEntities.length
        : reviewEntities.length;

  const markedContent = useMemo(() => {
    if (!reviewPageContent) return <p className="text-muted-foreground">-</p>;
    const hasReplacementMark = redactionOccurrenceSegments.some((seg) => seg.isMatch);
    const replacementNodes = redactionOccurrenceSegments.map((seg, index) => {
      if (!seg.isMatch) return <span key={`txt-${index}`}>{seg.text}</span>;
      const entity =
        entityByText.get(seg.origKey) ??
        ({
          id: `entity-map-${seg.safeKey}`,
          text: seg.origKey,
          type: 'CUSTOM',
          start: -1,
          end: -1,
          selected: true,
        } satisfies ReviewEntity);
      const entityTypeName = getEntityTypeName(entity.type);
      const entityLabel = t('batchWizard.step4.entityMarkLabel')
        .replace('{type}', entityTypeName)
        .replace('{text}', entity.text)
        .replace(
          '{state}',
          entity.selected ? t('batchWizard.step4.selected') : t('editor.deselected'),
        );
      return (
        <ReviewEntityMark
          key={`match-${seg.safeKey}-${seg.matchIdx}-${index}`}
          entity={entity}
          occurrenceId={`occ-${seg.safeKey}-${seg.matchIdx}`}
          text={displayPreviewMap[seg.origKey] ?? seg.text}
          entityLabel={entityLabel}
          entityTypeName={entityTypeName}
          reviewFileReadOnly={reviewFileReadOnly}
          onEntityClick={handleEntityClick}
        />
      );
    });
    if (hasReplacementMark) return replacementNodes;

    const nodes: React.ReactNode[] = [];
    let lastEnd = 0;
    sortedVisibleReviewEntities.forEach((entity) => {
      if (entity.start < 0 || entity.end > reviewPageContent.length) return;
      if (entity.start < lastEnd) return;
      if (entity.start > lastEnd) {
        nodes.push(
          <span key={`txt-${lastEnd}`}>{reviewPageContent.slice(lastEnd, entity.start)}</span>,
        );
      }
      const entityTypeName = getEntityTypeName(entity.type);
      const entityLabel = t('batchWizard.step4.entityMarkLabel')
        .replace('{type}', entityTypeName)
        .replace('{text}', entity.text)
        .replace(
          '{state}',
          entity.selected ? t('batchWizard.step4.selected') : t('editor.deselected'),
        );
      nodes.push(
        <ReviewEntityMark
          key={entity.id}
          entity={entity}
          occurrenceId={entity.id}
          text={reviewPageContent.slice(entity.start, entity.end)}
          entityLabel={entityLabel}
          entityTypeName={entityTypeName}
          reviewFileReadOnly={reviewFileReadOnly}
          onEntityClick={handleEntityClick}
        />,
      );
      lastEnd = entity.end;
    });
    if (lastEnd < reviewPageContent.length) {
      nodes.push(<span key="txt-end">{reviewPageContent.slice(lastEnd)}</span>);
    }
    return nodes;
  }, [
    displayPreviewMap,
    entityByText,
    handleEntityClick,
    redactionOccurrenceSegments,
    reviewFileReadOnly,
    reviewPageContent,
    sortedVisibleReviewEntities,
    t,
  ]);

  const previewRiskStyleByText = useMemo(() => {
    const styleByText = new Map<string, React.CSSProperties>();
    reviewEntities.forEach((entity) => {
      if (styleByText.has(entity.text)) return;
      const riskCfg = getEntityRiskConfig(entity.type);
      styleByText.set(entity.text, {
        backgroundColor: riskCfg.bgColor,
        color: riskCfg.textColor,
      });
    });
    return styleByText;
  }, [reviewEntities]);

  const batchMarkStyle = useCallback(
    (origKey: string): React.CSSProperties => {
      const cached = previewRiskStyleByText.get(origKey);
      if (cached) return cached;
      return DEFAULT_BATCH_MARK_STYLE;
    },
    [previewRiskStyleByText],
  );

  const previewContent = useMemo(
    () =>
      textPreviewSegments.map((seg, i) =>
        seg.isMatch ? (
          <mark
            key={i}
            style={batchMarkStyle(seg.origKey)}
            className="px-0.5 rounded-md transition-all duration-300"
          >
            {displayPreviewMap[seg.origKey] ?? seg.origKey}
          </mark>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      ),
    [batchMarkStyle, displayPreviewMap, textPreviewSegments],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-2">
      {reviewTotalPages > 1 && (
        <div className="flex-shrink-0">
          <PaginationRail
            page={reviewCurrentPage}
            pageSize={1}
            totalItems={reviewTotalPages}
            totalPages={reviewTotalPages}
            compact
            onPageChange={onReviewPageChange}
            testIdPrefix="review-page"
          />
        </div>
      )}
      <div className="grid min-h-0 flex-1 gap-2 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1.1fr)_300px] 2xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1.1fr)_320px]">
        {/* Original text */}
        <Card
          ref={cardRef}
          className="relative page-surface border-border/70 shadow-[var(--shadow-sm)]"
        >
          <div className="flex h-8 shrink-0 items-center justify-between border-b px-3">
            <span className="truncate text-xs font-semibold">
              {t('batchWizard.step4.originalText')}
            </span>
            <span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground tabular-nums">
              {t('batchWizard.step4.selected')} {displaySelectedReviewCount}/
              {displayTotalReviewCount}
            </span>
          </div>
          <div
            ref={reviewTextScrollRef}
            className="flex-1 overflow-auto p-3"
            onScroll={handleOriginalScroll}
          >
            <div
              ref={reviewTextContentRef}
              className="text-sm leading-relaxed whitespace-pre-wrap select-text font-[system-ui]"
              onMouseUp={handleTextSelect}
            >
              {markedContent}
            </div>
          </div>

          {selectedText && selectionPos && (
            <ReviewAnnotationPopover
              selectedText={selectedText.text}
              selectionPos={selectionPos}
              selectedTypeId={selectedTypeId}
              textTypes={textTypes}
              onTypeSelect={setSelectedTypeId}
              onAdd={addManualAnnotation}
              onClose={clearTextSelection}
            />
          )}

          {clickedEntity && entityPopupPos && (
            <ReviewEntityPopover
              entity={clickedEntity}
              position={entityPopupPos}
              onRemove={removeClickedEntity}
              onClose={closeClickedEntity}
            />
          )}
        </Card>

        {/* Redacted preview */}
        <Card className="page-surface border-border/70 shadow-[var(--shadow-sm)]">
          <div className="flex h-8 shrink-0 items-center border-b px-3">
            <span className="truncate text-xs font-semibold">
              {t('batchWizard.step4.redactedPreview')}
            </span>
          </div>
          <div ref={previewScrollRef} className="flex-1 overflow-auto p-3">
            <div className="text-sm leading-relaxed whitespace-pre-wrap font-[system-ui]">
              {previewContent}
            </div>
          </div>
        </Card>

        {/* Entity list */}
        <ReviewEntityList
          reviewEntities={reviewTotalPages > 1 ? visibleReviewEntities : reviewEntities}
          selectedReviewEntityCount={selectedReviewEntityCount}
          displaySelectedCount={displaySelectedReviewCount}
          displayTotalCount={displayTotalReviewCount}
          occurrenceGroups={redactionOccurrenceGroups}
          textTypes={textTypes}
          applyReviewEntities={applyReviewEntities}
          reviewTextContentRef={reviewTextContentRef}
          reviewTextScrollRef={reviewTextScrollRef}
          previewScrollRef={previewScrollRef}
        />
      </div>
    </div>
  );
}

export const ReviewTextContent = memo(ReviewTextContentInner);
