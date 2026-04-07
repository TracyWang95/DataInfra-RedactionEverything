// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { useState, useRef } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import {
  type BatchRow,
  RECOGNITION_DONE_STATUSES,
  type Step,
} from '../types';

interface BatchStep3RecognizeProps {
  rows: BatchRow[];
  activeJobId: string | null;
  failedRows: BatchRow[];
  goStep: (s: Step) => void;
  submitQueueToWorker: () => Promise<void>;
  requeueFailedItems: () => Promise<void>;
}

export function BatchStep3Recognize({
  rows,
  activeJobId,
  failedRows,
  goStep,
  submitQueueToWorker,
  requeueFailedItems,
}: BatchStep3RecognizeProps) {
  const t = useT();
  const doneCount = rows.filter(r => RECOGNITION_DONE_STATUSES.has(r.analyzeStatus)).length;
  const allDone = rows.length > 0 && doneCount === rows.length;
  const [everSubmitted, setEverSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const isProcessing = everSubmitted && !allDone;

  const handleSubmit = async () => {
    setSubmitting(true);
    setEverSubmitted(true);
    await submitQueueToWorker();
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setSubmitting(false), 2000);
  };

  const progressLabel = allDone
    ? t('batchWizard.step3.allDone')
    : isProcessing
      ? `${t('batchWizard.step3.processing')} ${doneCount}/${rows.length}`
      : `${rows.length} ${t('batchWizard.step3.pending')}`;
  const statusLabel = (status: BatchRow['analyzeStatus']) => {
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
  };

  const pct = rows.length > 0 ? Math.min(100, (doneCount / rows.length) * 100) : 0;
  const displayPct = isProcessing && pct === 0 ? 3 : pct;

  return (
    <Card className="flex min-h-0 flex-1 flex-col overflow-hidden" data-testid="batch-step3-recognize">
      <CardHeader className="shrink-0">
        <CardTitle className="text-sm">{t('batchWizard.step3.title')}</CardTitle>
        <p className="text-xs text-muted-foreground">
          {t('batchWizard.step3.desc')}
        </p>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain">
        {/* Progress */}
        {rows.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <div className="flex justify-between text-xs">
              <span
                className={cn(
                  allDone && 'font-medium text-[var(--success-foreground)]',
                  isProcessing && !allDone && 'text-primary',
                  !isProcessing && !allDone && 'text-muted-foreground',
                )}
              >
                {progressLabel}
              </span>
              <span className="tabular-nums font-medium">
                {doneCount} / {rows.length}
              </span>
            </div>
            <Progress
              value={displayPct}
              className="h-2.5"
              indicatorClassName={cn(
                allDone && 'tone-progress-success',
                isProcessing && !allDone && 'tone-progress-brand animate-pulse',
              )}
              data-testid="recognition-progress"
            />
          </div>
        )}

        {/* Action buttons */}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() => goStep(2)}
            data-testid="step3-prev"
          >
            {t('batchWizard.step3.prevStep')}
          </Button>

          <Button
            onClick={() => void handleSubmit()}
            disabled={!activeJobId || !rows.length || allDone || isProcessing || submitting}
            data-testid="submit-queue"
          >
            {t('batchWizard.step3.submitQueue')}
          </Button>

          {failedRows.length > 0 && (
            <Button
              variant="outline"
              className="text-destructive border-destructive/30 hover:bg-destructive/5"
              onClick={() => void requeueFailedItems()}
              data-testid="retry-failed"
            >
              {t('batchWizard.step3.retryFailed')} ({failedRows.length})
            </Button>
          )}

          <Button
            variant={allDone ? 'default' : 'outline'}
            onClick={() => goStep(4)}
            disabled={!allDone}
            className={cn(allDone && 'bg-primary hover:bg-primary/90')}
            data-testid="step3-next"
          >
            {allDone
              ? `${t('batchWizard.step3.nextReview')} \u2192`
              : `${t('batchWizard.step3.nextReview')} (${doneCount}/${rows.length})`}
          </Button>
        </div>

        {/* Per-file status list */}
        <div className="border rounded-lg divide-y max-h-80 overflow-y-auto">
          {rows.map(r => (
            <div
              key={r.file_id}
              className="px-4 py-2 flex flex-wrap items-center gap-2 text-sm"
            >
              <span className="truncate flex-1 min-w-0">{r.original_filename}</span>
              <Badge
                variant={
                  r.analyzeStatus === 'completed'
                    ? 'default'
                    : r.analyzeStatus === 'failed'
                      ? 'destructive'
                      : RECOGNITION_DONE_STATUSES.has(r.analyzeStatus)
                        ? 'secondary'
                        : 'outline'
                }
                className="text-xs"
              >
                {statusLabel(r.analyzeStatus)}
              </Badge>
              {r.analyzeError && (
                <span className="text-xs text-destructive">{r.analyzeError}</span>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
