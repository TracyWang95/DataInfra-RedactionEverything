// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { RefreshCw, Trash2, Upload } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import {
  deleteStructuredDataset,
  uploadStructuredFile,
  type StructuredDataset,
} from '@/services/structuredApi';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DatasetRegistryCard, FileTableNextStepCard } from '../components/files-cards';
import { StructuredFrame } from '../components/structured-frame';
import { useNotice } from '../hooks/use-notice';
import { useDatasets } from '../hooks/use-structured-data';
import { isDatasetDeliveryReady, isFileDataset } from '../lib/dataset-utils';

export function StructuredFiles() {
  const t = useT();
  const navigate = useNavigate();
  const datasetsState = useDatasets();
  const notice = useNotice();
  const [pendingDelete, setPendingDelete] = useState<StructuredDataset | null>(null);
  const fileDatasets = datasetsState.datasets.filter(isFileDataset);

  async function handleDeleteDataset(dataset: StructuredDataset) {
    setPendingDelete(null);
    await notice.run('delete', async () => {
      await deleteStructuredDataset(dataset.id);
      await datasetsState.refresh();
      notice.setMessage(
        t('structured.files.notice.deleted').replace('{name}', dataset.name),
      );
    });
  }
  const latestFileDataset = fileDatasets[0] ?? null;
  const deliverableFileCount = fileDatasets.filter(isDatasetDeliveryReady).length;

  async function handleUpload(files: FileList | null) {
    const fileList = Array.from(files ?? []);
    if (!fileList.length) return;
    await notice.run('upload', async () => {
      const uploaded: StructuredDataset[] = [];
      for (const file of fileList) {
        const response = await uploadStructuredFile(file);
        uploaded.push(...response.datasets);
      }
      await datasetsState.refresh();
      notice.setMessage(t('structured.files.notice.imported').replace('{count}', String(uploaded.length)));
      if (uploaded[0]) {
        navigate(
          `/structured/datasets?datasetId=${encodeURIComponent(uploaded[0].id)}&source=file&registered=${uploaded.length}`,
        );
      }
    });
  }

  return (
    <StructuredFrame
      eyebrow={t('structured.files.eyebrow')}
      title={t('structured.files.title')}
      description={t('structured.files.description')}
      notices={notice}
      actions={
        <Button variant="outline" size="sm" onClick={() => void datasetsState.refresh()}>
          <RefreshCw className="size-4" />
          {t('structured.common.refresh')}
        </Button>
      }
    >
      <section className="grid gap-3 xl:grid-cols-[minmax(20rem,0.75fr)_minmax(0,1fr)_minmax(18rem,0.7fr)]">
        <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
          <CardHeader className="px-4 py-3">
            <CardTitle className="text-sm">{t('structured.files.import.title')}</CardTitle>
            <CardDescription>{t('structured.files.import.description')}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 px-4 pb-4 pt-0">
            <Label
              htmlFor="structured-upload"
              className="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-border bg-muted/30 px-4 py-5 text-center transition hover:bg-muted/50"
            >
              <Upload className="size-7 text-muted-foreground" />
              <span className="mt-3 text-sm font-medium">{t('structured.files.import.choose')}</span>
              <span className="mt-1 text-xs text-muted-foreground">CSV / Excel / JSONL / SQLite</span>
            </Label>
            <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
              {['CSV', 'XLSX', 'JSONL', 'SQLite'].map((kind) => (
                <span key={kind} className="rounded-lg border border-border bg-muted/20 px-2 py-1.5 text-center">
                  {kind}
                </span>
              ))}
            </div>
            <Input
              id="structured-upload"
              className="hidden"
              type="file"
              multiple
              accept=".csv,.xlsx,.jsonl,.db,.sqlite"
              onChange={(event) => {
                void handleUpload(event.currentTarget.files);
                event.currentTarget.value = '';
              }}
            />
          </CardContent>
        </Card>

        <DatasetRegistryCard
          title={t('structured.files.registry.title')}
          description={t('structured.files.registry.description')}
          datasets={fileDatasets}
          emptyText={t('structured.files.registry.empty')}
          busy={notice.busy}
          primaryAction={(dataset) => {
            const reviewed = isDatasetDeliveryReady(dataset);
            return (
              <>
                <Badge
                  variant="outline"
                  className={cn(
                    'shrink-0',
                    reviewed
                      ? 'border-[var(--success-border)] text-[var(--success-foreground)]'
                      : 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]',
                  )}
                >
                  {reviewed ? t('structured.common.reviewed') : t('structured.common.pendingReview')}
                </Badge>
                <Button asChild size="sm" variant="outline">
                  <Link to={`/structured/datasets?datasetId=${encodeURIComponent(dataset.id)}`}>
                    {reviewed ? t('structured.common.viewPolicy') : t('structured.common.goToPolicy')}
                  </Link>
                </Button>
              </>
            );
          }}
          secondaryAction={(dataset) => (
            <Button
              size="icon"
              variant="ghost"
              className="size-8 shrink-0 text-muted-foreground hover:text-destructive"
              title={t('structured.files.deleteDataset')}
              onClick={() => setPendingDelete(dataset)}
              data-testid={`delete-dataset-${dataset.id}`}
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        />
        <FileTableNextStepCard
          dataset={latestFileDataset}
          count={fileDatasets.length}
          deliverableCount={deliverableFileCount}
        />
      </section>
      <ConfirmDialog
        open={pendingDelete !== null}
        title={t('structured.files.deleteConfirmTitle')}
        message={t('structured.files.deleteConfirmMessage').replace(
          '{name}',
          pendingDelete?.name ?? '',
        )}
        danger
        onConfirm={() => {
          if (pendingDelete) void handleDeleteDataset(pendingDelete);
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </StructuredFrame>
  );
}
