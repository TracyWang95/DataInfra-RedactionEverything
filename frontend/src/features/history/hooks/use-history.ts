// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useMemo } from 'react';
import { t } from '@/i18n';
import type { FileListItem } from '@/types';
import { useHistoryActions } from './use-history-actions';
import { useHistoryCompare } from './use-history-compare';
import { useHistoryData, type SourceTab } from './use-history-data';
import { useHistoryFilters } from './use-history-filters';

export const PAGE_SIZE_OPTIONS = [10, 20] as const;

export type { SourceTab } from './use-history-data';
export type { DateFilter, FileTypeFilter, StatusFilter } from './use-history-filters';

export type HistoryGroup =
  | { kind: 'standalone'; row: FileListItem }
  | { kind: 'batch'; batch_group_id: string; batch_group_count: number; rows: FileListItem[] }
  | { kind: 'date_group'; label: string; rows: FileListItem[] };

function getHistoryBatchGroupId(row: FileListItem): string | null {
  if (row.upload_source !== 'batch' && !row.batch_group_id) return null;
  return row.batch_group_id ?? row.job_id ?? row.file_id;
}

export function buildHistoryGroups(rows: FileListItem[], sourceTab: SourceTab): HistoryGroup[] {
  if (sourceTab === 'playground') {
    return rows.map((r) => ({
      kind: 'date_group' as const,
      label: t('history.singleSession').replace('{id}', r.file_id.slice(0, 8)),
      rows: [r],
    }));
  }
  const out: HistoryGroup[] = [];
  let i = 0;
  while (i < rows.length) {
    const r = rows[i];
    const bg = getHistoryBatchGroupId(r);
    if (!bg) {
      out.push({
        kind: 'date_group',
        label: t('history.singleSession').replace('{id}', r.file_id.slice(0, 8)),
        rows: [r],
      });
      i++;
      continue;
    }
    const block: FileListItem[] = [r];
    let j = i + 1;
    while (j < rows.length && getHistoryBatchGroupId(rows[j]) === bg) {
      block.push(rows[j]);
      j++;
    }
    out.push({
      kind: 'batch',
      batch_group_id: bg,
      batch_group_count: r.batch_group_count ?? block.length,
      rows: block,
    });
    i = j;
  }
  return out;
}

/* Hook */

export function useHistory() {
  const data = useHistoryData();
  const filters = useHistoryFilters({ rows: data.rows });
  const compare = useHistoryCompare();

  const { filteredRows } = filters;
  const { selected, sourceTab, setExpandedBatchIds, knownBatchIdsRef } = data;

  useEffect(() => {
    const visibleBatchIds = new Set<string>();
    for (const row of filteredRows) {
      const batchGroupId = getHistoryBatchGroupId(row);
      if (batchGroupId) visibleBatchIds.add(batchGroupId);
    }

    const previousKnownBatchIds = knownBatchIdsRef.current;
    setExpandedBatchIds((prev) => {
      let changed = false;
      const next = new Set<string>();
      for (const batchGroupId of prev) {
        if (visibleBatchIds.has(batchGroupId)) next.add(batchGroupId);
        else changed = true;
      }
      for (const batchGroupId of visibleBatchIds) {
        if (!previousKnownBatchIds.has(batchGroupId)) {
          next.add(batchGroupId);
          changed = true;
        }
      }
      if (next.size !== prev.size) changed = true;
      return changed ? next : prev;
    });
    knownBatchIdsRef.current = visibleBatchIds;
  }, [filteredRows, knownBatchIdsRef, setExpandedBatchIds]);

  const selectedIds = filteredRows.filter((r) => selected.has(r.file_id)).map((r) => r.file_id);
  const historyGroups = useMemo(
    () => buildHistoryGroups(filteredRows, sourceTab),
    [filteredRows, sourceTab],
  );

  const allSelected = filteredRows.length > 0 && selectedIds.length === filteredRows.length;

  const actions = useHistoryActions({
    rows: data.rows,
    selectedIds,
    page: data.page,
    pageSize: data.pageSize,
    load: data.load,
    setMsg: data.setMsg,
    setRows: data.setRows,
    setTotal: data.setTotal,
    setListStats: data.setListStats,
    setPage: data.setPage,
    setSelected: data.setSelected,
  });

  return {
    /* list data */
    rows: data.rows,
    filteredRows,
    total: data.total,
    page: data.page,
    pageSize: data.pageSize,
    displayPageSize: data.displayPageSize,
    totalPages: data.totalPages,
    historyGroups,
    statsData: data.statsData,
    /* loading */
    initialLoading: data.initialLoading,
    tableLoading: data.tableLoading,
    refreshing: data.refreshing,
    zipLoading: actions.zipLoading,
    mutationLoading: actions.mutationLoading,
    interactionLocked: actions.zipLoading,
    /* selection */
    selected: data.selected,
    setSelected: data.setSelected,
    selectedIds,
    allSelected,
    toggle: data.toggle,
    /* filters */
    sourceTab: data.sourceTab,
    changeSourceTab: data.changeSourceTab,
    dateFilter: filters.dateFilter,
    setDateFilter: filters.setDateFilter,
    fileTypeFilter: filters.fileTypeFilter,
    setFileTypeFilter: filters.setFileTypeFilter,
    statusFilter: filters.statusFilter,
    setStatusFilter: filters.setStatusFilter,
    hasActiveFilter: filters.hasActiveFilter,
    clearFilters: filters.clearFilters,
    /* pagination */
    goPage: data.goPage,
    changePageSize: data.changePageSize,
    /* actions */
    load: data.load,
    downloadZip: actions.downloadZip,
    downloadRow: actions.downloadRow,
    remove: actions.remove,
    removeGroup: actions.removeGroup,
    toggleBatchCollapse: data.toggleBatchCollapse,
    expandedBatchIds: data.expandedBatchIds,
    /* cleanup */
    cleanupConfirmOpen: actions.cleanupConfirmOpen,
    setCleanupConfirmOpen: actions.setCleanupConfirmOpen,
    handleCleanup: actions.handleCleanup,
    /* messages */
    msg: data.msg,
    /* compare */
    compareOpen: compare.compareOpen,
    compareTarget: compare.compareTarget,
    compareLoading: compare.compareLoading,
    compareErr: compare.compareErr,
    compareData: compare.compareData,
    compareBlobUrls: compare.compareBlobUrls,
    compareTab: compare.compareTab,
    setCompareTab: compare.setCompareTab,
    comparePreviewItems: compare.comparePreviewItems,
    comparePage: compare.comparePage,
    setComparePage: compare.setComparePage,
    compareTotalPages: compare.compareTotalPages,
    openCompareModal: compare.openCompareModal,
    closeCompareModal: compare.closeCompareModal,
    /* confirm dialog */
    confirmDlg: actions.confirmDlg,
    setConfirmDlg: actions.setConfirmDlg,
  };
}
