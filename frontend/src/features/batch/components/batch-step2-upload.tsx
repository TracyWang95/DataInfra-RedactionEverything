// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { memo, useState } from 'react';

import { Link } from 'react-router-dom';
import { X } from 'lucide-react';
import type { useDropzone } from 'react-dropzone';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';

import type { BatchWizardMode } from '@/services/batchPipeline';
import { isPreviewBatchJobId } from '../lib/batch-preview-fixtures';
import type { BatchRow, BatchUploadIssue, BatchUploadProgress, Step } from '../types';

function formatFileSize(bytes: number | undefined): string {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

interface BatchStep2UploadProps {
  mode: BatchWizardMode;
  activeJobId: string | null;
  rows: BatchRow[];
  loading: boolean;
  isDragActive: boolean;
  getRootProps: () => Record<string, unknown>;
  getInputProps: ReturnType<typeof useDropzone>['getInputProps'];
  uploadIssues: BatchUploadIssue[];
  uploadProgress?: BatchUploadProgress | null;
  clearUploadIssues: () => void;
  goStep: (s: Step) => void;
  removeRow: (fileId: string) => Promise<void>;
  clearRows: () => Promise<void>;
}

function BatchStep2UploadInner({
  mode,
  activeJobId,
  rows,
  loading,
  isDragActive,
  getRootProps,
  getInputProps,
  uploadIssues,
  uploadProgress,
  clearUploadIssues,
  goStep,
  removeRow,
  clearRows,
}: BatchStep2UploadProps) {
  const t = useT();
  const previewJob = activeJobId ? isPreviewBatchJobId(activeJobId) : false;
  const jobLabel = previewJob ? t('batchWizard.previewJobLabel') : activeJobId;
  const [pendingRemoveId, setPendingRemoveId] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const handleRemove = async (fileId: string) => {
    setPendingRemoveId(fileId);
    try {
      await removeRow(fileId);
    } finally {
      setPendingRemoveId(null);
    }
  };

  const handleClear = async () => {
    if (!rows.length) return;
    if (
      !window.confirm(t('batchWizard.step2.clearConfirm').replace('{count}', String(rows.length)))
    ) {
      return;
    }
    setClearing(true);
    try {
      await clearRows();
    } finally {
      setClearing(false);
    }
  };

  const dropHint =
    mode === 'smart'
      ? t('batchWizard.step2.dropHintSmart')
      : mode === 'image'
        ? t('batchWizard.step2.dropHintImage')
        : t('batchWizard.step2.dropHintText');
  const uploadPercent =
    uploadProgress && uploadProgress.total > 0
      ? Math.round((uploadProgress.completed / uploadProgress.total) * 100)
      : 0;
  const nextDisabled = !rows.length || loading;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden" data-testid="batch-step2-upload">
      <div className="grid min-h-0 flex-1 gap-3 overflow-y-auto xl:grid-cols-[minmax(0,1.14fr)_minmax(22rem,0.86fr)] xl:overflow-hidden">
        <div className="flex min-h-0 flex-col gap-3">
          {activeJobId && (
            <Card className="rounded-[20px] border-border/70 shadow-[var(--shadow-control)]">
              <CardContent className="p-3">
                <p className="truncate text-xs text-muted-foreground">
                  {t('batchWizard.step2.jobLinked')}{' '}
                  {previewJob ? (
                    <span className="font-medium text-primary">{jobLabel}</span>
                  ) : (
                    <Link
                      to={`/jobs/${activeJobId}`}
                      className={cn('font-mono text-primary hover:underline')}
                    >
                      {jobLabel}
                    </Link>
                  )}
                </p>
              </CardContent>
            </Card>
          )}

          {uploadIssues.length > 0 && (
            <Card
              className="rounded-[20px] border-destructive/30 bg-destructive/5 shadow-[var(--shadow-control)]"
              role="alert"
              aria-live="polite"
              data-testid="upload-issues"
            >
              <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 px-3 py-2">
                <CardTitle className="text-sm text-destructive">
                  {t('batchWizard.step2.uploadIssuesTitle').replace(
                    '{count}',
                    String(uploadIssues.length),
                  )}
                </CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                  onClick={clearUploadIssues}
                  data-testid="upload-issues-dismiss"
                >
                  {t('batchWizard.step2.dismissIssues')}
                </Button>
              </CardHeader>
              <CardContent className="max-h-28 space-y-1.5 overflow-y-auto px-3 pb-3 pt-0">
                {uploadIssues.slice(0, 5).map((issue) => (
                  <div
                    key={issue.id}
                    className="grid gap-0.5 text-xs sm:grid-cols-[minmax(0,1fr)_minmax(10rem,0.8fr)] sm:gap-2"
                  >
                    <p className="truncate font-medium text-foreground" title={issue.filename}>
                      {issue.filename}
                    </p>
                    <p className="truncate text-muted-foreground" title={issue.reason}>
                      {issue.reason}
                    </p>
                  </div>
                ))}
                {uploadIssues.length > 5 && (
                  <p className="text-xs text-muted-foreground">
                    {t('batchWizard.step2.moreIssues').replace(
                      '{count}',
                      String(uploadIssues.length - 5),
                    )}
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Drop zone */}
          <Card
            {...getRootProps()}
            className={cn(
              'min-h-[160px] flex-1 border-2 border-dashed flex flex-col items-center justify-center rounded-[20px] px-5 py-4 cursor-pointer transition-all xl:min-h-[190px]',
              isDragActive
                ? 'border-primary bg-background shadow-sm'
                : 'border-muted-foreground/20 hover:border-muted-foreground/40',
              loading && 'opacity-50 pointer-events-none',
            )}
            data-testid="drop-zone"
          >
            <input {...getInputProps({ 'aria-label': t('batchWizard.step2.dropHint') })} />
            <p className="text-base font-medium">{t('batchWizard.step2.dropHint')}</p>
            <p className="mt-2 max-w-full truncate text-xs text-muted-foreground" title={dropHint}>
              {dropHint}
            </p>
          </Card>

          {loading && uploadProgress && (
            <Card
              className="rounded-[20px] border-border/70 shadow-[var(--shadow-control)]"
              data-testid="upload-progress"
            >
              <CardContent className="space-y-2 p-3">
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="font-medium text-foreground">
                    {t('batchWizard.step2.uploadProgressTitle')}
                  </span>
                  <span className="shrink-0 text-muted-foreground">
                    {t('batchWizard.step2.uploadProgressCount')
                      .replace('{completed}', String(uploadProgress.completed))
                      .replace('{total}', String(uploadProgress.total))}
                  </span>
                </div>
                <Progress
                  value={uploadPercent}
                  aria-label={t('batchWizard.step2.uploadProgressTitle')}
                />
                <p className="text-xs text-muted-foreground">
                  {t('batchWizard.step2.uploadProgressActive')
                    .replace('{active}', String(uploadProgress.inFlight))
                    .replace('{failed}', String(uploadProgress.failed))}
                </p>
                {uploadProgress.currentFile && (
                  <p
                    className="truncate text-xs text-muted-foreground"
                    data-testid="upload-current-file"
                  >
                    {t('batchWizard.step2.uploadProgressCurrent').replace(
                      '{filename}',
                      uploadProgress.currentFile,
                    )}
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          <div className="flex shrink-0 gap-2">
            <Button
              variant="outline"
              className="h-9 whitespace-nowrap"
              onClick={() => goStep(1)}
              data-testid="step2-prev"
            >
              {t('batchWizard.step2.prevStep')}
            </Button>
            <Button
              className="h-9 whitespace-nowrap"
              onClick={() => goStep(3)}
              disabled={nextDisabled}
              title={loading ? t('batchWizard.step2.waitUploadBeforeRecognize') : undefined}
              data-testid="step2-next"
            >
              {t('batchWizard.step2.nextRecognize')}
            </Button>
          </div>
          {loading && (
            <p className="text-xs text-muted-foreground" data-testid="step2-next-disabled-reason">
              {t('batchWizard.step2.waitUploadBeforeRecognize')}
            </p>
          )}
        </div>

        {/* Upload queue */}
        <Card className="page-surface overflow-hidden rounded-[20px] border-border/70 shadow-[var(--shadow-control)]">
          <CardHeader className="border-b border-border/70 px-3 py-2 flex flex-row items-center justify-between gap-2 space-y-0">
            <div className="min-w-0">
              <CardTitle className="truncate text-sm">
                {t('batchWizard.step2.uploadQueue')}
              </CardTitle>
              <p className="truncate text-xs text-muted-foreground">
                {t('batchWizard.step2.queueCount').replace('{count}', String(rows.length))}
              </p>
            </div>
            {rows.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 shrink-0 whitespace-nowrap text-xs text-muted-foreground hover:text-destructive"
                onClick={handleClear}
                disabled={clearing || loading}
                data-testid="step2-clear-all"
              >
                {clearing ? t('batchWizard.step2.clearing') : t('batchWizard.step2.clearAll')}
              </Button>
            )}
          </CardHeader>
          <CardContent className="min-h-0 flex-1 overflow-y-auto divide-y p-0">
            {rows.length === 0 ? (
              <p className="p-6 text-center text-sm text-muted-foreground">
                {t('batchWizard.step2.noFiles')}
              </p>
            ) : (
              rows.map((r) => (
                <div
                  key={r.file_id}
                  className="grid grid-cols-[minmax(0,1fr)_1.75rem] items-center gap-x-2 gap-y-1 px-3 py-2 text-sm sm:grid-cols-[minmax(0,1fr)_5rem_4.5rem_1.75rem] sm:py-1.5"
                  data-testid={`step2-row-${r.file_id}`}
                >
                  <span className="min-w-0 truncate" title={r.original_filename}>
                    {r.original_filename}
                  </span>
                  <span className="min-w-0 whitespace-nowrap text-xs text-muted-foreground sm:text-right">
                    {formatFileSize(r.file_size)}
                  </span>
                  <span
                    className="min-w-0 truncate text-xs text-muted-foreground"
                    title={String(r.file_type)}
                  >
                    {r.file_type}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="col-start-2 row-span-3 row-start-1 size-7 shrink-0 text-muted-foreground hover:text-destructive sm:col-auto sm:row-auto"
                    onClick={() => void handleRemove(r.file_id)}
                    disabled={pendingRemoveId === r.file_id || clearing || loading}
                    title={t('batchWizard.step2.removeFile')}
                    data-testid={`step2-remove-${r.file_id}`}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export const BatchStep2Upload = memo(BatchStep2UploadInner);
