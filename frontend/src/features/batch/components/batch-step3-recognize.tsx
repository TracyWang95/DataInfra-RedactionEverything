// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { memo, useMemo, useState } from 'react';

import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { useServiceHealth } from '@/hooks/use-service-health';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import type { BatchWizardMode } from '@/services/batchPipeline';

import {
  type BatchRow,
  RECOGNITION_ACTIVE_STATUSES,
  RECOGNITION_DONE_STATUSES,
  isRecognitionSettledForReview,
  type Step,
} from '../types';
import { getBatchModeReadiness } from '../lib/batch-mode-readiness';

interface BatchStep3RecognizeProps {
  mode?: BatchWizardMode;
  rows: BatchRow[];
  activeJobId: string | null;
  failedRows: BatchRow[];
  goStep: (s: Step) => void;
  submitQueueToWorker: () => Promise<void>;
  requeueFailedItems: () => Promise<void>;
}

type StatusFilter = 'all' | 'active' | 'ready' | 'failed' | 'pending';

function BatchStep3RecognizeInner({
  mode = 'smart',
  rows,
  activeJobId,
  failedRows,
  goStep,
  submitQueueToWorker,
  requeueFailedItems,
}: BatchStep3RecognizeProps) {
  const t = useT();
  const { health } = useServiceHealth();
  const doneCount = rows.filter((r) => RECOGNITION_DONE_STATUSES.has(r.analyzeStatus)).length;
  const failedCount = failedRows.length;
  const pendingCount = rows.filter((r) => r.analyzeStatus === 'pending').length;
  const workingCount = rows.filter(
    (r) => r.analyzeStatus === 'parsing' || r.analyzeStatus === 'analyzing',
  ).length;
  const submittableCount = rows.filter(
    (r) => !RECOGNITION_DONE_STATUSES.has(r.analyzeStatus) && r.analyzeStatus !== 'failed',
  ).length;
  const visibleProgressCount = Math.min(rows.length, doneCount + workingCount);
  const allDone = rows.length > 0 && doneCount === rows.length;
  const canReview = isRecognitionSettledForReview(rows);
  const [everSubmitted, setEverSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [requeueing, setRequeueing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  const isProcessing =
    (everSubmitted || workingCount > 0) &&
    rows.some((row) => RECOGNITION_ACTIVE_STATUSES.has(row.analyzeStatus));
  const filters: Array<{ key: StatusFilter; label: string; count: number }> = [
    { key: 'all', label: t('batchWizard.step3.filterAll'), count: rows.length },
    { key: 'ready', label: t('batchWizard.step3.filterReady'), count: doneCount },
    { key: 'active', label: t('batchWizard.step3.filterActive'), count: workingCount },
    { key: 'pending', label: t('batchWizard.step3.filterPending'), count: pendingCount },
    { key: 'failed', label: t('batchWizard.step3.filterFailed'), count: failedCount },
  ];
  const filteredRows = useMemo(() => {
    if (statusFilter === 'ready') {
      return rows.filter((row) => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus));
    }
    if (statusFilter === 'failed') return rows.filter((row) => row.analyzeStatus === 'failed');
    if (statusFilter === 'pending') return rows.filter((row) => row.analyzeStatus === 'pending');
    if (statusFilter === 'active') {
      return rows.filter(
        (row) => row.analyzeStatus === 'parsing' || row.analyzeStatus === 'analyzing',
      );
    }
    return rows;
  }, [rows, statusFilter]);

  const handleSubmit = async () => {
    setSubmitting(true);
    setEverSubmitted(true);
    try {
      await submitQueueToWorker();
    } finally {
      setSubmitting(false);
    }
  };

  const handleRequeueFailed = async () => {
    if (requeueing) return;
    setRequeueing(true);
    try {
      await requeueFailedItems();
    } finally {
      setRequeueing(false);
    }
  };

  const progressLabel = allDone
    ? t('batchWizard.step3.allDone')
    : canReview
      ? `${t('batchWizard.step3.readyForReview')} ${doneCount}/${rows.length}`
      : isProcessing
        ? `${t('batchWizard.step3.processing')} ${visibleProgressCount}/${rows.length} (${t('batchWizard.step3.readyForReview')} ${doneCount}/${rows.length})`
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
  const rowProgressLabel = (row: BatchRow): string | null => {
    const current = Number(row.recognitionCurrent ?? 0);
    const total = Number(row.recognitionTotal ?? 0);
    const rawMessage = row.recognitionMessage?.trim();
    if (
      row.recognitionStage === 'vision' &&
      total > 1 &&
      (row.analyzeStatus === 'analyzing' || row.analyzeStatus === 'parsing')
    ) {
      return t('batchWizard.step3.filePageProgress')
        .replace('{current}', String(Math.max(0, current)))
        .replace('{total}', String(total));
    }
    if (
      row.recognitionStage === 'ner' &&
      (row.analyzeStatus === 'analyzing' || row.analyzeStatus === 'parsing')
    ) {
      return t('batchWizard.step3.fileTextProgress');
    }
    if (!rawMessage) return null;
    switch (rawMessage) {
      case 'text_recognition_running':
      case 'Text recognition running':
        return t('batchWizard.step3.fileTextProgress');
      case 'text_recognition_complete':
      case 'Text recognition complete':
        return t('batchWizard.step3.fileTextComplete');
      case 'vision_recognition_complete':
      case 'Vision recognition complete':
        return t('batchWizard.step3.fileVisionComplete');
      case 'Requeued after stale processing heartbeat':
        return t('batchWizard.step3.requeuedAfterStale');
      default:
        return rawMessage;
    }
  };

  const pct = rows.length > 0 ? Math.min(100, (visibleProgressCount / rows.length) * 100) : 0;
  const displayPct = isProcessing && pct === 0 ? 3 : pct;
  const modeReadiness = getBatchModeReadiness(mode, health);
  const hasUnavailableService = Boolean(health && !modeReadiness.ready);
  const blockSubmitForServiceState = hasUnavailableService;

  return (
    <Card
      className="page-surface border-border/70 shadow-[var(--shadow-control)]"
      data-testid="batch-step3-recognize"
    >
      <CardHeader className="shrink-0 border-b border-border/70 px-3 py-2">
        <CardTitle className="text-sm">{t('batchWizard.step3.title')}</CardTitle>
        <p className="truncate text-xs text-muted-foreground">{t('batchWizard.step3.desc')}</p>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2.5 xl:overflow-hidden">
        {/* Progress */}
        {rows.length > 0 && (
          <div
            className="flex flex-col gap-1 rounded-lg border border-border/70 bg-background px-2.5 py-2"
            data-testid="recognition-progress-block"
          >
            <div className="flex min-w-0 justify-between gap-3 text-xs">
              <span
                className={cn(
                  'min-w-0 truncate',
                  allDone && 'font-medium text-[var(--success-foreground)]',
                  isProcessing && !allDone && 'text-primary',
                  !isProcessing && !allDone && 'text-muted-foreground',
                )}
              >
                {progressLabel}
              </span>
              <span className="shrink-0 tabular-nums font-medium">
                {visibleProgressCount} / {rows.length}
              </span>
            </div>
            <Progress
              value={displayPct}
              className="h-1.5"
              indicatorClassName={cn(
                allDone && 'tone-progress-success',
                isProcessing && !allDone && 'tone-progress-brand batch-recognition-progress-active',
              )}
              data-testid="recognition-progress"
            />
          </div>
        )}

        {failedCount > 0 && doneCount > 0 && canReview && (
          <Alert data-testid="recognition-partial-ready">
            <AlertDescription>
              {t('batchWizard.step3.partialReadyHint')
                .replace('{ready}', String(doneCount))
                .replace('{failed}', String(failedCount))}
            </AlertDescription>
          </Alert>
        )}

        {hasUnavailableService && (
          <Alert data-testid="recognition-service-state">
            <AlertDescription>{t('batchWizard.step3.serviceUnavailableHint')}</AlertDescription>
          </Alert>
        )}

        {/* Action buttons */}
        <div className="flex shrink-0 flex-nowrap gap-2 overflow-x-auto pb-1">
          <Button
            variant="outline"
            className="h-9 shrink-0 whitespace-nowrap"
            onClick={() => goStep(2)}
            data-testid="step3-prev"
          >
            {t('batchWizard.step3.prevStep')}
          </Button>

          <Button
            className="h-9 shrink-0 whitespace-nowrap"
            onClick={() => void handleSubmit()}
            disabled={
              !activeJobId ||
              !rows.length ||
              submittableCount === 0 ||
              isProcessing ||
              submitting ||
              blockSubmitForServiceState
            }
            data-testid="submit-queue"
          >
            {blockSubmitForServiceState
              ? t('batchWizard.step3.submitBlocked')
              : t('batchWizard.step3.submitQueue')}
          </Button>

          {failedRows.length > 0 && (
            <Button
              variant="outline"
              className="h-9 shrink-0 whitespace-nowrap border-destructive/30 text-destructive hover:bg-destructive/5"
              onClick={() => void handleRequeueFailed()}
              disabled={blockSubmitForServiceState || requeueing}
              data-testid="retry-failed"
            >
              {t('batchWizard.step3.retryFailed')} ({failedRows.length})
            </Button>
          )}

          <Button
            variant={canReview ? 'default' : 'outline'}
            onClick={() => goStep(4)}
            disabled={!canReview}
            className={cn(
              'h-9 shrink-0 whitespace-nowrap',
              canReview && 'bg-primary hover:bg-primary/90',
            )}
            data-testid="step3-next"
            data-reviewable={canReview ? 'true' : 'false'}
            data-reviewable-count={doneCount}
          >
            {canReview
              ? `${t('batchWizard.step3.nextReview')} \u2192`
              : `${t('batchWizard.step3.nextReview')} (${doneCount}/${rows.length})`}
          </Button>
        </div>

        <div
          className="flex shrink-0 flex-nowrap gap-1.5 overflow-x-auto pb-1"
          data-testid="recognition-status-filters"
        >
          {filters.map(({ key, label, count }) => (
            <Button
              key={key}
              type="button"
              variant={statusFilter === key ? 'default' : 'outline'}
              size="sm"
              className="h-7 shrink-0 rounded-full px-2.5 text-xs whitespace-nowrap"
              onClick={() => setStatusFilter(key)}
              data-testid={`recognition-filter-${key}`}
            >
              {label} {count}
            </Button>
          ))}
        </div>

        {/* Per-file status list */}
        <div className="min-h-0 flex-1 divide-y overflow-y-auto rounded-lg border">
          {filteredRows.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground">
              {t('batchWizard.step3.noRowsInFilter')}
            </div>
          ) : (
            filteredRows.map((r) => {
              const detail = rowProgressLabel(r);
              return (
                <div
                  key={r.file_id}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1 px-3 py-2 text-sm md:grid-cols-[minmax(0,1.2fr)_minmax(0,13rem)_auto_minmax(0,12rem)] md:py-1.5"
                  data-testid={`recognition-row-${r.file_id}`}
                >
                  <span className="min-w-0 truncate" title={r.original_filename}>
                    {r.original_filename}
                  </span>
                  <span
                    className="col-span-2 min-w-0 truncate text-xs text-muted-foreground md:col-auto"
                    title={detail ?? undefined}
                    data-testid={`row-progress-${r.file_id}`}
                  >
                    {detail ?? ''}
                  </span>
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
                    className="col-start-2 row-start-1 shrink-0 whitespace-nowrap text-xs md:col-auto md:row-auto"
                  >
                    {statusLabel(r.analyzeStatus)}
                  </Badge>
                  <span
                    className="col-span-2 min-w-0 truncate text-xs text-destructive md:col-auto"
                    title={r.analyzeError}
                  >
                    {r.analyzeError ?? ''}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export const BatchStep3Recognize = memo(BatchStep3RecognizeInner);
