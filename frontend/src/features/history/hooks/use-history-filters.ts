// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useMemo, useState } from 'react';
import { resolveRedactionState } from '@/utils/redactionState';
import type { FileListItem } from '@/types';

export type DateFilter = 'all' | '7d' | '30d';
export type FileTypeFilter = 'all' | 'word' | 'pdf' | 'image';
export type StatusFilter = 'all' | 'redacted' | 'awaiting_review' | 'unredacted';

export interface UseHistoryFiltersOptions {
  /** Current page rows to derive the filtered view from */
  rows: FileListItem[];
}

export function useHistoryFilters({ rows }: UseHistoryFiltersOptions) {
  const [dateFilter, setDateFilter] = useState<DateFilter>('all');
  const [fileTypeFilter, setFileTypeFilter] = useState<FileTypeFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  const filteredRows = useMemo(() => {
    let result = rows;
    if (dateFilter !== 'all') {
      const now = Date.now();
      const days = dateFilter === '7d' ? 7 : 30;
      const cutoff = now - days * 24 * 60 * 60 * 1000;
      result = result.filter((r) => r.created_at && new Date(r.created_at).getTime() >= cutoff);
    }
    if (fileTypeFilter !== 'all') {
      result = result.filter((r) => {
        const ft = String(r.file_type).toLowerCase();
        if (fileTypeFilter === 'word') return ft === 'docx' || ft === 'doc';
        if (fileTypeFilter === 'pdf') return ft === 'pdf' || ft === 'pdf_scanned';
        if (fileTypeFilter === 'image') return ft === 'image';
        return true;
      });
    }
    if (statusFilter !== 'all') {
      result = result.filter(
        (r) => resolveRedactionState(r.has_output, r.item_status) === statusFilter,
      );
    }
    return result;
  }, [rows, dateFilter, fileTypeFilter, statusFilter]);

  const hasActiveFilter =
    dateFilter !== 'all' || fileTypeFilter !== 'all' || statusFilter !== 'all';
  const clearFilters = useCallback(() => {
    setDateFilter('all');
    setFileTypeFilter('all');
    setStatusFilter('all');
  }, []);

  return {
    dateFilter,
    setDateFilter,
    fileTypeFilter,
    setFileTypeFilter,
    statusFilter,
    setStatusFilter,
    filteredRows,
    hasActiveFilter,
    clearFilters,
  };
}
