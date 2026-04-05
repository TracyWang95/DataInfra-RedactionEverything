/**
 * BatchStep4Review — Step 4: Review & confirm redaction.
 * Supports both text entity review and image bbox review modes.
 * Delegates to the parent hook for all state management.
 */
import type React from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
// Badge available for future use
import { Checkbox } from '@/components/ui/checkbox';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import type { TextSegment } from '@/utils/textRedactionSegments';
import { tonePanelClass } from '@/utils/toneClasses';
import type {
  BatchRow,
  ReviewEntity,
  PipelineCfg,
  TextEntityType,
} from '../hooks/use-batch-wizard';

interface BatchStep4ReviewProps {
  // Review navigation
  doneRows: BatchRow[];
  reviewIndex: number;
  reviewFile: BatchRow | null;
  reviewLoading: boolean;
  reviewExecuteLoading: boolean;
  reviewFileReadOnly: boolean;
  navigateReviewIndex: (idx: number) => void;

  // Text review
  reviewEntities: ReviewEntity[];
  reviewTextContent: string;
  reviewTextContentRef: React.RefObject<HTMLDivElement | null>;
  reviewTextScrollRef: React.RefObject<HTMLDivElement | null>;
  selectedReviewEntityCount: number;
  displayPreviewMap: Record<string, string>;
  textPreviewSegments: TextSegment[];
  applyReviewEntities: (updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[])) => void;
  toggleReviewEntitySelected: (id: string) => void;

  // Image review
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

  // Undo/redo
  undoReviewText: () => void;
  redoReviewText: () => void;
  undoReviewImage: () => void;
  redoReviewImage: () => void;
  reviewTextUndoStack: ReviewEntity[][];
  reviewTextRedoStack: ReviewEntity[][];
  reviewImageUndoStack: EditorBox[][];
  reviewImageRedoStack: EditorBox[][];

  // Draft
  reviewDraftSaving: boolean;
  reviewDraftError: string | null;

  // Counts
  reviewedOutputCount: number;
  rows: BatchRow[];
  allReviewConfirmed: boolean;

  // Actions
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
      {/* Read-only banner */}
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
        <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
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
  } = props;

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
        <span
          key={entity.id}
          data-review-entity-id={entity.id}
          className="cursor-pointer transition-all inline-flex items-center gap-0.5 rounded px-0.5 -mx-0.5 hover:ring-2 hover:ring-offset-1 hover:ring-blue-400/20"
          style={{ backgroundColor: risk.bgColor, color: risk.textColor, opacity: entity.selected ? 1 : 0.45 }}
          title={`${getEntityTypeName(entity.type)}`}
        >
          {reviewTextContent.slice(entity.start, entity.end)}
        </span>,
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
      <Card className="min-h-0 flex flex-col overflow-hidden">
        <div className="shrink-0 px-4 py-2 border-b flex items-center justify-between">
          <span className="text-xs font-semibold">{t('batchWizard.step4.originalText')}</span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {t('batchWizard.step4.selected')} {selectedReviewEntityCount}/{reviewEntities.length}
          </span>
        </div>
        <div ref={reviewTextScrollRef} className="flex-1 overflow-auto p-4">
          <div
            ref={reviewTextContentRef}
            className="text-sm leading-relaxed whitespace-pre-wrap font-[system-ui]"
          >
            {renderMarkedContent()}
          </div>
        </div>
      </Card>

      {/* Redacted preview */}
      <Card className="min-h-0 flex flex-col overflow-hidden">
        <div className="shrink-0 px-4 py-2 border-b">
          <span className="text-xs font-semibold">{t('batchWizard.step4.redactedPreview')}</span>
        </div>
        <div className="flex-1 overflow-auto p-4">
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
        <div className="flex-1 overflow-y-auto p-2 space-y-2">
          {reviewEntities.map(e => {
            const repl = displayPreviewMap[e.text] ?? (
              typeof e.start === 'number' && typeof e.end === 'number' && e.end <= reviewTextContent.length
                ? displayPreviewMap[reviewTextContent.slice(e.start, e.end)]
                : undefined
            );
            const risk = getEntityRiskConfig(e.type);
            return (
              <div
                key={e.id}
                className="rounded-xl border shadow-sm px-3 py-2"
                style={{
                  backgroundColor: e.selected === false ? undefined : risk.bgColor,
                  borderLeft: `3px solid ${risk.color}`,
                }}
              >
                <div className="flex items-start gap-2">
                  <Checkbox
                    checked={e.selected !== false}
                    onCheckedChange={() => toggleReviewEntitySelected(e.id)}
                    className="mt-0.5"
                    data-testid={`entity-toggle-${e.id}`}
                  />
                  <div className="min-w-0 flex-1">
                    <span className="text-xs font-medium" style={{ color: risk.textColor }}>
                      {textTypes.find(tt => tt.id === e.type)?.name ?? getEntityTypeName(e.type)}
                    </span>
                    <span className="block text-xs break-all mt-0.5" style={{ color: risk.textColor }}>
                      {e.text}
                    </span>
                    {repl != null && (
                      <span className="block text-xs mt-0.5 truncate opacity-90" style={{ color: risk.textColor }}>
                        {repl}
                      </span>
                    )}
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
