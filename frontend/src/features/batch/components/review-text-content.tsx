// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type React from 'react';
import { memo, useCallback, useRef, useState } from 'react';

import { useT } from '@/i18n';
import { Card } from '@/components/ui/card';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import type { TextSegment } from '@/utils/textRedactionSegments';

import type { ReviewEntity, TextEntityType } from '../types';
import { ReviewAnnotationPopover } from './review-annotation-popover';
import { ReviewEntityPopover } from './review-entity-popover';
import { ReviewEntityList } from './review-entity-list';
import { useTextSelection } from './use-text-selection';

export interface ReviewTextContentProps {
  reviewEntities: ReviewEntity[];
  reviewTextContent: string;
  reviewTextContentRef: React.RefObject<HTMLDivElement | null>;
  reviewTextScrollRef: React.RefObject<HTMLDivElement | null>;
  selectedReviewEntityCount: number;
  displayPreviewMap: Record<string, string>;
  textPreviewSegments: TextSegment[];
  applyReviewEntities: (updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[])) => void;
  textTypes: TextEntityType[];
  reviewFileReadOnly: boolean;
}

function ReviewTextContentInner({
  reviewEntities,
  reviewTextContent,
  reviewTextContentRef,
  reviewTextScrollRef,
  selectedReviewEntityCount,
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

  const handleEntityClick = useCallback((entity: ReviewEntity) => {
    if (reviewFileReadOnly) return;
    clearTextSelection();
    setClickedEntity(entity);
    const el = reviewTextContentRef.current?.querySelector(`[data-review-entity-id="${CSS.escape(entity.id)}"]`) as HTMLElement | null;
    const card = cardRef.current;
    if (el && card) {
      const elRect = el.getBoundingClientRect();
      const cardRect = card.getBoundingClientRect();
      setEntityPopupPos({
        left: Math.min(Math.max(elRect.left - cardRect.left, 4), cardRect.width - 224),
        top: elRect.bottom - cardRect.top + 4,
      });
    }
  }, [reviewFileReadOnly, clearTextSelection, reviewTextContentRef]);

  const removeClickedEntity = useCallback(() => {
    if (!clickedEntity) return;
    applyReviewEntities(prev => prev.filter(e => e.id !== clickedEntity.id));
    setClickedEntity(null);
    setEntityPopupPos(null);
  }, [clickedEntity, applyReviewEntities]);

  const renderMarkedContent = () => {
    if (!reviewTextContent) return <p className="text-muted-foreground">-</p>;
    const sorted = [...reviewEntities].sort((a, b) => a.start - b.start);
    const nodes: React.ReactNode[] = [];
    let lastEnd = 0;
    sorted.forEach(entity => {
      if (entity.start < lastEnd) return;
      if (entity.start > lastEnd) {
        nodes.push(<span key={`txt-${lastEnd}`}>{reviewTextContent.slice(lastEnd, entity.start)}</span>);
      }
      const risk = getEntityRiskConfig(entity.type);
      nodes.push(
        <mark
          key={entity.id}
          data-review-entity-id={entity.id}
          className="inline cursor-pointer rounded-sm px-0.5 py-[1px] transition-all hover:brightness-95 hover:ring-2 hover:ring-offset-1 hover:ring-blue-400/20 hover:shadow-sm"
          style={{ backgroundColor: risk.bgColor, color: risk.textColor, opacity: entity.selected ? 1 : 0.45 }}
          title={`${getEntityTypeName(entity.type)}`}
          onClick={() => handleEntityClick(entity)}
        >
          {reviewTextContent.slice(entity.start, entity.end)}
        </mark>,
      );
      lastEnd = entity.end;
    });
    if (lastEnd < reviewTextContent.length) {
      nodes.push(<span key="txt-end">{reviewTextContent.slice(lastEnd)}</span>);
    }
    return nodes;
  };

  const batchMarkStyle = (origKey: string): React.CSSProperties => {
    const entity = reviewEntities.find(e => e.text === origKey);
    const riskCfg = getEntityRiskConfig(entity?.type ?? 'CUSTOM');
    return { backgroundColor: riskCfg.bgColor, color: riskCfg.textColor };
  };

  return (
    <div className="flex-1 min-h-0 grid gap-3 p-3 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1.1fr)_320px]">
      {/* Original text */}
      <Card ref={cardRef} className="relative min-h-0 flex flex-col overflow-hidden">
        <div className="shrink-0 px-4 py-2 border-b flex items-center justify-between">
          <span className="text-xs font-semibold">{t('batchWizard.step4.originalText')}</span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {t('batchWizard.step4.selected')} {selectedReviewEntityCount}/{reviewEntities.length}
          </span>
        </div>
        <div
          ref={reviewTextScrollRef}
          className="flex-1 overflow-auto p-4"
          onScroll={() => {
            if (clickedEntity) { setClickedEntity(null); setEntityPopupPos(null); }
            const orig = reviewTextScrollRef.current;
            const prev = previewScrollRef.current;
            if (orig && prev && orig.scrollHeight > orig.clientHeight) {
              const ratio = orig.scrollTop / (orig.scrollHeight - orig.clientHeight);
              prev.scrollTop = ratio * (prev.scrollHeight - prev.clientHeight);
            }
          }}
        >
          <div
            ref={reviewTextContentRef}
            className="text-sm leading-relaxed whitespace-pre-wrap select-text font-[system-ui]"
            onMouseUp={handleTextSelect}
          >
            {renderMarkedContent()}
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
            onClose={() => { setClickedEntity(null); setEntityPopupPos(null); }}
          />
        )}
      </Card>

      {/* Redacted preview */}
      <Card className="min-h-0 flex flex-col overflow-hidden">
        <div className="shrink-0 px-4 py-2 border-b">
          <span className="text-xs font-semibold">{t('batchWizard.step4.redactedPreview')}</span>
        </div>
        <div ref={previewScrollRef} className="flex-1 overflow-auto p-4">
          <div className="text-sm leading-relaxed whitespace-pre-wrap font-[system-ui]">
            {textPreviewSegments.map((seg, i) =>
              seg.isMatch ? (
                <mark key={i} style={batchMarkStyle(seg.origKey)} className="px-0.5 rounded-md transition-all duration-300">
                  {displayPreviewMap[seg.origKey] ?? seg.origKey}
                </mark>
              ) : (
                <span key={i}>{seg.text}</span>
              ),
            )}
          </div>
        </div>
      </Card>

      {/* Entity list */}
      <ReviewEntityList
        reviewEntities={reviewEntities}
        selectedReviewEntityCount={selectedReviewEntityCount}
        textTypes={textTypes}
        applyReviewEntities={applyReviewEntities}
        reviewTextContentRef={reviewTextContentRef}
        reviewTextScrollRef={reviewTextScrollRef}
        previewScrollRef={previewScrollRef}
      />
    </div>
  );
}

export const ReviewTextContent = memo(ReviewTextContentInner);
