// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { CheckCircle2, TableProperties } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type { StructuredConnection, StructuredDataset } from '@/services/structuredApi';
import {
  buildDatasetIdentityContexts,
  buildDatasetScopeSummary,
  compareStructuredDatasetsForReview,
  datasetIdentityContextText,
  isSameDatasetReviewScope,
} from '../lib/dataset-utils';
import { DatasetIdentity, EmptyState, ListPager } from './shared';

export function DatasetPickerCard({
  datasets,
  connections,
  selectedDatasetId,
  reviewedDatasetIds,
  dirtyDatasetId,
  onSelect,
  compact,
}: {
  datasets: StructuredDataset[];
  connections?: StructuredConnection[];
  selectedDatasetId: string;
  reviewedDatasetIds?: Set<string>;
  dirtyDatasetId?: string;
  onSelect: (datasetId: string) => void;
  compact?: boolean;
}) {
  const t = useT();
  const [query, setQuery] = React.useState('');
  const [page, setPage] = React.useState(0);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredDatasets = React.useMemo(
    () =>
      normalizedQuery
        ? datasets.filter((dataset) =>
            [dataset.name, dataset.source_kind, dataset.schema_name, dataset.table_name]
              .filter(Boolean)
              .some((value) => String(value).toLowerCase().includes(normalizedQuery)),
          )
        : datasets,
    [datasets, normalizedQuery],
  );
  const orderedDatasets = React.useMemo(
    () => [...filteredDatasets].sort(compareStructuredDatasetsForReview),
    [filteredDatasets],
  );
  const identityContextById = React.useMemo(
    () => buildDatasetIdentityContexts(orderedDatasets, connections ?? []),
    [connections, orderedDatasets],
  );
  const pageSize = compact ? 3 : 8;
  const orderedDatasetIds = React.useMemo(() => orderedDatasets.map((dataset) => dataset.id).join('|'), [orderedDatasets]);
  const pageCount = Math.max(1, Math.ceil(orderedDatasets.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleDatasets = orderedDatasets.slice(safePage * pageSize, safePage * pageSize + pageSize);
  const selectedDataset = datasets.find((dataset) => dataset.id === selectedDatasetId) ?? null;
  const scopeSummary = React.useMemo(
    () => buildDatasetScopeSummary(selectedDataset, datasets, connections ?? []),
    // `t` keeps the memoized labels in sync with the active locale.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [connections, datasets, selectedDataset, t],
  );
  const reviewedCount = reviewedDatasetIds
    ? datasets.filter((dataset) => reviewedDatasetIds.has(dataset.id)).length
    : 0;
  const dirtyCount = dirtyDatasetId && datasets.some((dataset) => dataset.id === dirtyDatasetId) ? 1 : 0;
  const pendingCount = Math.max(datasets.length - reviewedCount - dirtyCount, 0);
  const selectedScopeCount = selectedDataset
    ? datasets.filter((dataset) => isSameDatasetReviewScope(dataset, selectedDataset)).length
    : 0;
  const selectedScopeLabel = selectedDataset?.connection_id
    ? t('structured.scope.currentConnection')
    : t('structured.scope.currentSource');
  const listSummary = datasets.length
    ? [
        normalizedQuery
          ? t('structured.picker.summary.filtered')
              .replace('{count}', String(orderedDatasets.length))
              .replace('{total}', String(datasets.length))
          : t('structured.picker.summary.total').replace('{count}', String(datasets.length)),
        t('structured.picker.summary.saved').replace('{count}', String(reviewedCount)),
        dirtyCount > 0 ? t('structured.picker.summary.dirty').replace('{count}', String(dirtyCount)) : '',
        t('structured.picker.summary.pending').replace('{count}', String(pendingCount)),
        selectedScopeCount > 1 ? `${selectedScopeLabel} ${selectedScopeCount}` : '',
      ]
        .filter(Boolean)
        .join(' · ')
    : t('structured.picker.summary.fallback');

  React.useEffect(() => {
    setPage(0);
  }, [orderedDatasetIds]);

  React.useEffect(() => {
    if (!selectedDatasetId) return;
    const selectedIndex = orderedDatasets.findIndex((dataset) => dataset.id === selectedDatasetId);
    if (selectedIndex < 0) return;
    const selectedPage = Math.floor(selectedIndex / pageSize);
    setPage((current) => (current === selectedPage ? current : selectedPage));
  }, [orderedDatasetIds, orderedDatasets, pageSize, selectedDatasetId]);

  return (
    <Card className="page-surface flex min-h-0 flex-col border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">{t('structured.common.datasetsLabel')}</CardTitle>
        <CardDescription>{listSummary}</CardDescription>
      </CardHeader>
      <CardContent className="grid min-h-0 flex-1 grid-rows-[auto_auto_minmax(0,1fr)_auto] gap-2 px-4 pb-3 pt-0">
        {scopeSummary ? (
          <div
            className="grid gap-1 rounded-xl border border-border bg-muted/25 px-2.5 py-1.5"
            data-testid="dataset-scope-summary"
          >
            <span className="flex min-w-0 items-center justify-between gap-2">
              <span className="min-w-0">
                <span className="block text-xs font-semibold uppercase tracking-wide text-muted-foreground">{scopeSummary.eyebrow}</span>
                <span className="block truncate text-xs font-semibold" title={scopeSummary.title}>
                  {scopeSummary.title}
                </span>
              </span>
              <Badge variant="outline" className="shrink-0">
                {scopeSummary.badge}
              </Badge>
            </span>
            <span className="truncate text-[11px] text-muted-foreground" title={scopeSummary.detail}>
              {scopeSummary.detail}
            </span>
          </div>
        ) : (
          <div className="hidden" />
        )}
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t('structured.picker.searchPlaceholder')}
          className="h-9"
        />
        <div className="grid content-start gap-2 overflow-hidden pr-1">
          {filteredDatasets.length === 0 ? (
            <EmptyState icon={TableProperties} text={t('structured.common.noDatasets')} />
          ) : (
            visibleDatasets.map((dataset) => {
              const selected = selectedDatasetId === dataset.id;
              const dirty = dirtyDatasetId === dataset.id;
              const reviewed = reviewedDatasetIds?.has(dataset.id) ?? false;
              return (
                <button
                  key={dataset.id}
                  type="button"
                  onClick={() => onSelect(dataset.id)}
                  data-testid="dataset-picker-item"
                  data-dataset-name={dataset.table_name ?? dataset.name}
                  data-dataset-context={datasetIdentityContextText(dataset, identityContextById.get(dataset.id))}
                  className={cn(
                    'grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border text-left transition hover:bg-muted/35',
                    compact ? 'min-h-12 px-2.5 py-1.5' : 'min-h-14 px-3 py-2',
                    selected && 'border-foreground bg-muted/45',
                  )}
                >
                  <DatasetIdentity dataset={dataset} compact identityContext={identityContextById.get(dataset.id)} />
                  <span className="flex shrink-0 flex-col items-end gap-1">
                    <CheckCircle2
                      className={cn(
                        'size-4 text-muted-foreground',
                        selected && 'text-foreground',
                        reviewed && 'text-[var(--success-foreground)]',
                        dirty && 'text-[var(--warning-foreground)]',
                      )}
                    />
                    {dirty || reviewed ? (
                      <span
                        className={cn(
                          'rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                          dirty
                            ? 'bg-[var(--warning-surface)] text-[var(--warning-foreground)]'
                            : 'bg-[var(--success-surface)] text-[var(--success-foreground)]',
                        )}
                      >
                        {dirty ? t('structured.picker.dirtyBadge') : t('structured.picker.savedBadge')}
                      </span>
                    ) : null}
                  </span>
                </button>
              );
            })
          )}
        </div>
        {filteredDatasets.length > 0 ? (
          <ListPager
            label={t('structured.common.datasetsLabel')}
            page={safePage}
            pageCount={pageCount}
            total={orderedDatasets.length}
            pageSize={pageSize}
            visibleCount={visibleDatasets.length}
            onPageChange={setPage}
          />
        ) : (
          <div className="min-h-0" />
        )}
      </CardContent>
    </Card>
  );
}
