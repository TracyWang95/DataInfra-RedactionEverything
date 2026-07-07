// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, TableProperties } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type {
  StructuredConnection,
  StructuredDataset,
  StructuredExportFormat,
} from '@/services/structuredApi';
import {
  buildDatasetIdentityContexts,
  compareStructuredDatasetsForReview,
  datasetIdentityContextText,
  isDatasetDeliveryReady,
  matchesDeliveryDatasetQuery,
  policyReviewUrlForDataset,
  structuredJobStatusLabel,
} from '../lib/dataset-utils';
import { DatasetIdentity, EmptyState, ListPager } from './shared';

export function DeliveryDatasetCard({
  datasets,
  connections,
  selectedIds,
  onToggle,
  onSelectAll,
  onClear,
}: {
  datasets: StructuredDataset[];
  connections: StructuredConnection[];
  selectedIds: Set<string>;
  onToggle: (datasetId: string) => void;
  onSelectAll: (datasetIds?: string[]) => void;
  onClear: () => void;
}) {
  const t = useT();
  const [query, setQuery] = React.useState('');
  const [page, setPage] = React.useState(0);
  const pageSize = 5;
  const deliverableDatasets = React.useMemo(() => datasets.filter(isDatasetDeliveryReady), [datasets]);
  const deliverableIds = React.useMemo(() => new Set(deliverableDatasets.map((dataset) => dataset.id)), [deliverableDatasets]);
  const deliverableCount = deliverableDatasets.length;
  const effectiveSelectedCount = Array.from(selectedIds).filter((datasetId) => deliverableIds.has(datasetId)).length;
  const datasetListSignature = React.useMemo(
    () => datasets.map((dataset) => `${dataset.id}:${isDatasetDeliveryReady(dataset) ? 'ready' : 'pending'}`).join('|'),
    [datasets],
  );
  const orderedDatasets = React.useMemo(
    () =>
      datasets.filter((dataset) => matchesDeliveryDatasetQuery(dataset, query, connections)).sort((left, right) => {
        const leftReviewed = isDatasetDeliveryReady(left);
        const rightReviewed = isDatasetDeliveryReady(right);
        if (leftReviewed !== rightReviewed) return leftReviewed ? -1 : 1;
        return compareStructuredDatasetsForReview(left, right);
      }),
    [connections, datasets, query],
  );
  const filteredDeliverableIds = React.useMemo(
    () => orderedDatasets.filter(isDatasetDeliveryReady).map((dataset) => dataset.id),
    [orderedDatasets],
  );
  const normalizedQuery = query.trim();
  const identityContextById = React.useMemo(
    () => buildDatasetIdentityContexts(orderedDatasets, connections),
    [connections, orderedDatasets],
  );
  const pageCount = Math.max(1, Math.ceil(orderedDatasets.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleDatasets = orderedDatasets.slice(safePage * pageSize, safePage * pageSize + pageSize);

  React.useEffect(() => {
    setPage(0);
  }, [datasetListSignature, normalizedQuery]);

  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="flex-row items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <CardTitle className="text-sm">{t('structured.delivery.list.title')}</CardTitle>
          <CardDescription>{t('structured.delivery.list.description')}</CardDescription>
        </div>
        <Badge variant="outline" className="shrink-0 rounded-full">
          {t('structured.common.selectedCount').replace('{count}', String(effectiveSelectedCount))}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-2 px-4 pb-4 pt-0">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t('structured.delivery.list.searchPlaceholder')}
          className="h-9"
          data-testid="delivery-dataset-search"
        />
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-muted/25 px-3 py-2">
          <span className="text-sm text-muted-foreground">
            {t('structured.delivery.list.summary')
              .replace('{total}', String(datasets.length))
              .replace('{deliverable}', String(deliverableCount))
              .replace('{selected}', String(effectiveSelectedCount))}
            {normalizedQuery
              ? t('structured.delivery.list.summaryFiltered')
                  .replace('{filtered}', String(orderedDatasets.length))
                  .replace('{deliverable}', String(filteredDeliverableIds.length))
              : ''}
            {t('structured.delivery.list.summaryPage').replace('{count}', String(visibleDatasets.length))}
          </span>
          <span className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onSelectAll(normalizedQuery ? filteredDeliverableIds : undefined)}
              disabled={(normalizedQuery ? filteredDeliverableIds.length : deliverableCount) === 0}
            >
              {normalizedQuery ? t('structured.delivery.list.selectFiltered') : t('structured.delivery.list.selectDeliverable')}
            </Button>
            <Button variant="outline" size="sm" onClick={onClear} disabled={selectedIds.size === 0}>
              {t('structured.common.clear')}
            </Button>
          </span>
        </div>
        <div className="grid gap-2">
          {datasets.length === 0 ? (
            <EmptyState icon={TableProperties} text={t('structured.delivery.list.emptyNone')} />
          ) : orderedDatasets.length === 0 ? (
            <EmptyState icon={TableProperties} text={t('structured.delivery.list.emptyFiltered')} />
          ) : (
            visibleDatasets.map((dataset) => {
              const reviewed = isDatasetDeliveryReady(dataset);
              const selected = reviewed && selectedIds.has(dataset.id);
              return (
                <div
                  key={dataset.id}
                  data-testid="delivery-dataset-row"
                  data-delivery-ready={reviewed ? 'true' : 'false'}
                  data-dataset-name={dataset.table_name ?? dataset.name}
                  data-dataset-context={datasetIdentityContextText(dataset, identityContextById.get(dataset.id))}
                  className={cn(
                    'grid min-h-16 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-2 transition',
                    selected && 'border-foreground bg-muted/45',
                    !reviewed && 'bg-muted/20 text-muted-foreground',
                  )}
                >
                  <Checkbox
                    aria-label={t('structured.delivery.list.selectAria').replace('{name}', dataset.name)}
                    checked={selected}
                    disabled={!reviewed}
                    onCheckedChange={() => onToggle(dataset.id)}
                  />
                  <DatasetIdentity dataset={dataset} identityContext={identityContextById.get(dataset.id)} />
                  <span className="flex shrink-0 items-center gap-2">
                    <Badge
                      variant={reviewed ? 'outline' : 'secondary'}
                      className={cn(
                        'shrink-0',
                        reviewed
                          ? 'border-[var(--success-border)] text-[var(--success-foreground)]'
                          : 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]',
                      )}
                    >
                      {reviewed ? t('structured.common.reviewed') : t('structured.common.pendingReview')}
                    </Badge>
                    {!reviewed ? (
                      <Button asChild variant="outline" size="sm" className="h-7 bg-background px-2 text-[11px]">
                        <Link to={policyReviewUrlForDataset(dataset, { returnToDelivery: true })}>
                          {t('structured.common.goReview')}
                        </Link>
                      </Button>
                    ) : null}
                  </span>
                </div>
              );
            })
          )}
        </div>
        {orderedDatasets.length > pageSize ? (
          <ListPager
            label={t('structured.common.datasetsLabel')}
            page={safePage}
            pageCount={pageCount}
            total={orderedDatasets.length}
            pageSize={pageSize}
            visibleCount={visibleDatasets.length}
            onPageChange={setPage}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

export function DeliveryChecklist({
  selectedCount,
  unreviewedCount,
  exportFormat,
  deliveryModeLabel,
  latestJobStatus,
}: {
  selectedCount: number;
  unreviewedCount: number;
  exportFormat: StructuredExportFormat;
  deliveryModeLabel: string;
  latestJobStatus: string;
}) {
  const t = useT();
  const checks = [
    {
      label: t('structured.delivery.list.title'),
      detail:
        selectedCount > 0
          ? t('structured.delivery.checklist.selectedDetail').replace('{count}', String(selectedCount))
          : t('structured.delivery.checklist.waitingSelect'),
      done: selectedCount > 0,
    },
    {
      label: t('structured.delivery.checklist.jobMode'),
      detail: deliveryModeLabel,
      done: selectedCount > 0,
    },
    {
      label: t('structured.delivery.checklist.policyReview'),
      detail:
        selectedCount === 0
          ? t('structured.delivery.modePending')
          : unreviewedCount > 0
            ? t('structured.delivery.checklist.reviewedPartial').replace('{count}', String(unreviewedCount))
            : t('structured.delivery.checklist.reviewedAll'),
      done: selectedCount > 0,
    },
    {
      label: t('structured.delivery.checklist.packageFormat'),
      detail: t('structured.delivery.checklist.formatDetail').replace('{format}', exportFormat.toUpperCase()),
      done: true,
    },
    {
      label: t('structured.delivery.checklist.backgroundJob'),
      detail: latestJobStatus ? structuredJobStatusLabel(latestJobStatus) : t('structured.delivery.checklist.notCreated'),
      done: latestJobStatus === 'completed',
    },
  ];
  return (
    <div className="grid gap-1.5 rounded-xl border border-border bg-muted/25 p-1.5 sm:grid-cols-2">
      {checks.map((check) => (
        <div key={check.label} className="flex min-w-0 items-center justify-between gap-2 rounded-lg bg-background px-2.5 py-1.5">
          <span className="flex min-w-0 items-center gap-2">
            <CheckCircle2 className={cn('size-4 shrink-0', check.done ? 'text-[var(--success-foreground)]' : 'text-muted-foreground')} />
            <span className="truncate text-sm font-medium">{check.label}</span>
          </span>
          <span className="truncate text-xs text-muted-foreground">{check.detail}</span>
        </div>
      ))}
    </div>
  );
}
