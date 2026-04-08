// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { ArrowLeftRight, Download, Trash2 } from 'lucide-react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import type { FileListItem } from '@/types';
import { BADGE_BASE, getRedactionStateLabel, REDACTION_STATE_CLASS, resolveRedactionState } from '@/utils/redactionState';

interface HistoryTableProps {
  rows: FileListItem[];
  loading: boolean;
  selected: Set<string>;
  onToggle: (id: string) => void;
  allSelected: boolean;
  onSelectAll: (checked: boolean) => void;
  onDownload: (row: FileListItem) => void;
  onDelete: (row: FileListItem) => void;
  onCompare: (row: FileListItem) => void;
}

export function HistoryTable({
  rows,
  loading,
  selected,
  onToggle,
  allSelected,
  onSelectAll,
  onDownload,
  onDelete,
  onCompare,
}: HistoryTableProps) {
  const t = useT();
  const getFileTypeLabel = (value: string) => {
    if (value === 'word' || value === 'doc' || value === 'docx') return t('file.word');
    if (value === 'pdf' || value === 'pdf_scanned') return t('file.pdf');
    if (value === 'image') return t('file.image');
    return value;
  };

  if (loading) {
    return (
      <div className="space-y-2 p-4 pb-10">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (rows.length === 0) {
    return <EmptyState title={t('emptyState.noFiles')} description={t('emptyState.noFilesDesc')} />;
  }

  return (
    <div className="page-surface-body" data-testid="history-table">
      <table className="w-full min-w-[980px] text-sm">
        <thead>
          <tr className="border-b border-border/70 bg-muted/30 text-left text-xs font-medium text-muted-foreground">
            <th className="w-10 px-4 py-3">
              <Checkbox checked={allSelected} onCheckedChange={(value) => onSelectAll(!!value)} data-testid="history-select-all" />
            </th>
            <th className="px-4 py-3">{t('history.col.filename')}</th>
            <th className="hidden px-4 py-3 sm:table-cell">{t('history.fileType')}</th>
            <th className="hidden px-4 py-3 md:table-cell">{t('history.col.entities')}</th>
            <th className="hidden px-4 py-3 md:table-cell">{t('history.col.status')}</th>
            <th className="hidden px-4 py-3 lg:table-cell">{t('history.col.time')}</th>
            <th className="px-4 py-3 text-right">{t('history.col.actions')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const state = resolveRedactionState(row.has_output, row.item_status);

            return (
              <tr
                key={row.file_id}
                className="border-b border-border/70 transition-colors hover:bg-muted/40"
                data-testid={`history-row-${row.file_id}`}
              >
                <td className="px-4 py-3.5">
                  <Checkbox checked={selected.has(row.file_id)} onCheckedChange={() => onToggle(row.file_id)} />
                </td>
                <td className="max-w-[260px] px-4 py-3.5 font-medium">
                  <div className="truncate">{row.original_filename}</div>
                </td>
                <td className="hidden px-4 py-3.5 sm:table-cell">
                  <Badge variant="secondary" className="rounded-full text-[10px]">
                    {getFileTypeLabel(row.file_type)}
                  </Badge>
                </td>
                <td className="hidden px-4 py-3.5 tabular-nums md:table-cell">{row.entity_count}</td>
                <td className="hidden px-4 py-3.5 md:table-cell">
                  <Badge className={cn(BADGE_BASE, REDACTION_STATE_CLASS[state])}>
                    {getRedactionStateLabel(state)}
                  </Badge>
                </td>
                <td className="hidden px-4 py-3.5 text-xs text-muted-foreground lg:table-cell">
                  {row.created_at ? new Date(row.created_at).toLocaleString() : '-'}
                </td>
                <td className="px-4 py-3.5">
                  <div className="flex items-center justify-end gap-1">
                    {row.has_output && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 rounded-xl"
                        onClick={() => onCompare(row)}
                        title={t('history.viewCompare')}
                        aria-label={t('history.viewCompare')}
                        data-testid={`compare-${row.file_id}`}
                      >
                        <ArrowLeftRight className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 rounded-xl"
                      onClick={() => onDownload(row)}
                      title={t('common.download')}
                      aria-label={t('common.download')}
                    >
                      <Download className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 rounded-xl text-destructive hover:text-destructive"
                      onClick={() => onDelete(row)}
                      title={t('common.delete')}
                      aria-label={t('common.delete')}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
