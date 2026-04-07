// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type React from 'react';
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import type { TextSegment } from '@/utils/textRedactionSegments';
import { getSelectionOffsets, clampPopoverInCanvas } from '@/utils/domSelection';
import type { ReviewEntity, TextEntityType } from '../types';

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

export function ReviewTextContent({
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

  // ── Clicked entity popover (remove annotation) ──
  const [clickedEntity, setClickedEntity] = useState<ReviewEntity | null>(null);
  const [entityPopupPos, setEntityPopupPos] = useState<{ left: number; top: number } | null>(null);

  // ── Grouped entity list ──
  const entityGroups = useMemo(() => {
    const map = new Map<string, { type: string; text: string; ids: string[]; selected: number; total: number }>();
    reviewEntities.forEach(e => {
      const key = `${e.type}::${e.text}`;
      const g = map.get(key) || { type: e.type, text: e.text, ids: [], selected: 0, total: 0 };
      g.ids.push(e.id);
      g.total++;
      if (e.selected !== false) g.selected++;
      map.set(key, g);
    });
    return Array.from(map.values());
  }, [reviewEntities]);

  // ── Scroll to entity in text panel — cycles through occurrences ──
  const scrollIndexRef = useRef<Map<string, number>>(new Map());
  const previewScrollRef = useRef<HTMLDivElement>(null);

  const scrollToEntityGroup = useCallback((ids: string[]) => {
    if (!ids.length) return;
    const key = ids.join(',');
    const prevIdx = scrollIndexRef.current.get(key) ?? -1;
    const nextIdx = (prevIdx + 1) % ids.length;
    scrollIndexRef.current.set(key, nextIdx);

    const targetId = ids[nextIdx];
    const el = reviewTextContentRef.current?.querySelector(`[data-review-entity-id="${CSS.escape(targetId)}"]`) as HTMLElement | null;
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-2', 'ring-primary');
      setTimeout(() => el.classList.remove('ring-2', 'ring-primary'), 1500);

      // Sync redacted preview scroll to same ratio
      const origScroll = reviewTextScrollRef.current;
      const prevScroll = previewScrollRef.current;
      if (origScroll && prevScroll) {
        const ratio = origScroll.scrollHeight > origScroll.clientHeight
          ? origScroll.scrollTop / (origScroll.scrollHeight - origScroll.clientHeight)
          : 0;
        prevScroll.scrollTop = ratio * (prevScroll.scrollHeight - prevScroll.clientHeight);
      }
    }
  }, [reviewTextContentRef, reviewTextScrollRef]);

  // ── Text selection annotation state ──
  const [selectedText, setSelectedText] = useState<{ text: string; start: number; end: number } | null>(null);
  const [selectionPos, setSelectionPos] = useState<{ left: number; top: number } | null>(null);
  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const selectionRangeRef = useRef<Range | null>(null);

  const clearTextSelection = useCallback(() => {
    setSelectedText(null);
    setSelectionPos(null);
    selectionRangeRef.current = null;
  }, []);

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

  const handleTextSelect = useCallback(() => {
    if (reviewFileReadOnly) return;

    const selection = window.getSelection();
    if (!selection || !reviewTextContentRef.current) {
      clearTextSelection();
      return;
    }

    if (selection.isCollapsed) {
      if (!selectedText || !selectionPos) clearTextSelection();
      return;
    }

    const text = selection.toString().trim();
    if (!text || text.length < 2) {
      clearTextSelection();
      return;
    }

    const range = selection.getRangeAt(0);
    if (!reviewTextContentRef.current.contains(range.commonAncestorContainer)) {
      clearTextSelection();
      return;
    }

    const offsets = getSelectionOffsets(range, reviewTextContentRef.current);
    const start = offsets?.start ?? reviewTextContent.indexOf(text);
    const end = offsets?.end ?? (start + text.length);
    if (start < 0 || end < 0) {
      clearTextSelection();
      return;
    }

    try {
      selectionRangeRef.current = range.cloneRange();
    } catch {
      clearTextSelection();
      return;
    }

    if (!selectedTypeId) {
      const fallbackType = textTypes[0]?.id;
      if (fallbackType) setSelectedTypeId(fallbackType);
    }

    setSelectionPos(null);
    setSelectedText({ text, start, end });
  }, [clearTextSelection, reviewFileReadOnly, reviewTextContent, reviewTextContentRef, selectedText, selectedTypeId, selectionPos, textTypes]);

  // Position the popover after selectedText changes (absolute within Card)
  useLayoutEffect(() => {
    if (!selectedText) {
      selectionRangeRef.current = null;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing position with DOM layout
      setSelectionPos(null);
      return;
    }

    const card = cardRef.current;
    if (!card) return;

    const update = () => {
      const range = selectionRangeRef.current;
      if (!range || range.collapsed) {
        setSelectionPos(null);
        return;
      }

      let rect: DOMRect;
      try {
        rect = range.getBoundingClientRect();
      } catch {
        setSelectionPos(null);
        return;
      }

      if (rect.width === 0 && rect.height === 0) return;

      const cardRect = card.getBoundingClientRect();
      // Clamp within the Card bounds (viewport coords), then convert to Card-relative
      const clamped = clampPopoverInCanvas(rect, cardRect, 240, 240);
      setSelectionPos({ left: clamped.left - cardRect.left, top: clamped.top - cardRect.top });
    };

    update();

    const scrollEl = reviewTextScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [selectedText, reviewTextScrollRef]);

  const addManualAnnotation = useCallback(() => {
    if (!selectedText || !selectedTypeId) return;
    const newEntity: ReviewEntity = {
      id: `manual_${Date.now()}`,
      text: selectedText.text,
      type: selectedTypeId,
      start: selectedText.start,
      end: selectedText.end,
      selected: true,
      source: 'manual',
      page: 0,
      confidence: 1,
    };
    applyReviewEntities(prev => [...prev, newEntity]);
    clearTextSelection();
    window.getSelection()?.removeAllRanges();
  }, [selectedText, selectedTypeId, applyReviewEntities, clearTextSelection]);

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
            // Dismiss entity popover on scroll to avoid stale positioning
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

        {/* Text selection annotation popover */}
        {selectedText && selectionPos && (
          <div
            className="absolute z-50 w-[220px] animate-in fade-in zoom-in-95 rounded-xl border border-border bg-popover shadow-lg"
            style={{ left: selectionPos.left, top: selectionPos.top }}
            onMouseDown={(e) => e.stopPropagation()}
            onMouseUp={(e) => e.stopPropagation()}
          >
            {/* Header: selected text + close */}
            <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
              <p className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                &ldquo;{selectedText.text}&rdquo;
              </p>
              <button
                type="button"
                onClick={clearTextSelection}
                className="ml-2 shrink-0 rounded-md p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><path d="M11.782 4.032a.575.575 0 10-.813-.814L7.5 6.687 4.032 3.218a.575.575 0 00-.814.814L6.687 7.5l-3.469 3.468a.575.575 0 00.814.814L7.5 8.313l3.469 3.469a.575.575 0 00.813-.814L8.313 7.5l3.469-3.468z" fill="currentColor"/></svg>
              </button>
            </div>

            {/* Type pills grid */}
            <div className="max-h-[180px] overflow-y-auto overscroll-contain px-1.5 py-1.5">
              <div className="grid grid-cols-2 gap-1">
                {textTypes.map((et) => {
                  const risk = getEntityRiskConfig(et.id);
                  const active = selectedTypeId === et.id;
                  return (
                    <button
                      key={et.id}
                      type="button"
                      onClick={() => setSelectedTypeId(et.id)}
                      className={cn(
                        'truncate rounded-lg px-2 py-1.5 text-left text-[11px] transition-colors',
                        active ? 'font-medium shadow-sm ring-1 ring-inset' : 'hover:bg-accent',
                      )}
                      style={active ? { backgroundColor: risk.bgColor, color: risk.textColor, '--tw-ring-color': risk.color } as React.CSSProperties : undefined}
                    >
                      {et.name ?? getEntityTypeName(et.id)}
                    </button>
                  );
                })}
                <button
                  type="button"
                  onClick={() => setSelectedTypeId('CUSTOM')}
                  className={cn(
                    'truncate rounded-lg px-2 py-1.5 text-left text-[11px] transition-colors',
                    selectedTypeId === 'CUSTOM' ? 'bg-muted font-medium shadow-sm ring-1 ring-inset ring-border' : 'hover:bg-accent',
                  )}
                >
                  {t('playground.customType')}
                </button>
              </div>
            </div>

            {/* Add button */}
            <div className="flex items-center gap-1.5 border-t border-border/60 px-3 py-2">
              <Button
                size="sm"
                onClick={addManualAnnotation}
                disabled={!selectedTypeId}
                className="h-7 flex-1 text-xs"
              >
                {t('playground.addAnnotation')}
              </Button>
            </div>
          </div>
        )}

        {/* Clicked entity popover — remove annotation */}
        {clickedEntity && entityPopupPos && (() => {
          const risk = getEntityRiskConfig(clickedEntity.type);
          return (
            <div
              className="absolute z-50 w-[220px] animate-in fade-in zoom-in-95 rounded-xl border border-border bg-popover p-3 shadow-lg"
              style={{ left: entityPopupPos.left, top: entityPopupPos.top }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className="inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
                    style={{ backgroundColor: risk.bgColor, color: risk.textColor }}
                  >
                    {getEntityTypeName(clickedEntity.type)}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">{clickedEntity.text}</span>
                </div>
                <button
                  type="button"
                  onClick={() => { setClickedEntity(null); setEntityPopupPos(null); }}
                  className="shrink-0 rounded-md p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <svg width="14" height="14" viewBox="0 0 15 15" fill="none"><path d="M11.782 4.032a.575.575 0 10-.813-.814L7.5 6.687 4.032 3.218a.575.575 0 00-.814.814L6.687 7.5l-3.469 3.468a.575.575 0 00.814.814L7.5 8.313l3.469 3.469a.575.575 0 00.813-.814L8.313 7.5l3.469-3.468z" fill="currentColor"/></svg>
                </button>
              </div>
              <Button size="sm" variant="ghost" onClick={removeClickedEntity} className="h-7 w-full text-xs text-destructive hover:bg-destructive/10 hover:text-destructive">
                {t('playground.removeAnnotation')}
              </Button>
            </div>
          );
        })()}
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
            )}
          </div>
        </div>
      </Card>

      {/* Entity list */}
      <Card className="min-h-0 flex flex-col overflow-hidden">
        <div className="shrink-0 px-3 py-2 border-b flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold">{t('batchWizard.step4.entityList')}</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground tabular-nums">
              {selectedReviewEntityCount}/{reviewEntities.length}
            </span>
            <Button
              variant="outline"
              size="sm"
              className="text-xs h-6"
              onClick={() => applyReviewEntities(prev => prev.map(e => ({ ...e, selected: true })))}
              data-testid="select-all-entities"
            >
              {t('batchWizard.step4.selectAll')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="text-xs h-6"
              onClick={() => applyReviewEntities(prev => prev.map(e => ({ ...e, selected: false })))}
              data-testid="deselect-all-entities"
            >
              {t('batchWizard.step4.deselectAll')}
            </Button>
          </div>
        </div>
        <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2">
          {entityGroups.map(g => {
            const risk = getEntityRiskConfig(g.type);
            const allSelected = g.selected === g.total;
            const noneSelected = g.selected === 0;
            return (
              <div
                key={`${g.type}::${g.text}`}
                className="rounded-xl border shadow-sm px-3 py-2 cursor-pointer transition-colors hover:bg-accent/30"
                style={{
                  backgroundColor: noneSelected ? undefined : risk.bgColor,
                  borderLeft: `3px solid ${risk.color}`,
                }}
                onClick={() => scrollToEntityGroup(g.ids)}
              >
                <div className="flex items-start gap-2">
                  <Checkbox
                    checked={allSelected ? true : noneSelected ? false : 'indeterminate'}
                    onCheckedChange={() => {
                      const newSelected = !allSelected;
                      applyReviewEntities(prev =>
                        prev.map(e => g.ids.includes(e.id) ? { ...e, selected: newSelected } : e),
                      );
                    }}
                    className="mt-0.5"
                    data-testid={`entity-group-toggle-${g.type}-${g.text}`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium" style={{ color: risk.textColor }}>
                        {textTypes.find(tt => tt.id === g.type)?.name ?? getEntityTypeName(g.type)}
                      </span>
                      {g.total > 1 && (
                        <Badge variant="secondary" className="rounded-full px-1.5 py-0 text-[10px] leading-4">
                          &times;{g.total}
                        </Badge>
                      )}
                    </div>
                    <span className="block text-xs break-all mt-0.5" style={{ color: risk.textColor }}>
                      {g.text}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
          {reviewEntities.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-6">
              {t('batchWizard.step4.noEntities')}
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}
