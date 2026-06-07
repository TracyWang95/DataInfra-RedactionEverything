// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { tonePanelClass } from '@/utils/toneClasses';

import { useBatchWizardContext } from '../batch-wizard-context';
import { getNextRequiredReviewPageTarget, getNextReviewIndex } from '../lib/review-navigation';
import { RECOGNITION_DONE_STATUSES, type BatchRow } from '../types';
import { ReviewImageContent } from './review-image-content';
import { ReviewTextContent } from './review-text-content';

function ReviewContentLoading() {
  const t = useT();

  return (
    <div
      className="flex min-h-[420px] flex-1 items-center justify-center bg-background p-6"
      data-testid="batch-step4-content-loading"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <div className="flex min-w-0 flex-col items-center gap-3 text-center">
        <span className="size-6 animate-spin rounded-full border-2 border-border border-t-primary" />
        <div className="space-y-1">
          <p className="text-sm font-semibold text-foreground">
            {t('batchWizard.step4.loadingReviewTitle')}
          </p>
          <p className="max-w-md text-xs leading-5 text-muted-foreground">
            {t('batchWizard.step4.loadingReviewHint')}
          </p>
        </div>
      </div>
    </div>
  );
}

function statusLabel(t: (key: string) => string, status: BatchRow['analyzeStatus']) {
  switch (status) {
    case 'pending':
      return t('batchWizard.status.pending');
    case 'parsing':
      return t('batchWizard.status.parsing');
    case 'analyzing':
      return t('batchWizard.status.analyzing');
    case 'awaiting_review':
      return t('batchWizard.status.awaitingReview');
    case 'review_approved':
      return t('batchWizard.status.reviewApproved');
    case 'redacting':
      return t('batchWizard.status.redacting');
    case 'completed':
      return t('batchWizard.status.completed');
    case 'failed':
      return t('batchWizard.status.failed');
    default:
      return status;
  }
}

function formatReadyProgress(t: (key: string) => string, ready: number, total: number) {
  return t('batchWizard.step4.reviewableProgress')
    .replace('{ready}', String(ready))
    .replace('{total}', String(total));
}

function formatWaitingProgress(t: (key: string) => string, ready: number, total: number) {
  return t('batchWizard.step4.waitingForBackground')
    .replace('{ready}', String(ready))
    .replace('{total}', String(total));
}

function rowRecognitionProgress(row: BatchRow) {
  const current = Number(row.recognitionCurrent ?? 0);
  const total = Number(row.recognitionTotal ?? 0);
  if (!Number.isFinite(current) || !Number.isFinite(total) || total <= 0) return null;
  return `${Math.min(Math.max(0, current), total)}/${total}`;
}

function ReviewQueueStatus({
  rows,
  doneRows,
  testId = 'review-queue-status',
}: {
  rows: BatchRow[];
  doneRows: BatchRow[];
  testId?: string;
}) {
  const t = useT();
  const waitingRows = rows.filter((row) => !RECOGNITION_DONE_STATUSES.has(row.analyzeStatus));
  const activeRecognitionRows = waitingRows.filter((row) => row.analyzeStatus !== 'failed');
  const backgroundRecognitionRunning = activeRecognitionRows.length > 0;
  const visibleWaitingRows = waitingRows.slice(0, 3);
  const hiddenWaitingCount = Math.max(0, waitingRows.length - visibleWaitingRows.length);

  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground"
      data-testid={testId}
      role={backgroundRecognitionRunning ? 'status' : undefined}
      aria-live={backgroundRecognitionRunning ? 'polite' : undefined}
    >
      <span className="shrink-0 font-medium text-foreground">
        {formatReadyProgress(t, doneRows.length, rows.length)}
      </span>
      {backgroundRecognitionRunning && (
        <span
          className="inline-flex shrink-0 items-center gap-1 font-medium text-foreground"
          data-testid={`${testId}-background`}
        >
          <span className="size-2 rounded-full bg-primary" />
          {t('batchWizard.step4.backgroundRecognitionRunning')}
        </span>
      )}
      {visibleWaitingRows.map((row) => {
        const progress = rowRecognitionProgress(row);
        return (
          <span key={row.file_id} className="inline-flex min-w-0 max-w-56 items-center gap-1">
            <span className="min-w-0 truncate" title={row.original_filename}>
              {row.original_filename}
            </span>
            <Badge
              variant={row.analyzeStatus === 'failed' ? 'destructive' : 'outline'}
              className="shrink-0 whitespace-nowrap text-[11px]"
            >
              {statusLabel(t, row.analyzeStatus)}
            </Badge>
            {progress && (
              <span className="shrink-0 whitespace-nowrap tabular-nums">{progress}</span>
            )}
          </span>
        );
      })}
      {hiddenWaitingCount > 0 && (
        <span className="shrink-0 tabular-nums">+{hiddenWaitingCount}</span>
      )}
      {backgroundRecognitionRunning && (
        <span
          className="min-w-40 flex-1 truncate text-muted-foreground/80"
          data-testid={`${testId}-background-hint`}
          title={t('batchWizard.step4.backgroundRecognitionHint')}
        >
          {t('batchWizard.step4.backgroundRecognitionHint')}
        </span>
      )}
    </div>
  );
}

export function BatchStep4Review() {
  const t = useT();
  const w = useBatchWizardContext();

  const {
    doneRows,
    reviewIndex,
    reviewFile,
    reviewLoading,
    reviewLoadError,
    reviewExecuteLoading,
    reviewFileReadOnly,
    reviewTotalPages,
    reviewPageSummaries,
    reviewRequiredPagesVisited,
    visitedReviewPagesCount,
    reviewRequiredPageCount,
    reviewUnvisitedRequiredPageCount,
    navigateReviewIndex,
    reviewDraftSaving,
    reviewDraftError,
    reviewedOutputCount,
    rows,
    canAdvanceToExport,
    confirmCurrentReview,
    advanceToExportStep,
    loadReviewData,
    rerunCurrentItemRecognition: onRerunRecognition,
    rerunRecognitionLoading,
  } = w;

  if (!doneRows.length) {
    return (
      <Card
        className="page-surface border-border/70 shadow-[var(--shadow-control)]"
        data-testid="batch-step4-empty"
      >
        <CardContent className="space-y-3 p-6">
          <p className="text-sm text-muted-foreground">{t('batchWizard.step4.noRecognized')}</p>
          {rows.length > 0 && (
            <ReviewQueueStatus rows={rows} doneRows={doneRows} testId="review-waiting-status" />
          )}
        </CardContent>
      </Card>
    );
  }

  if (!reviewFile) {
    return (
      <Card
        className="page-surface flex min-h-0 flex-1 flex-col overflow-hidden border-border/70 shadow-[var(--shadow-control)]"
        data-testid="batch-step4-loading"
      >
        <CardContent className="flex min-h-0 flex-1 p-0">
          <ReviewContentLoading />
        </CardContent>
      </Card>
    );
  }

  if (reviewLoadError) {
    return (
      <Card
        className="page-surface border-border/70 shadow-[var(--shadow-control)]"
        data-testid="batch-step4-load-error"
      >
        <CardContent className="space-y-4 p-6">
          <div className={`rounded-xl border px-4 py-3 ${tonePanelClass.danger}`}>
            <p className="text-sm font-semibold">{t('batchWizard.step4.loadFailedTitle')}</p>
            <p className="mt-1 text-sm leading-6">{reviewLoadError}</p>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs leading-5 text-muted-foreground">
              {t('batchWizard.step4.loadFailedAction')}
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() =>
                void loadReviewData(reviewFile.file_id, reviewFile.isImageMode === true)
              }
              data-testid="retry-review-load"
            >
              {t('common.retry')}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const isImage = reviewFile.isImageMode === true;
  const unfinishedRows = rows.filter((row) => !RECOGNITION_DONE_STATUSES.has(row.analyzeStatus));
  const activeBackgroundRows = unfinishedRows.filter((row) => row.analyzeStatus !== 'failed');
  const waitingForBackgroundRecognition = activeBackgroundRows.length > 0;
  const nextReviewIndex = getNextReviewIndex(doneRows, reviewIndex, reviewFile.file_id);
  const nextRequiredPageTarget = getNextRequiredReviewPageTarget(
    reviewPageSummaries,
    w.reviewCurrentPage,
  );
  const nextUnvisitedRequiredPage = nextRequiredPageTarget?.page.page;
  const nextReviewBlockedByCurrent =
    reviewFile.reviewConfirmed !== true && !reviewFileReadOnly;
  const canNavigateNextReview =
    nextReviewIndex !== null &&
    !reviewLoading &&
    !reviewExecuteLoading &&
    !nextReviewBlockedByCurrent;

  return (
    <Card
      className="page-surface flex min-h-0 flex-1 flex-col overflow-hidden border-border/70 shadow-[var(--shadow-control)]"
      data-testid="batch-step4-review"
    >
      {reviewFileReadOnly && (
        <div className={`shrink-0 border-b px-4 py-2 text-sm ${tonePanelClass.success}`}>
          {t('batchWizard.step4.readOnlyHint')}
        </div>
      )}

      <div className="shrink-0 border-b bg-muted/30 px-3 py-2" data-testid="review-file-toolbar">
        <div className="flex min-w-0 flex-nowrap items-center gap-2 overflow-x-auto pb-0.5">
          <div className="min-w-0 flex-1">
            <span
              className="block truncate text-xs font-semibold"
              title={reviewFile.original_filename}
            >
              {reviewFile.original_filename}
            </span>
          </div>

          {doneRows.length > 1 && (
            <div className="flex shrink-0 items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                className="h-8 whitespace-nowrap"
                disabled={reviewIndex <= 0}
                onClick={() => void navigateReviewIndex(reviewIndex - 1)}
                data-testid="review-prev"
              >
                {t('batchWizard.step4.prevFile')}
              </Button>
              <span className="min-w-12 text-center text-xs text-muted-foreground tabular-nums">
                {reviewIndex + 1}/{doneRows.length}
              </span>
              <Button
                variant="outline"
                size="sm"
                className="h-8 whitespace-nowrap"
                disabled={!canNavigateNextReview}
                title={
                  nextReviewBlockedByCurrent
                    ? reviewRequiredPagesVisited
                      ? t('batchWizard.step4.confirmRedact')
                      : t('batchWizard.step4.mustVisitRequiredPages')
                    : undefined
                }
                onClick={() => {
                  if (nextReviewIndex !== null && canNavigateNextReview) {
                    void navigateReviewIndex(nextReviewIndex);
                  }
                }}
                data-testid="review-next"
              >
                {t('batchWizard.step4.nextFile')}
              </Button>
            </div>
          )}

          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              className="h-8 whitespace-nowrap"
              onClick={isImage ? w.undoReviewImage : w.undoReviewText}
              disabled={isImage ? !w.reviewImageUndoStack.length : !w.reviewTextUndoStack.length}
            >
              {t('playground.undo')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-8 whitespace-nowrap"
              onClick={isImage ? w.redoReviewImage : w.redoReviewText}
              disabled={isImage ? !w.reviewImageRedoStack.length : !w.reviewTextRedoStack.length}
            >
              {t('playground.redo')}
            </Button>
          </div>

          {onRerunRecognition && (
            <Button
              variant="outline"
              size="sm"
              className="h-8 shrink-0 whitespace-nowrap text-xs"
              disabled={reviewFileReadOnly || reviewLoading || rerunRecognitionLoading}
              onClick={() => void onRerunRecognition()}
              data-testid="rerun-recognition"
            >
              {rerunRecognitionLoading
                ? t('batchWizard.step4.rerunningRecognition')
                : t('batchWizard.step4.rerunRecognition')}
            </Button>
          )}

          <div className="min-w-28 shrink-0 text-right">
            {reviewDraftSaving && (
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                {t('batchWizard.step4.savingDraft')}
              </span>
            )}
            {!reviewDraftSaving && reviewDraftError && (
              <span className="block truncate text-xs text-destructive" title={reviewDraftError}>
                {reviewDraftError}
              </span>
            )}
            {!reviewDraftSaving && !reviewDraftError && (
              <span className="whitespace-nowrap text-xs text-[var(--success-foreground)]">
                {t('batchWizard.step4.draftSynced')}
              </span>
            )}
          </div>
        </div>
      </div>

      {unfinishedRows.length > 0 && (
        <div
          className="shrink-0 border-b bg-muted/20 px-3 py-1.5"
          data-testid="review-unfinished-status"
        >
          <ReviewQueueStatus rows={rows} doneRows={doneRows} />
        </div>
      )}

      {reviewLoading ? (
        <ReviewContentLoading />
      ) : isImage ? (
        <ReviewImageContent
          reviewBoxes={w.reviewBoxes}
          visibleReviewBoxes={w.visibleReviewBoxes}
          reviewOrigImageBlobUrl={w.reviewOrigImageBlobUrl}
          reviewImagePreviewSrc={w.reviewImagePreviewSrc}
          reviewImagePreviewLoading={w.reviewImagePreviewLoading}
          reviewCurrentPage={w.reviewCurrentPage}
          reviewTotalPages={w.reviewTotalPages}
          selectedReviewBoxCount={w.selectedReviewBoxCount}
          totalReviewBoxCount={w.totalReviewBoxCount}
          currentReviewVisionQuality={w.currentReviewVisionQuality}
          pipelines={w.pipelines}
          onReviewPageChange={w.setReviewCurrentPage}
          setVisibleReviewBoxes={w.setVisibleReviewBoxes}
          handleReviewBoxesCommit={w.handleReviewBoxesCommit}
          toggleReviewBoxSelected={w.toggleReviewBoxSelected}
        />
      ) : (
        <ReviewTextContent
          reviewEntities={w.reviewEntities}
          visibleReviewEntities={w.visibleReviewEntities}
          reviewTextContent={w.reviewTextContent}
          reviewPageContent={w.reviewPageContent}
          reviewTextContentRef={w.reviewTextContentRef}
          reviewTextScrollRef={w.reviewTextScrollRef}
          selectedReviewEntityCount={w.selectedReviewEntityCount}
          reviewCurrentPage={w.reviewCurrentPage}
          reviewTotalPages={w.reviewTotalPages}
          onReviewPageChange={w.setReviewCurrentPage}
          displayPreviewMap={w.displayPreviewMap}
          textPreviewSegments={w.textPreviewSegments}
          applyReviewEntities={w.applyReviewEntities}
          textTypes={w.textTypes}
          reviewFileReadOnly={w.reviewFileReadOnly}
        />
      )}

      <div
        className="sticky bottom-0 z-10 shrink-0 border-t bg-background/95 px-3 py-2 backdrop-blur-xl"
        data-testid="review-action-bar"
      >
        <div className="flex flex-wrap items-center justify-end gap-2">
          {((reviewTotalPages > 1 && !reviewFileReadOnly) || waitingForBackgroundRecognition) && (
            <div className="mr-auto flex min-w-[14rem] flex-1 flex-wrap items-center gap-x-3 gap-y-1">
              {reviewTotalPages > 1 && !reviewFileReadOnly && (
                <span
                  className={cn(
                    'shrink truncate text-xs tabular-nums',
                    reviewRequiredPagesVisited
                      ? 'text-[var(--success-foreground)]'
                      : 'text-muted-foreground',
                  )}
                  title={t('batchWizard.step4.pagesVisitedHint')}
                >
                  {reviewRequiredPageCount > 0
                    ? `${t('batchWizard.step4.requiredPagesVisited')} ${
                        reviewRequiredPageCount - reviewUnvisitedRequiredPageCount
                      }/${reviewRequiredPageCount}`
                    : `${t('batchWizard.step4.pagesVisited')} ${visitedReviewPagesCount}/${reviewTotalPages}`}
                </span>
              )}
              {waitingForBackgroundRecognition && (
                <span
                  className="shrink truncate text-xs text-muted-foreground tabular-nums"
                  data-testid="review-background-wait"
                  title={t('batchWizard.step4.backgroundRecognitionHint')}
                >
                  {formatWaitingProgress(t, doneRows.length, rows.length)}
                </span>
              )}
            </div>
          )}
          <span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground tabular-nums">
            {t('batchWizard.step4.confirmed')} {reviewedOutputCount}/{rows.length}
          </span>
          {reviewTotalPages > 1 &&
            !reviewFileReadOnly &&
            !reviewRequiredPagesVisited &&
            nextUnvisitedRequiredPage !== undefined && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="shrink-0 whitespace-nowrap"
                disabled={reviewLoading || reviewExecuteLoading}
                onClick={() => w.setReviewCurrentPage(nextUnvisitedRequiredPage)}
                data-testid="review-next-required-page"
              >
                {t('batchWizard.step4.nextUnvisitedPage')}
              </Button>
            )}
          <Button
            size="sm"
            className="shrink-0 whitespace-nowrap"
            onClick={() => void confirmCurrentReview()}
            disabled={
              reviewLoading ||
              reviewDraftSaving ||
              reviewExecuteLoading ||
              reviewFileReadOnly ||
              !reviewRequiredPagesVisited
            }
            title={
              !reviewRequiredPagesVisited && !reviewFileReadOnly
                ? t('batchWizard.step4.mustVisitRequiredPages')
                : undefined
            }
            data-testid="confirm-redact"
          >
            {reviewExecuteLoading
              ? t('batchWizard.step4.submitting')
              : reviewFileReadOnly
                ? t('batchWizard.step4.completed')
                : t('batchWizard.step4.confirmRedact')}
          </Button>
          <Button
            size="sm"
            variant={canAdvanceToExport ? 'default' : 'outline'}
            disabled={
              !canAdvanceToExport || reviewLoading || reviewDraftSaving || reviewExecuteLoading
            }
            title={
              waitingForBackgroundRecognition && !canAdvanceToExport
                ? t('batchWizard.step4.backgroundRecognitionHint')
                : undefined
            }
            onClick={() => void advanceToExportStep()}
            className={cn(
              'shrink-0 whitespace-nowrap',
              canAdvanceToExport && 'bg-primary hover:bg-primary/90',
            )}
            data-testid="go-export"
          >
            {t('batchWizard.step4.goExport')}
          </Button>
        </div>
      </div>
    </Card>
  );
}
