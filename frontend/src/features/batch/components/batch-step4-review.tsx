// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { tonePanelClass } from '@/utils/toneClasses';

import { useBatchWizardContext } from '../batch-wizard-context';
import { ReviewImageContent } from './review-image-content';
import { ReviewTextContent } from './review-text-content';

export function BatchStep4Review() {
  const t = useT();
  const w = useBatchWizardContext();

  const {
    doneRows, reviewIndex, reviewFile, reviewLoading, reviewExecuteLoading,
    reviewFileReadOnly, navigateReviewIndex,
    reviewDraftSaving, reviewDraftError,
    reviewedOutputCount, rows, allReviewConfirmed,
    confirmCurrentReview, advanceToExportStep,
    rerunCurrentItemRecognition: onRerunRecognition,
    rerunRecognitionLoading,
  } = w;

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
            onClick={isImage ? w.undoReviewImage : w.undoReviewText}
            disabled={isImage ? !w.reviewImageUndoStack.length : !w.reviewTextUndoStack.length}
          >
            {t('playground.undo')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={isImage ? w.redoReviewImage : w.redoReviewText}
            disabled={isImage ? !w.reviewImageRedoStack.length : !w.reviewTextRedoStack.length}
          >
            {t('playground.redo')}
          </Button>
        </div>

        {/* Re-run recognition */}
        {onRerunRecognition && (
          <div className="flex items-center border-l pl-2">
            <Button
              variant="outline"
              size="sm"
              className="h-6 text-xs"
              disabled={reviewFileReadOnly || reviewLoading || rerunRecognitionLoading}
              onClick={() => void onRerunRecognition()}
              data-testid="rerun-recognition"
            >
              {rerunRecognitionLoading
                ? t('batchWizard.step4.rerunningRecognition')
                : t('batchWizard.step4.rerunRecognition')}
            </Button>
          </div>
        )}

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
        <ReviewImageContent
          reviewBoxes={w.reviewBoxes}
          reviewOrigImageBlobUrl={w.reviewOrigImageBlobUrl}
          reviewImagePreviewSrc={w.reviewImagePreviewSrc}
          reviewImagePreviewLoading={w.reviewImagePreviewLoading}
          selectedReviewBoxCount={w.selectedReviewBoxCount}
          pipelines={w.pipelines}
          setReviewBoxes={w.setReviewBoxes}
          handleReviewBoxesCommit={w.handleReviewBoxesCommit}
          toggleReviewBoxSelected={w.toggleReviewBoxSelected}
        />
      ) : (
        <ReviewTextContent
          reviewEntities={w.reviewEntities}
          reviewTextContent={w.reviewTextContent}
          reviewTextContentRef={w.reviewTextContentRef}
          reviewTextScrollRef={w.reviewTextScrollRef}
          selectedReviewEntityCount={w.selectedReviewEntityCount}
          displayPreviewMap={w.displayPreviewMap}
          textPreviewSegments={w.textPreviewSegments}
          applyReviewEntities={w.applyReviewEntities}
          textTypes={w.textTypes}
          reviewFileReadOnly={w.reviewFileReadOnly}
        />
      )}
    </Card>
  );
}
