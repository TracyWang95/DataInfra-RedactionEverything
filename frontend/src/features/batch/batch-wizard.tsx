
import { Navigate } from 'react-router-dom';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useBatchWizard } from './hooks/use-batch-wizard';
import { BatchStepProgress } from './components/batch-step-progress';
import { BatchStep1Config } from './components/batch-step1-config';
import { BatchStep2Upload } from './components/batch-step2-upload';
import { BatchStep3Recognize } from './components/batch-step3-recognize';
import { BatchStep4Review } from './components/batch-step4-review';
import { BatchStep5Export } from './components/batch-step5-export';

export function BatchWizard() {
  const t = useT();
  const w = useBatchWizard();

  if (!w.modeValid) {
    return <Navigate to="/batch" replace />;
  }

  const msgVariant =
    w.msg?.tone === 'ok' ? 'default' as const
    : w.msg?.tone === 'err' || w.msg?.tone === 'warn' ? 'destructive' as const
    : 'default' as const;

  return (
    <div
      className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background"
      data-testid="batch-wizard"
    >
      <div
        className={cn(
          'flex min-h-0 min-w-0 flex-1 flex-col',
          w.step === 1
            ? 'page-shell-narrow !max-w-[88rem] 2xl:!max-w-[96rem] overflow-hidden'
            : w.step === 4
              ? 'page-shell overflow-hidden'
              : 'page-shell-narrow !max-w-[92rem] 2xl:!max-w-[100rem] overflow-y-auto overscroll-contain',
        )}
      >
        {w.previewMode && (
          <Alert className="mb-3">
            <AlertDescription>{t('batchWizard.previewBanner')}</AlertDescription>
          </Alert>
        )}

        {w.step !== 4 && (
          <p className="mb-1 shrink-0 text-xs leading-tight text-muted-foreground">
            {t('batchWizard.stepsOverview')}
          </p>
        )}

        <BatchStepProgress
          currentStep={w.step}
          canGoStep={w.canGoStep}
          onStepClick={w.goStep}
        />

        {w.msg && (
          <Alert variant={msgVariant} className="mb-2">
            <AlertDescription>{w.msg.text}</AlertDescription>
          </Alert>
        )}

        {w.step === 1 && (
          <BatchStep1Config
            cfg={w.cfg}
            setCfg={w.setCfg}
            configLoaded={w.configLoaded}
            textTypes={w.textTypes}
            pipelines={w.pipelines}
            textPresets={w.textPresets}
            visionPresets={w.visionPresets}
            onBatchTextPresetChange={w.onBatchTextPresetChange}
            onBatchVisionPresetChange={w.onBatchVisionPresetChange}
            confirmStep1={w.confirmStep1}
            setConfirmStep1={w.setConfirmStep1}
            isStep1Complete={w.isStep1Complete}
            jobPriority={w.jobPriority}
            setJobPriority={w.setJobPriority}
            advanceToUploadStep={w.advanceToUploadStep}
          />
        )}

        {w.step === 2 && (
          <BatchStep2Upload
            mode={w.mode}
            activeJobId={w.activeJobId}
            rows={w.rows}
            loading={w.loading}
            isDragActive={w.isDragActive}
            getRootProps={w.getRootProps}
            getInputProps={w.getInputProps}
            goStep={w.goStep}
          />
        )}

        {w.step === 3 && (
          <BatchStep3Recognize
            rows={w.rows}
            activeJobId={w.activeJobId}
            failedRows={w.failedRows}
            goStep={w.goStep}
            submitQueueToWorker={w.submitQueueToWorker}
            requeueFailedItems={w.requeueFailedItems}
          />
        )}

        {}
        {w.step === 4 && (
          <BatchStep4Review
            doneRows={w.doneRows}
            reviewIndex={w.reviewIndex}
            reviewFile={w.reviewFile}
            reviewLoading={w.reviewLoading}
            reviewExecuteLoading={w.reviewExecuteLoading}
            reviewFileReadOnly={w.reviewFileReadOnly}
            navigateReviewIndex={w.navigateReviewIndex}
            reviewEntities={w.reviewEntities}
            reviewTextContent={w.reviewTextContent}
            reviewTextContentRef={w.reviewTextContentRef}
            reviewTextScrollRef={w.reviewTextScrollRef}
            selectedReviewEntityCount={w.selectedReviewEntityCount}
            displayPreviewMap={w.displayPreviewMap}
            textPreviewSegments={w.textPreviewSegments}
            applyReviewEntities={w.applyReviewEntities}
            toggleReviewEntitySelected={w.toggleReviewEntitySelected}
            reviewBoxes={w.reviewBoxes}
            reviewOrigImageBlobUrl={w.reviewOrigImageBlobUrl}
            reviewImagePreviewSrc={w.reviewImagePreviewSrc}
            reviewImagePreviewLoading={w.reviewImagePreviewLoading}
            selectedReviewBoxCount={w.selectedReviewBoxCount}
            pipelines={w.pipelines}
            textTypes={w.textTypes}
            setReviewBoxes={w.setReviewBoxes}
            handleReviewBoxesCommit={w.handleReviewBoxesCommit}
            toggleReviewBoxSelected={w.toggleReviewBoxSelected}
            undoReviewText={w.undoReviewText}
            redoReviewText={w.redoReviewText}
            undoReviewImage={w.undoReviewImage}
            redoReviewImage={w.redoReviewImage}
            reviewTextUndoStack={w.reviewTextUndoStack}
            reviewTextRedoStack={w.reviewTextRedoStack}
            reviewImageUndoStack={w.reviewImageUndoStack}
            reviewImageRedoStack={w.reviewImageRedoStack}
            reviewDraftSaving={w.reviewDraftSaving}
            reviewDraftError={w.reviewDraftError}
            reviewedOutputCount={w.reviewedOutputCount}
            rows={w.rows}
            allReviewConfirmed={w.allReviewConfirmed}
            confirmCurrentReview={w.confirmCurrentReview}
            advanceToExportStep={w.advanceToExportStep}
          />
        )}

        {}
        {w.step === 5 && (
          <BatchStep5Export
            rows={w.rows}
            selected={w.selected}
            selectedIds={w.selectedIds}
            zipLoading={w.zipLoading}
            toggle={w.toggle}
            goStep={w.goStep}
            downloadZip={w.downloadZip}
          />
        )}
      </div>
    </div>
  );
}
