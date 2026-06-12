// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CheckCircle2, TableProperties } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type { StructuredDataset } from '@/services/structuredApi';
import { isDatasetDeliveryReady, policyReviewUrlForDataset } from '../lib/dataset-utils';
import { DatasetIdentity, EmptyState, ListPager } from './shared';

export function DatasetRegistryCard({
  title,
  description,
  datasets,
  emptyText,
  busy,
  primaryAction,
}: {
  title: string;
  description: string;
  datasets: StructuredDataset[];
  emptyText: string;
  busy?: string;
  primaryAction?: (dataset: StructuredDataset) => React.ReactNode;
}) {
  const t = useT();
  const [page, setPage] = React.useState(0);
  const pageSize = 6;
  const pageCount = Math.max(1, Math.ceil(datasets.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleDatasets = datasets.slice(safePage * pageSize, safePage * pageSize + pageSize);

  React.useEffect(() => {
    setPage(0);
  }, [datasets.length]);

  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 px-4 pb-4 pt-0">
        <div className="grid gap-2">
          {datasets.length === 0 ? (
            <EmptyState icon={TableProperties} text={emptyText} />
          ) : (
            visibleDatasets.map((dataset) => (
              <div
                key={dataset.id}
                className="grid min-h-16 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-2"
              >
                <DatasetIdentity dataset={dataset} />
                <div className="flex shrink-0 items-center gap-2">
                  {primaryAction?.(dataset)}
                  {busy ? null : null}
                </div>
              </div>
            ))
          )}
        </div>
        {datasets.length > pageSize ? (
          <ListPager
            label={t('structured.common.datasetsLabel')}
            page={safePage}
            pageCount={pageCount}
            total={datasets.length}
            pageSize={pageSize}
            visibleCount={visibleDatasets.length}
            onPageChange={setPage}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

export function FileTableNextStepCard({
  dataset,
  count,
  deliverableCount,
}: {
  dataset: StructuredDataset | null;
  count: number;
  deliverableCount: number;
}) {
  const t = useT();
  const reviewed = Boolean(dataset && isDatasetDeliveryReady(dataset));
  const policyTarget = dataset ? `/structured/datasets?datasetId=${encodeURIComponent(dataset.id)}` : '/structured/files';
  const hasDeliverableFiles = deliverableCount > 0;
  const deliveryTarget = hasDeliverableFiles
    ? '/structured/delivery?scope=file'
    : dataset
      ? policyReviewUrlForDataset(dataset, { returnToDelivery: true })
      : '/structured/delivery';
  const deliveryStatus =
    deliverableCount > 0
      ? deliverableCount === count
        ? t('structured.files.next.statusAllDeliverable')
        : t('structured.files.next.statusDeliverableRatio')
            .replace('{deliverable}', String(deliverableCount))
            .replace('{total}', String(count))
      : dataset
        ? t('structured.common.pendingReview')
        : t('structured.files.next.statusAwaitDataset');
  const deliveryLabel =
    deliverableCount > 1
      ? t('structured.files.next.deliverAll')
      : hasDeliverableFiles
        ? t('structured.files.next.deliverFiles')
        : t('structured.files.next.enterDelivery');
  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">{t('structured.files.next.title')}</CardTitle>
        <CardDescription>{t('structured.files.next.description')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 px-4 pb-4 pt-0">
        <div className="grid gap-2 rounded-xl border border-border bg-muted/25 p-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">{t('structured.files.next.count')}</span>
            <span className="font-semibold">{count}</span>
          </div>
          <div className="grid min-h-14 content-center rounded-lg bg-background px-3 py-2">
            <span className="text-xs text-muted-foreground">{t('structured.files.next.latest')}</span>
            <span className="truncate font-semibold" title={dataset?.name}>
              {dataset?.name ?? t('structured.files.next.empty')}
            </span>
            {dataset ? (
              <span className="truncate text-xs text-muted-foreground">
                {t('structured.common.datasetMeta')
                  .replace('{kind}', dataset.source_kind.toUpperCase())
                  .replace('{columns}', String(dataset.column_count))
                  .replace('{rows}', String(dataset.row_count_estimate ?? 0))}
              </span>
            ) : null}
          </div>
        </div>
        <div className="grid gap-2">
          <FileFlowCheck
            label={t('structured.files.import.title')}
            status={count > 0 ? t('structured.files.next.statusRegistered') : t('structured.files.next.statusAwaitImport')}
            done={count > 0}
          />
          <FileFlowCheck
            label={t('structured.files.next.stepPolicy')}
            status={
              deliverableCount > 0
                ? t('structured.files.next.statusReviewedRatio')
                    .replace('{reviewed}', String(deliverableCount))
                    .replace('{total}', String(count))
                : dataset
                  ? t('structured.common.pendingReview')
                  : t('structured.files.next.statusAwaitRegister')
            }
            done={deliverableCount > 0}
          />
          <FileFlowCheck label={t('structured.files.next.stepDelivery')} status={deliveryStatus} done={hasDeliverableFiles} />
        </div>
        {dataset ? (
          <Button asChild className="h-9 justify-between rounded-xl" size="sm">
            <Link to={policyTarget}>
              {reviewed ? t('structured.common.viewPolicy') : t('structured.files.next.continuePolicy')}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        ) : (
          <Button className="h-9 justify-between rounded-xl" size="sm" disabled>
            {t('structured.files.next.continuePolicy')}
            <ArrowRight className="size-4" />
          </Button>
        )}
        {dataset ? (
          <Button asChild variant="outline" className="h-9 justify-between rounded-xl" size="sm">
            <Link to={deliveryTarget}>
              {deliveryLabel}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        ) : (
          <Button variant="outline" className="h-9 justify-between rounded-xl" size="sm" disabled>
            {t('structured.files.next.enterDelivery')}
            <ArrowRight className="size-4" />
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function FileFlowCheck({ label, status, done }: { label: string; status: string; done: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border px-3 py-1.5 text-sm">
      <span className="flex items-center gap-2">
        <CheckCircle2
          className={cn('size-4', done ? 'text-[var(--success-foreground)]' : 'text-muted-foreground')}
        />
        {label}
      </span>
      <span className="text-xs text-muted-foreground">{status}</span>
    </div>
  );
}
