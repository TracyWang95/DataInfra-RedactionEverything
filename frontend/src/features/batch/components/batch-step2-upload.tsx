/**
 * BatchStep2Upload — Step 2: File upload with drag-and-drop.
 * Uses react-dropzone for file selection and displays upload queue.
 */
import { Link } from 'react-router-dom';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { Step, BatchRow } from '../hooks/use-batch-wizard';
import type { BatchWizardMode } from '@/services/batchPipeline';

interface BatchStep2UploadProps {
  mode: BatchWizardMode;
  activeJobId: string | null;
  rows: BatchRow[];
  loading: boolean;
  isDragActive: boolean;
  getRootProps: () => Record<string, unknown>;
  getInputProps: () => Record<string, unknown>;
  goStep: (s: Step) => void;
}

export function BatchStep2Upload({
  mode,
  activeJobId,
  rows,
  loading,
  isDragActive,
  getRootProps,
  getInputProps,
  goStep,
}: BatchStep2UploadProps) {
  const t = useT();

  const dropHint =
    mode === 'smart'
      ? t('batchWizard.step2.dropHintSmart')
      : mode === 'image'
        ? t('batchWizard.step2.dropHintImage')
        : t('batchWizard.step2.dropHintText');

  return (
    <div className="grid gap-6 lg:grid-cols-2" data-testid="batch-step2-upload">
      <div className="flex flex-col gap-4">
        {activeJobId && (
          <Card>
            <CardContent className="p-3">
              <p className="text-xs text-muted-foreground">
                {t('batchWizard.step2.jobLinked')}{' '}
                <Link
                  to={`/jobs/${activeJobId}`}
                  className="font-mono text-primary hover:underline break-all"
                >
                  {activeJobId}
                </Link>
              </p>
            </CardContent>
          </Card>
        )}

        {/* Drop zone */}
        <Card
          {...getRootProps()}
          className={cn(
            'min-h-[220px] border-2 border-dashed flex flex-col items-center justify-center px-6 py-8 cursor-pointer transition-all',
            isDragActive
              ? 'border-primary bg-background shadow-sm'
              : 'border-muted-foreground/20 hover:border-muted-foreground/40',
            loading && 'opacity-50 pointer-events-none',
          )}
          data-testid="drop-zone"
        >
          <input {...getInputProps()} className="hidden" />
          <p className="text-base font-medium">{t('batchWizard.step2.dropHint')}</p>
          <p className="text-xs text-muted-foreground mt-2">{dropHint}</p>
        </Card>

        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => goStep(1)}
            data-testid="step2-prev"
          >
            {t('batchWizard.step2.prevStep')}
          </Button>
          <Button
            onClick={() => goStep(3)}
            disabled={!rows.length}
            data-testid="step2-next"
          >
            {t('batchWizard.step2.nextRecognize')}
          </Button>
        </div>
      </div>

      {/* Upload queue */}
      <Card className="overflow-hidden flex flex-col min-h-[240px]">
        <CardHeader className="py-3 pb-0">
          <CardTitle className="text-sm">{t('batchWizard.step2.uploadQueue')}</CardTitle>
          <p className="text-xs text-muted-foreground">
            {rows.length} {t('batchWizard.step2.noFiles') === rows.length.toString() ? '' : ''}
          </p>
        </CardHeader>
        <CardContent className="flex-1 overflow-y-auto max-h-[320px] divide-y p-0">
          {rows.length === 0 ? (
            <p className="p-6 text-sm text-muted-foreground text-center">
              {t('batchWizard.step2.noFiles')}
            </p>
          ) : (
            rows.map(r => (
              <div
                key={r.file_id}
                className="px-4 py-2 flex justify-between gap-2 text-sm"
              >
                <span className="truncate">{r.original_filename}</span>
                <span className="text-xs text-muted-foreground shrink-0">
                  {r.file_type}
                </span>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
