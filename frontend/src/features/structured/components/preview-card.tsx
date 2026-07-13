// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Eye } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type {
  StructuredColumnProfile,
  StructuredPreview,
  StructuredProfile,
} from '@/services/structuredApi';
import { displayValue } from '../lib/dataset-utils';
import { EmptyState } from './shared';

export function PreviewCard({
  preview,
  profile,
  loading = false,
}: {
  preview: StructuredPreview | null;
  profile: StructuredProfile | null;
  loading?: boolean;
}) {
  const t = useT();
  const columns = React.useMemo(() => {
    if (!preview) return [];
    const profileByColumn = new Map((profile?.columns ?? []).map((column, index) => [column.name, { column, index }]));
    const previewOrder = new Map(preview.columns.map((column, index) => [column, index]));
    const riskWeight: Record<StructuredColumnProfile['risk_level'], number> = {
      critical: 4,
      high: 3,
      medium: 2,
      low: 1,
    };
    const redactedColumns = preview.policy
      .filter((item) => item.enabled && item.action !== 'keep' && preview.columns.includes(item.column))
      .map((item) => item.column)
      .sort((left, right) => {
        const leftProfile = profileByColumn.get(left);
        const rightProfile = profileByColumn.get(right);
        const leftRisk = leftProfile ? riskWeight[leftProfile.column.risk_level] : 0;
        const rightRisk = rightProfile ? riskWeight[rightProfile.column.risk_level] : 0;
        if (leftRisk !== rightRisk) return rightRisk - leftRisk;
        return (previewOrder.get(left) ?? 0) - (previewOrder.get(right) ?? 0);
      });
    const fallbackColumns = preview.columns.filter((column) => !redactedColumns.includes(column));
    return [...redactedColumns, ...fallbackColumns].slice(0, 4);
  }, [preview, profile]);
  const redactedColumnCount =
    preview?.policy.filter((item) => item.enabled && item.action !== 'keep' && preview.columns.includes(item.column)).length ?? 0;
  const redactedColumnSet = React.useMemo(
    () =>
      new Set(
        preview?.policy
          .filter((item) => item.enabled && item.action !== 'keep' && preview.columns.includes(item.column))
          .map((item) => item.column) ?? [],
      ),
    [preview],
  );
  const previewStats = React.useMemo(() => {
    const changedColumns = new Set<string>();
    let changedCellCount = 0;
    let changedRedactedCellCount = 0;
    if (!preview) {
      return {
        displayedRedactedColumnCount: 0,
        hiddenRedactedColumnCount: 0,
        contextColumnCount: 0,
        changedColumns,
        changedRedactedColumnCount: 0,
        changedCellCount,
        changedRedactedCellCount,
      };
    }
    const rowCount = Math.min(preview.original_rows.length, preview.redacted_rows.length, 5);
    for (const column of preview.columns) {
      for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
        const originalValue = displayValue(preview.original_rows[rowIndex]?.[column]);
        const redactedValue = displayValue(preview.redacted_rows[rowIndex]?.[column]);
        if (originalValue !== redactedValue) {
          changedColumns.add(column);
          changedCellCount += 1;
          if (redactedColumnSet.has(column)) changedRedactedCellCount += 1;
        }
      }
    }
    const displayedRedactedColumnCount = columns.filter((column) => redactedColumnSet.has(column)).length;
    const changedRedactedColumnCount = Array.from(changedColumns).filter((column) => redactedColumnSet.has(column)).length;
    return {
      displayedRedactedColumnCount,
      hiddenRedactedColumnCount: Math.max(redactedColumnSet.size - displayedRedactedColumnCount, 0),
      contextColumnCount: Math.max(columns.length - displayedRedactedColumnCount, 0),
      changedColumns,
      changedRedactedColumnCount,
      changedCellCount,
      changedRedactedCellCount,
    };
  }, [columns, preview, redactedColumnSet]);
  const previewContextColumnCount = previewStats.contextColumnCount;
  const previewDescription = loading
    ? t('structured.preview.descLoading')
    : preview
    ? previewContextColumnCount > 0
      ? t('structured.preview.descWithContext')
          .replace('{displayed}', String(previewStats.displayedRedactedColumnCount))
          .replace('{total}', String(redactedColumnCount))
          .replace('{context}', String(previewContextColumnCount))
      : t('structured.preview.descRedactedOnly')
          .replace('{displayed}', String(columns.length))
          .replace('{total}', String(redactedColumnCount))
    : t('structured.preview.descIdle');
  const previewWarning = Boolean(preview && redactedColumnCount > 0 && previewStats.changedRedactedColumnCount === 0);
  return (
    <Card className="page-surface flex min-h-0 flex-col border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">{t('structured.preview.title')}</CardTitle>
        <CardDescription>{previewDescription}</CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 px-4 pb-3 pt-0">
        {!preview ? (
          <EmptyState icon={Eye} text={loading ? t('structured.preview.emptyLoading') : t('structured.preview.emptyIdle')} />
        ) : (
          <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_minmax(0,1fr)] gap-2">
            <PreviewValidationStrip
              columnCount={columns.length}
              displayedRedactedColumnCount={previewStats.displayedRedactedColumnCount}
              totalRedactedColumnCount={redactedColumnCount}
              hiddenRedactedColumnCount={previewStats.hiddenRedactedColumnCount}
              changedColumnCount={previewStats.changedColumns.size}
              changedRedactedColumnCount={previewStats.changedRedactedColumnCount}
              changedCellCount={previewStats.changedCellCount}
              changedRedactedCellCount={previewStats.changedRedactedCellCount}
              warning={previewWarning}
            />
            <PreviewTable title={t('structured.preview.original')} columns={columns} rows={preview.original_rows} />
            <PreviewTable
              title={t('structured.preview.redacted')}
              columns={columns}
              rows={preview.redacted_rows}
              muted
              compareRows={preview.original_rows}
              changedColumns={previewStats.changedColumns}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PreviewValidationStrip({
  columnCount,
  displayedRedactedColumnCount,
  totalRedactedColumnCount,
  hiddenRedactedColumnCount,
  changedColumnCount,
  changedRedactedColumnCount,
  changedCellCount,
  changedRedactedCellCount,
  warning,
}: {
  columnCount: number;
  displayedRedactedColumnCount: number;
  totalRedactedColumnCount: number;
  hiddenRedactedColumnCount: number;
  changedColumnCount: number;
  changedRedactedColumnCount: number;
  changedCellCount: number;
  changedRedactedCellCount: number;
  warning: boolean;
}) {
  const t = useT();
  return (
    <div
      className={cn(
        'flex min-h-9 flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-1.5 text-xs',
        warning
          ? 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]'
          : 'border-[var(--success-border)] bg-[var(--success-surface)] text-[var(--success-foreground)]',
      )}
      data-testid="preview-validation"
      data-preview-changed-columns={changedColumnCount}
      data-preview-changed-redacted-columns={changedRedactedColumnCount}
      data-preview-changed-cells={changedCellCount}
      data-preview-changed-redacted-cells={changedRedactedCellCount}
    >
      <span className="font-semibold">
        {warning ? t('structured.preview.checkNeeded') : t('structured.preview.validated')}
      </span>
      <span className="flex flex-wrap items-center gap-2 text-muted-foreground">
        <span>{t('structured.preview.columnsShown').replace('{count}', String(columnCount))}</span>
        <span>
          {t('structured.preview.redactedColumns')
            .replace('{displayed}', String(displayedRedactedColumnCount))
            .replace('{total}', String(totalRedactedColumnCount))}
        </span>
        <span>
          {t('structured.preview.redactedChanges')
            .replace('{changed}', String(changedRedactedColumnCount))
            .replace('{total}', String(totalRedactedColumnCount))}
        </span>
        <span>{t('structured.preview.changedColumns').replace('{count}', String(changedColumnCount))}</span>
        <span>{t('structured.preview.changedCells').replace('{count}', String(changedCellCount))}</span>
        {hiddenRedactedColumnCount > 0 ? (
          <span>{t('structured.preview.hiddenColumns').replace('{count}', String(hiddenRedactedColumnCount))}</span>
        ) : null}
      </span>
      {warning ? <span className="basis-full text-[11px]">{t('structured.preview.noChangeWarning')}</span> : null}
    </div>
  );
}

function PreviewTable({
  title,
  columns,
  rows,
  muted,
  compareRows,
  changedColumns,
}: {
  title: string;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  muted?: boolean;
  compareRows?: Array<Record<string, unknown>>;
  changedColumns?: Set<string>;
}) {
  return (
    <div className="min-h-0 min-w-0 overflow-hidden rounded-xl border border-border">
      <div className={cn('border-b border-border px-3 py-2 text-sm font-medium', muted && 'bg-muted/40')}>
        {title}
      </div>
      <div className="overflow-hidden">
        <table className="w-full table-fixed text-xs">
          <thead className="sticky top-0 bg-muted text-muted-foreground">
            <tr>
              {columns.map((column) => (
                <th key={column} className="px-2 py-2 text-left">
                  <span className="block truncate" title={column}>
                    {column}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 5).map((row, index) => (
              <tr key={index} className="border-t border-border">
                {columns.map((column) => {
                  const value = displayValue(row[column]);
                  const changed =
                    Boolean(muted && compareRows && changedColumns?.has(column)) &&
                    displayValue(compareRows?.[index]?.[column]) !== value;
                  return (
                    <td
                      key={column}
                      className={cn('px-2 py-2', changed && 'bg-[var(--success-surface)]')}
                      data-preview-changed={changed ? 'true' : undefined}
                    >
                      <span className="block truncate" title={value}>
                        {value}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
