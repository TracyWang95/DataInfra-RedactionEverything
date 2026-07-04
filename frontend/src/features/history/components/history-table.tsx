// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useMemo, useRef, type CSSProperties } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import {
  clampPageSize,
  interpolateDensity,
  useProportionalRowHeight,
} from '@/components/hooks/useProportionalRowHeight';
import type { FileListItem } from '@/types';
import { buildJobPrimaryNavigationLabels } from '@/utils/jobPrimaryNavigation';
import {
  HistoryBatchRow,
  HistoryDataRow,
  historyGridStyle,
  type HistoryTableDensity,
  type HistoryTableGroup,
} from './history-row';

interface HistoryTableProps {
  rows: FileListItem[];
  loading: boolean;
  refreshing?: boolean;
  tableLoading?: boolean;
  pageSize: number;
  selected: Set<string>;
  onToggle: (id: string) => void;
  allSelected: boolean;
  onSelectAll: (checked: boolean) => void;
  expandedBatchIds?: Set<string>;
  onToggleBatchCollapse?: (batchGroupId: string) => void;
  onSelectGroup?: (ids: string[], checked: boolean) => void;
  onDownload: (row: FileListItem) => void;
  onDelete: (row: FileListItem) => void;
  onDeleteGroup?: (rows: FileListItem[]) => void;
  onCompare: (row: FileListItem) => void;
}

const HISTORY_MIN_PAGE_SIZE = 10;
const HISTORY_MAX_PAGE_SIZE = 20;
const HISTORY_TABLE_MIN_PADDING_Y = 3;
const HISTORY_TABLE_MAX_PADDING_Y = 8;
const HISTORY_TABLE_MIN_PADDING_X = 10;
const HISTORY_TABLE_MAX_PADDING_X = 16;
const HISTORY_FILENAME_SKELETON_MIN_HEIGHT = 14;
const HISTORY_FILENAME_SKELETON_MAX_HEIGHT = 16;
const HISTORY_STATUS_DETAIL_MIN_WIDTH = 160;
const HISTORY_STATUS_DETAIL_MAX_WIDTH = 176;
const HISTORY_SKELETON_BUTTON_SIZE = 24;
const HISTORY_SKELETON_BUTTON_RADIUS = 8;

function normalizeHistoryPageSize(pageSize: number): number {
  return clampPageSize(pageSize, HISTORY_MIN_PAGE_SIZE, HISTORY_MAX_PAGE_SIZE);
}

function getHistoryTableDensity(pageSize: number, rowHeight: number): HistoryTableDensity {
  const interpolate = interpolateDensity(pageSize, HISTORY_MIN_PAGE_SIZE, HISTORY_MAX_PAGE_SIZE);

  return {
    table: 'min-w-[1080px]',
    rowHeight,
    rowPaddingY: Math.max(
      0,
      Math.min(
        interpolate(HISTORY_TABLE_MAX_PADDING_Y, HISTORY_TABLE_MIN_PADDING_Y),
        rowHeight * 0.08,
      ),
    ),
    rowPaddingX: interpolate(HISTORY_TABLE_MAX_PADDING_X, HISTORY_TABLE_MIN_PADDING_X),
    filenameSkeletonHeight: interpolate(
      HISTORY_FILENAME_SKELETON_MAX_HEIGHT,
      HISTORY_FILENAME_SKELETON_MIN_HEIGHT,
    ),
    statusDetailMaxWidth: interpolate(
      HISTORY_STATUS_DETAIL_MAX_WIDTH,
      HISTORY_STATUS_DETAIL_MIN_WIDTH,
    ),
    skeletonButtonSize: HISTORY_SKELETON_BUTTON_SIZE,
    skeletonButtonRadius: HISTORY_SKELETON_BUTTON_RADIUS,
  };
}

function getHistorySkeletonCount(pageSize: number): number {
  return normalizeHistoryPageSize(pageSize);
}

function getRowBatchGroupId(row: FileListItem): string | null {
  if (row.upload_source !== 'batch' && !row.batch_group_id) return null;
  return row.batch_group_id ?? row.job_id ?? row.file_id;
}

function buildHistoryTableGroups(rows: FileListItem[]): HistoryTableGroup[] {
  const out: HistoryTableGroup[] = [];
  const batchGroups = new Map<string, Extract<HistoryTableGroup, { kind: 'batch' }>>();

  for (const row of rows) {
    const batchGroupId = getRowBatchGroupId(row);
    if (!batchGroupId) {
      out.push({ kind: 'single', id: row.file_id, row });
      continue;
    }

    const existing = batchGroups.get(batchGroupId);
    if (existing) {
      existing.rows.push(row);
      existing.expectedCount = Math.max(
        existing.expectedCount,
        row.batch_group_count ?? existing.rows.length,
      );
      continue;
    }

    const group: Extract<HistoryTableGroup, { kind: 'batch' }> = {
      kind: 'batch',
      id: batchGroupId,
      rows: [row],
      expectedCount: row.batch_group_count ?? 1,
    };
    batchGroups.set(batchGroupId, group);
    out.push(group);
  }

  return out;
}

function getVisibleHistoryRowCount(
  groups: HistoryTableGroup[],
  expandedBatchIds?: Set<string>,
): number {
  return groups.reduce((count, group) => {
    if (group.kind === 'single') return count + 1;
    const collapsed = expandedBatchIds ? !expandedBatchIds.has(group.id) : false;
    return count + 1 + (collapsed ? 0 : group.rows.length);
  }, 0);
}

export function HistoryTable({
  rows,
  loading,
  refreshing = false,
  tableLoading = false,
  pageSize,
  selected,
  onToggle,
  allSelected,
  onSelectAll,
  expandedBatchIds,
  onToggleBatchCollapse,
  onSelectGroup,
  onDownload,
  onDelete,
  onDeleteGroup,
  onCompare,
}: HistoryTableProps) {
  const t = useT();
  const bodyRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const rowHeight = useProportionalRowHeight({
    pageSize,
    minPageSize: HISTORY_MIN_PAGE_SIZE,
    maxPageSize: HISTORY_MAX_PAGE_SIZE,
    bodyRef,
    headRef,
    subtractRowDividers: true,
  });
  const density = useMemo(() => getHistoryTableDensity(pageSize, rowHeight), [pageSize, rowHeight]);
  const safePageSize = normalizeHistoryPageSize(pageSize);
  const tableGroups = useMemo(() => buildHistoryTableGroups(rows), [rows]);
  const visibleRowCount = useMemo(
    () => getVisibleHistoryRowCount(tableGroups, expandedBatchIds),
    [expandedBatchIds, tableGroups],
  );
  const fillerRowCount = Math.max(0, safePageSize - visibleRowCount);
  const bodyStyle: CSSProperties = {
    height: 0,
    minHeight: 0,
    overscrollBehavior: 'contain',
    scrollbarGutter: 'stable',
  };
  const hardLoading = loading && rows.length === 0;
  const showEmptyState = !hardLoading && rows.length === 0;
  const navLabels = useMemo(() => buildJobPrimaryNavigationLabels(t), [t]);

  return (
    <div
      className="page-surface-body relative min-h-0 flex-1 overflow-x-auto overflow-y-auto"
      ref={bodyRef}
      style={bodyStyle}
      data-testid="history-table"
      aria-busy={loading || refreshing || tableLoading}
    >
      {showEmptyState ? (
        <div
          className="flex min-h-full items-center justify-center px-4"
          data-testid="history-table-empty"
        >
          <EmptyState title={t('emptyState.noFiles')} description={t('emptyState.noFilesDesc')} />
        </div>
      ) : (
        <div
          className={cn('flex min-w-full flex-col', density.table)}
          data-testid="history-table-grid"
        >
          <div
            className="jobs-table-head shrink-0 border-b border-border/70 bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground sm:px-4"
            ref={headRef}
            style={historyGridStyle}
          >
            <span className="jobs-tree-cell">
              <Checkbox
                checked={allSelected}
                disabled={hardLoading}
                onCheckedChange={(value) => onSelectAll(!!value)}
                data-testid="history-select-all"
              />
            </span>
            <span className="jobs-task-cell">{t('history.col.filename')}</span>
            <span className="jobs-exec-cell">{t('history.fileType')}</span>
            <span>{t('history.col.entities')}</span>
            <span className="jobs-status-cell">{t('history.col.status')}</span>
            <span className="jobs-updated-cell">{t('history.col.time')}</span>
            <span className="jobs-action-column-head">{t('history.continueReview')}</span>
            <span className="jobs-action-column-head">{t('history.compareActionHeader')}</span>
            <span className="jobs-action-column-head">{t('common.download')}</span>
            <span className="jobs-action-column-head">{t('common.delete')}</span>
          </div>

          <ul className="jobs-table-list flex min-h-full min-w-full flex-col divide-y divide-border/70">
            {hardLoading
              ? Array.from({ length: getHistorySkeletonCount(pageSize) }).map((_, index) => (
                  <li
                    key={index}
                    className="jobs-row-main overflow-hidden px-3 py-2 sm:px-4"
                    style={{
                      ...historyGridStyle,
                      height: `${density.rowHeight}px`,
                      minHeight: `${density.rowHeight}px`,
                      paddingTop: `${density.rowPaddingY}px`,
                      paddingBottom: `${density.rowPaddingY}px`,
                    }}
                  >
                    <div className="jobs-tree-cell">
                      <Skeleton className="size-4 rounded" />
                    </div>
                    <div className="jobs-task-cell min-w-0">
                      <Skeleton
                        className="max-w-full rounded-full"
                        style={{ height: `${density.filenameSkeletonHeight}px` }}
                      />
                    </div>
                    <div className="hidden md:block">
                      <Skeleton className="h-5 w-16 rounded-full" />
                    </div>
                    <div className="hidden md:block">
                      <Skeleton className="h-4 w-8 rounded-full" />
                    </div>
                    <div className="hidden md:block">
                      <Skeleton className="h-5 w-20 rounded-full" />
                    </div>
                    <div className="hidden md:block">
                      <Skeleton className="h-4 w-32 rounded-full" />
                    </div>
                    {Array.from({ length: 4 }).map((_, actionIndex) => (
                      <div className="jobs-action-cell" key={actionIndex}>
                        <Skeleton
                          className="rounded-lg"
                          style={{
                            width: `${density.skeletonButtonSize}px`,
                            height: `${density.skeletonButtonSize}px`,
                            borderRadius: `${density.skeletonButtonRadius}px`,
                          }}
                        />
                      </div>
                    ))}
                  </li>
                ))
              : tableGroups.flatMap((group) => {
                  if (group.kind === 'single') {
                    return [
                      <HistoryDataRow
                        key={group.row.file_id}
                        row={group.row}
                        selected={selected.has(group.row.file_id)}
                        treeLevel="single"
                        density={density}
                        navLabels={navLabels}
                        t={t}
                        onToggle={onToggle}
                        onDownload={onDownload}
                        onDelete={onDelete}
                        onCompare={onCompare}
                      />,
                    ];
                  }

                  const collapsed = expandedBatchIds ? !expandedBatchIds.has(group.id) : false;
                  const renderedRows = [
                    <HistoryBatchRow
                      key={`batch-${group.id}`}
                      group={group}
                      collapsed={collapsed}
                      selected={selected}
                      density={density}
                      navLabels={navLabels}
                      t={t}
                      onToggleCollapse={onToggleBatchCollapse}
                      onSelectGroup={onSelectGroup}
                      onDeleteGroup={onDeleteGroup}
                    />,
                  ];

                  if (!collapsed) {
                    renderedRows.push(
                      ...group.rows.map((row) => (
                        <HistoryDataRow
                          key={row.file_id}
                          row={row}
                          selected={selected.has(row.file_id)}
                          treeLevel="batch-child"
                          density={density}
                          navLabels={navLabels}
                          t={t}
                          onToggle={onToggle}
                          onDownload={onDownload}
                          onDelete={onDelete}
                          onCompare={onCompare}
                        />
                      )),
                    );
                  }

                  return renderedRows;
                })}
            {!hardLoading &&
              Array.from({ length: fillerRowCount }).map((_, index) => (
                <li
                  key={`history-filler-${index}`}
                  className="shrink-0 bg-background"
                  style={{
                    height: `${density.rowHeight}px`,
                    minHeight: `${density.rowHeight}px`,
                  }}
                  aria-hidden
                />
              ))}
          </ul>
        </div>
      )}
    </div>
  );
}
