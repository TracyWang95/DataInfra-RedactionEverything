/**
 * BatchWizard — page orchestrator for the 5-step batch workflow.
 * Imports the use-batch-wizard hook and delegates to step components.
 *
 * Rebuilt from pages/Batch.tsx (3510 lines) into feature module:
 *   - hooks/use-batch-wizard.ts (all wizard state and actions)
 *   - components/batch-step-progress.tsx (step indicator)
 *   - components/batch-step{1..5}-*.tsx (step UI)
 */
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
      className="h-full min-h-0 min-w-0 flex flex-col bg-muted/30 overflow-hidden"
      data-testid="batch-wizard"
    >
      <div
        className={cn(
          'flex-1 flex flex-col min-h-0 min-w-0 w-full max-w-[min(100%,1920px)] mx-auto',
          w.step === 1
            ? 'px-3 py-2 sm:px-4 sm:py-2.5 overflow-hidden'
            : w.step === 4
              ? 'px-2 py-1.5 sm:px-3 sm:py-2 flex flex-col min-h-0 overflow-hidden'
              : 'px-3 py-3 sm:px-5 sm:py-4 overflow-y-auto overscroll-contain',
        )}
      >
        {/* Overview text */}
        {w.step !== 4 && (
          <p className="mb-1 shrink-0 text-xs text-muted-foreground leading-tight">
            {t('batchWizard.stepsOverview')}
          </p>
        )}

        {/* Step progress bar */}
        <BatchStepProgress
          currentStep={w.step}
          canGoStep={w.canGoStep}
          onStepClick={w.goStep}
        />

        {/* Status message */}
        {w.msg && (
          <Alert variant={msgVariant} className="mb-2">
            <AlertDescription>{w.msg.text}</AlertDescription>
          </Alert>
        )}

        {/* Step 1: Config */}
        {w.step === 1 && (
          <BatchStep1Config
            cfg={w.cfg}
            setCfg={w.setCfg}
            configLoaded={w.configLoaded}
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

        {/* Step 2: Upload */}
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

        {/* Step 3: Recognize */}
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

        {/* Step 4: Review */}
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

        {/* Step 5: Export */}
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
