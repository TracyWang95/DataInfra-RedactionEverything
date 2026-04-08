// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { Navigate } from 'react-router-dom';

import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { useBatchWizard } from './hooks/use-batch-wizard';
import { BatchWizardProvider } from './batch-wizard-context';
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
    <BatchWizardProvider value={w}>
      <div
        className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background"
        data-testid="batch-wizard"
      >
        <div
          className={cn(
            'flex min-h-0 min-w-0 flex-1 flex-col',
            w.step === 1
              ? 'page-shell-narrow !max-w-[108rem] 2xl:!max-w-[118rem] overflow-hidden'
              : w.step === 4
                ? 'page-shell overflow-hidden'
                : 'page-shell-narrow !max-w-[112rem] 2xl:!max-w-[122rem] overflow-hidden',
          )}
        >
          {w.previewMode && (
            <Alert className="mb-3" data-testid="batch-preview-alert">
              <AlertDescription>{t('batchWizard.previewBanner')}</AlertDescription>
            </Alert>
          )}

          {w.step !== 4 && (
            <p className="mb-0.5 shrink-0 text-xs leading-tight text-muted-foreground">
              {t('batchWizard.stepsOverview')}
            </p>
          )}

          <BatchStepProgress
            currentStep={w.step}
            canGoStep={w.canGoStep}
          />

          {w.msg && (
            <Alert variant={msgVariant} className="mb-2">
              <AlertDescription>{w.msg.text}</AlertDescription>
            </Alert>
          )}

          {w.step === 1 && <BatchStep1Config />}

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

          {w.step === 4 && <BatchStep4Review />}

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
    </BatchWizardProvider>
  );
}
