// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type { StructuredDataset } from '@/services/structuredApi';
import {
  datasetSchemaLabel,
  datasetTypeLabel,
  shortEntityId,
  type DatasetIdentityContext,
} from '../lib/dataset-utils';

export function DatasetIdentity({
  dataset,
  compact,
  identityContext,
}: {
  dataset: StructuredDataset;
  compact?: boolean;
  identityContext?: DatasetIdentityContext;
}) {
  const t = useT();
  const isDbDataset = Boolean(dataset.connection_id);
  const primaryName = isDbDataset ? dataset.table_name || dataset.name : dataset.name;
  const rowText =
    dataset.row_count_estimate == null
      ? t('structured.common.rowsPending')
      : t('structured.common.rowCount').replace('{count}', String(dataset.row_count_estimate));
  const columnText = t('structured.common.columnCount').replace('{count}', String(dataset.column_count));
  const metaItems = isDbDataset
    ? [
        identityContext?.connectionName,
        datasetSchemaLabel(dataset),
        datasetTypeLabel(dataset),
        columnText,
        rowText,
      ]
    : [
        identityContext && identityContext.duplicateCount > 1
          ? t('structured.identity.duplicate')
              .replace('{index}', String(identityContext.duplicateIndex))
              .replace('{count}', String(identityContext.duplicateCount))
          : '',
        identityContext && identityContext.duplicateCount > 1 && dataset.source_id
          ? t('structured.identity.source').replace('{id}', shortEntityId(dataset.source_id))
          : '',
        datasetTypeLabel(dataset),
        columnText,
        rowText,
      ];
  return (
    <span className="min-w-0">
      <span className={cn('block truncate font-medium', compact ? 'text-xs' : 'text-sm')} title={dataset.name}>
        {primaryName}
      </span>
      <span className="mt-1 flex flex-wrap items-center gap-1 text-[10.5px] text-muted-foreground">
        <Badge variant="outline" title={dataset.source_kind}>
          {dataset.source_kind.toUpperCase()}
        </Badge>
        {metaItems.filter((item): item is string => Boolean(item)).map((item, index) => (
          <span key={`${index}:${item}`} className="truncate">
            {item}
          </span>
        ))}
      </span>
    </span>
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const id = React.useId();
  const childArray = React.Children.toArray(children);
  const controlIndex = childArray.findIndex((child) => React.isValidElement<{ id?: string }>(child));
  const items = childArray.map((child, index) =>
    index === controlIndex && React.isValidElement<{ id?: string }>(child)
      ? React.cloneElement(child, { id: child.props.id ?? id })
      : child,
  );
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {items}
    </div>
  );
}

export function EmptyState({ icon: Icon, text }: { icon: React.FC<{ className?: string }>; text: string }) {
  return (
    <div className="flex min-h-32 flex-col items-center justify-center gap-2 px-4 py-8 text-center text-muted-foreground">
      <Icon className="size-5" />
      <span className="text-sm">{text}</span>
    </div>
  );
}

export function ListPager({
  label,
  page,
  pageCount,
  total,
  pageSize,
  visibleCount,
  onPageChange,
}: {
  label: string;
  page: number;
  pageCount: number;
  total: number;
  pageSize: number;
  visibleCount: number;
  onPageChange: (page: number) => void;
}) {
  const t = useT();
  const start = total === 0 ? 0 : page * pageSize + 1;
  const end = total === 0 ? 0 : Math.min(total, page * pageSize + visibleCount);
  return (
    <div className="flex min-h-8 flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-muted/25 px-2.5 py-1.5 text-xs text-muted-foreground">
      <span className="min-w-0 truncate">
        {t('structured.common.pagerSummary')
          .replace('{label}', label)
          .replace('{start}', String(start))
          .replace('{end}', String(end))
          .replace('{total}', String(total))
          .replace('{page}', String(page + 1))
          .replace('{pageCount}', String(pageCount))}
      </span>
      {pageCount > 1 ? (
        <span className="ml-auto flex gap-1.5">
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={page <= 0}
            onClick={() => onPageChange(page - 1)}
          >
            {t('structured.common.prevGroup')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={page >= pageCount - 1}
            onClick={() => onPageChange(page + 1)}
          >
            {t('structured.common.nextGroup')}
          </Button>
        </span>
      ) : null}
    </div>
  );
}
