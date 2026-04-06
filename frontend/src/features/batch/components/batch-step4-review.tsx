
import type React from 'react';
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';

import { Checkbox } from '@/components/ui/checkbox';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import type { TextSegment } from '@/utils/textRedactionSegments';
import { tonePanelClass } from '@/utils/toneClasses';
import { getSelectionOffsets, clampPopoverInCanvas } from '@/utils/domSelection';
import type {
  BatchRow,
  PipelineCfg,
  ReviewEntity,
  TextEntityType,
} from '../types';

interface BatchStep4ReviewProps {

  doneRows: BatchRow[];
  reviewIndex: number;
  reviewFile: BatchRow | null;
  reviewLoading: boolean;
  reviewExecuteLoading: boolean;
  reviewFileReadOnly: boolean;
  navigateReviewIndex: (idx: number) => void;

  reviewEntities: ReviewEntity[];
  reviewTextContent: string;
  reviewTextContentRef: React.RefObject<HTMLDivElement | null>;
  reviewTextScrollRef: React.RefObject<HTMLDivElement | null>;
  selectedReviewEntityCount: number;
  displayPreviewMap: Record<string, string>;
  textPreviewSegments: TextSegment[];
  applyReviewEntities: (updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[])) => void;
  toggleReviewEntitySelected: (id: string) => void;

  reviewBoxes: EditorBox[];
  reviewOrigImageBlobUrl: string;
  reviewImagePreviewSrc: string;
  reviewImagePreviewLoading: boolean;
  selectedReviewBoxCount: number;
  pipelines: PipelineCfg[];
  textTypes: TextEntityType[];
  setReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>>;
  handleReviewBoxesCommit: (prev: EditorBox[], next: EditorBox[]) => void;
  toggleReviewBoxSelected: (id: string) => void;

  undoReviewText: () => void;
  redoReviewText: () => void;
  undoReviewImage: () => void;
  redoReviewImage: () => void;
  reviewTextUndoStack: ReviewEntity[][];
  reviewTextRedoStack: ReviewEntity[][];
  reviewImageUndoStack: EditorBox[][];
  reviewImageRedoStack: EditorBox[][];

  reviewDraftSaving: boolean;
  reviewDraftError: string | null;

  reviewedOutputCount: number;
  rows: BatchRow[];
  allReviewConfirmed: boolean;

  confirmCurrentReview: () => Promise<void>;
  advanceToExportStep: () => Promise<void>;
}

export function BatchStep4Review(props: BatchStep4ReviewProps) {
  const t = useT();
  const {
    doneRows, reviewIndex, reviewFile, reviewLoading, reviewExecuteLoading,
    reviewFileReadOnly, navigateReviewIndex,
    reviewDraftSaving, reviewDraftError,
    reviewedOutputCount, rows, allReviewConfirmed,
    confirmCurrentReview, advanceToExportStep,
  } = props;

  if (!doneRows.length) {
    return (
      <Card data-testid="batch-step4-empty">
        <CardContent className="p-6">
          <p className="text-sm text-muted-foreground">
            {t('batchWizard.step4.noRecognized')}
          </p>
        </CardContent>
      </Card>
    );
  }

  if (reviewLoading || !reviewFile) {
    return (
      <Card data-testid="batch-step4-loading">
        <CardContent className="p-6">
          <p className="text-sm text-muted-foreground">{t('batchWizard.step4.loading')}</p>
        </CardContent>
      </Card>
    );
  }

  const isImage = reviewFile.isImageMode === true;

  return (
    <Card
      className="flex-1 flex flex-col min-h-0 overflow-hidden"
      data-testid="batch-step4-review"
    >
      {reviewFileReadOnly && (
        <div className={`shrink-0 border-b px-4 py-2 text-sm ${tonePanelClass.success}`}>
          {t('batchWizard.step4.readOnlyHint')}
        </div>
      )}

      {/* Toolbar */}
      <div className="shrink-0 flex flex-wrap items-center gap-2 px-3 py-2 border-b bg-muted/30">
        <span className="text-xs font-semibold truncate max-w-[20rem]" title={reviewFile.original_filename}>
          {reviewFile.original_filename}
        </span>

        {doneRows.length > 1 && (
          <div className="flex items-center gap-1 border-l pl-2">
            <Button
              variant="outline"
              size="sm"
              disabled={reviewIndex <= 0}
              onClick={() => void navigateReviewIndex(reviewIndex - 1)}
              data-testid="review-prev"
            >
              {t('batchWizard.step4.prevFile')}
            </Button>
            <span className="text-xs text-muted-foreground tabular-nums">
              {reviewIndex + 1}/{doneRows.length}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={reviewIndex >= doneRows.length - 1}
              onClick={() => void navigateReviewIndex(reviewIndex + 1)}
              data-testid="review-next"
            >
              {t('batchWizard.step4.nextFile')}
            </Button>
          </div>
        )}

        {/* Undo/Redo */}
        <div className="flex items-center gap-1 border-l pl-2">
          <Button
            variant="outline"
            size="sm"
            onClick={isImage ? props.undoReviewImage : props.undoReviewText}
            disabled={isImage ? !props.reviewImageUndoStack.length : !props.reviewTextUndoStack.length}
          >
            {t('playground.undo')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={isImage ? props.redoReviewImage : props.redoReviewText}
            disabled={isImage ? !props.reviewImageRedoStack.length : !props.reviewTextRedoStack.length}
          >
            {t('playground.redo')}
          </Button>
        </div>

        {/* Draft status */}
        {reviewDraftSaving && (
          <span className="text-xs text-muted-foreground">{t('batchWizard.step4.savingDraft')}</span>
        )}
        {!reviewDraftSaving && reviewDraftError && (
          <span className="text-xs text-destructive truncate max-w-[10rem]">{reviewDraftError}</span>
        )}
        {!reviewDraftSaving && !reviewDraftError && (
          <span className="text-xs text-[var(--success-foreground)]">{t('batchWizard.step4.draftSynced')}</span>
        )}

        {/* Right actions */}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground tabular-nums">
            {t('batchWizard.step4.confirmed')} {reviewedOutputCount}/{rows.length}
          </span>
          <Button
            size="sm"
            onClick={() => void confirmCurrentReview()}
            disabled={reviewLoading || reviewExecuteLoading || reviewFileReadOnly}
            data-testid="confirm-redact"
          >
            {reviewFileReadOnly
              ? t('batchWizard.step4.completed')
              : reviewExecuteLoading
                ? t('batchWizard.step4.submitting')
                : t('batchWizard.step4.confirmRedact')}
          </Button>
          <Button
            size="sm"
            variant={allReviewConfirmed ? 'default' : 'outline'}
            disabled={!allReviewConfirmed || reviewExecuteLoading}
            onClick={() => void advanceToExportStep()}
            className={cn(allReviewConfirmed && 'bg-primary hover:bg-primary/90')}
            data-testid="go-export"
          >
            {t('batchWizard.step4.goExport')}
          </Button>
        </div>
      </div>

      {/* Content area */}
      {isImage ? (
        <ImageReviewContent {...props} />
      ) : (
        <TextReviewContent {...props} />
      )}
    </Card>
  );
}

// ── Image review sub-component ──
function ImageReviewContent(props: BatchStep4ReviewProps) {
  const t = useT();
  const {
    reviewBoxes, reviewOrigImageBlobUrl, reviewImagePreviewSrc,
    reviewImagePreviewLoading, selectedReviewBoxCount,
    pipelines, setReviewBoxes, handleReviewBoxesCommit, toggleReviewBoxSelected,
  } = props;

  const getVisionTypeMeta = (id: string) => {
    for (const p of pipelines) {
      const tt = p.types.find(x => x.id === id);
      if (tt) return { name: tt.name, color: '#6366F1' };
    }
    return { name: id, color: '#6366F1' };
  };

  return (
    <div className="flex-1 min-h-0 flex overflow-hidden">
      {/* Column 1: Original + bbox editor */}
      <div className="flex-[2] min-w-0 min-h-0 border-r flex flex-col">
        <div className="flex-1 min-h-0 relative">
          <div className="absolute inset-0">
            <ImageBBoxEditor
              imageSrc={reviewOrigImageBlobUrl}
              boxes={reviewBoxes}
              onBoxesChange={setReviewBoxes}
              onBoxesCommit={handleReviewBoxesCommit}
              getTypeConfig={getVisionTypeMeta}
              availableTypes={pipelines.flatMap(p => p.types.filter(tt => tt.enabled))}
              defaultType="CUSTOM"
            />
          </div>
        </div>
      </div>

      {/* Column 2: Redacted preview */}
      <div className="flex-[2] min-w-0 flex flex-col border-r overflow-hidden">
        <div className="shrink-0 flex items-center gap-1.5 px-2 py-1.5 border-b bg-muted/30">
          <span className="text-xs font-medium">{t('batchWizard.step4.previewImage')}</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {reviewImagePreviewLoading
              ? t('batchWizard.step4.generating')
              : `${selectedReviewBoxCount}/${reviewBoxes.length} ${t('batchWizard.step4.selected')}`}
          </span>
        </div>
        <div className="flex-1 min-h-0 overflow-auto bg-muted/20 flex items-center justify-center">
          {reviewImagePreviewSrc ? (
            <img src={reviewImagePreviewSrc} alt={t('batchWizard.step4.previewImage')} className="max-w-full max-h-full object-contain" />
          ) : (
            <p className="text-sm text-muted-foreground">
              {reviewImagePreviewLoading ? t('batchWizard.step4.generating') : t('batchWizard.step4.noBoxes')}
            </p>
          )}
        </div>
      </div>

      {/* Column 3: Detection list */}
      <div className="flex-[1] min-w-[220px] max-w-[320px] min-h-0 flex flex-col bg-background">
        <div className="shrink-0 flex items-center px-2 py-1.5 border-b">
          <span className="text-xs font-medium">{t('batchWizard.step4.detectionRegions')}</span>
          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            {selectedReviewBoxCount}/{reviewBoxes.length}
          </span>
        </div>
        <div className="flex flex-1 flex-col gap-1.5 overflow-y-auto p-2">
          {reviewBoxes.map(box => {
            const meta = getVisionTypeMeta(box.type);
            return (
              <button
                key={box.id}
                type="button"
                onClick={() => toggleReviewBoxSelected(box.id)}
                className="w-full text-left rounded-lg border px-2.5 py-1.5 transition hover:border-muted-foreground/40"
                style={{
                  borderColor: box.selected !== false ? meta.color : undefined,
                  backgroundColor: box.selected === false ? undefined : `${meta.color}0d`,
                }}
                data-testid={`bbox-toggle-${box.id}`}
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={box.selected !== false}
                    onCheckedChange={() => toggleReviewBoxSelected(box.id)}
                  />
                  <span className="text-xs font-medium truncate" style={{ color: meta.color }}>
                    {meta.name}
                  </span>
                  <span className="text-xs text-muted-foreground ml-auto shrink-0">
                    {Math.round(box.width * 100)}&times;{Math.round(box.height * 100)}%
                  </span>
                </div>
                {box.text && (
                  <p className="mt-0.5 text-xs text-muted-foreground truncate pl-6">{box.text}</p>
                )}
              </button>
            );
          })}
          {reviewBoxes.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-8">
              {t('batchWizard.step4.noBoxes')}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Text review sub-component ──
function TextReviewContent(props: BatchStep4ReviewProps) {
  const t = useT();
  const {
    reviewEntities, reviewTextContent, reviewTextContentRef, reviewTextScrollRef,
    selectedReviewEntityCount, displayPreviewMap, textPreviewSegments,
    applyReviewEntities, toggleReviewEntitySelected, textTypes,
    reviewFileReadOnly,
  } = props;

  const cardRef = useRef<HTMLDivElement | null>(null);

  // ── Grouped entity list (Issue 4) ──
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
  }, [reviewTextContentRef]);

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
          onClick={() => toggleReviewEntitySelected(entity.id)}
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
