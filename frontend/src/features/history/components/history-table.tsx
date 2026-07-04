// Copyright 2026 DataInfra-RedactionEverything Contributors

import { ArrowLeftRight, ArrowRight, ChevronDown, ChevronRight, Download, Trash2 } from 'lucide-react';
import { memo, useMemo, useRef, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/EmptyState';
import {
  clampPageSize,
  interpolateDensity,
  useProportionalRowHeight,
} from '@/components/hooks/useProportionalRowHeight';
import type { FileListItem } from '@/types';
import {
  BADGE_BASE,
  getRedactionStateLabel,
  REDACTION_STATE_CLASS,
  resolveRedactionState,
} from '@/utils/redactionState';
import {
  buildJobPrimaryNavigationLabels,
  resolveJobPrimaryNavigation,
  type PrimaryNavAction,
} from '@/utils/jobPrimaryNavigation';

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

type HistoryTableDensity = {
  table: string;
  rowHeight: number;
  rowPaddingY: number;
  rowPaddingX: number;
  filenameSkeletonHeight: number;
  statusDetailMaxWidth: number;
  skeletonButtonSize: number;
  skeletonButtonRadius: number;
};

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

const HISTORY_ACTIVE_STATUSES = new Set([
  'pending',
  'queued',
  'running',
  'parsing',
  'ner',
  'vision',
  'processing',
  'redacting',
]);

type HistoryDeliveryState = {
  label: string;
  detail?: string;
  toneClass: string;
};

function formatCreatedAt(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString(undefined, {
    year: '2-digit',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getHistoryDeliveryState(
  row: FileListItem,
  t: (key: string) => string,
): HistoryDeliveryState {
  if (row.has_output) {
    return {
      label: t('redactionState.redacted'),
      toneClass: REDACTION_STATE_CLASS.redacted,
    };
  }

  const itemStatus = String(row.item_status ?? '').toLowerCase();
  if (itemStatus && HISTORY_ACTIVE_STATUSES.has(itemStatus)) {
    return {
      label: t('job.status.processing'),
      detail: t('jobs.processingEllipsis'),
      toneClass: REDACTION_STATE_CLASS.awaiting_review,
    };
  }

  if (itemStatus === 'awaiting_review' || itemStatus === 'review_approved') {
    return {
      label: t('job.status.awaiting_review'),
      toneClass: REDACTION_STATE_CLASS.awaiting_review,
    };
  }

  if (itemStatus === 'completed') {
    return {
      label: t('jobs.completed').replace('{n}', '1'),
      toneClass: REDACTION_STATE_CLASS.redacted,
    };
  }

  const state = resolveRedactionState(row.has_output, row.item_status);
  return {
    label: getRedactionStateLabel(state),
    toneClass: REDACTION_STATE_CLASS[state],
  };
}

function getHistoryFileTypeCategory(value: string): 'text' | 'image' | 'mixed' {
  if (value === 'image') return 'image';
  if (
    value === 'word' ||
    value === 'doc' ||
    value === 'docx' ||
    value === 'txt' ||
    value === 'pdf' ||
    value === 'pdf_scanned'
  ) {
    return 'text';
  }
  return 'mixed';
}

function getHistoryFileTypeLabel(value: string, t: (key: string) => string) {
  const category = getHistoryFileTypeCategory(String(value));
  if (category === 'text') return t('history.fileKindText');
  if (category === 'image') return t('history.fileKindImage');
  return t('history.fileKindMixed');
}

function getHistoryBatchFileTypeLabel(rows: FileListItem[], t: (key: string) => string) {
  const categories = new Set(
    rows.map((row) => {
      return getHistoryFileTypeCategory(String(row.file_type));
    }),
  );

  if (categories.size === 1 && categories.has('text')) return t('history.fileKindText');
  if (categories.size === 1 && categories.has('image')) return t('history.fileKindImage');
  return t('history.fileKindMixed');
}

function getHistoryBatchCountLabel(
  visibleCount: number,
  expectedCount: number,
  t: (key: string) => string,
) {
  const safeTotal = Math.max(expectedCount, visibleCount);
  if (safeTotal === visibleCount) {
    return t('history.filesCount').replace('{n}', String(safeTotal));
  }
  return t('history.batchVisibleCountCompact')
    .replace('{visible}', String(visibleCount))
    .replace('{total}', String(safeTotal));
}

function buildHistoryReviewAction(
  row: FileListItem,
  navLabels: ReturnType<typeof buildJobPrimaryNavigationLabels>,
): PrimaryNavAction {
  const embed = row.job_embed;
  if (!row.job_id || !embed || embed.status !== 'awaiting_review') return { kind: 'none' };
  const rowStatus = String(row.item_status ?? '').toLowerCase();
  if (rowStatus !== 'awaiting_review' && rowStatus !== 'review_approved') {
    return { kind: 'none' };
  }
  const items = [
    ...(row.item_id ? [{ id: row.item_id, status: rowStatus }] : []),
    ...(embed.items ?? []).filter((item) => item.id !== row.item_id),
  ];
  return resolveJobPrimaryNavigation({
    jobId: row.job_id,
    status: embed.status,
    jobType: embed.job_type,
    items,
    currentPage: 'other',
    navHints: {
      item_count: embed.progress?.total_items ?? items.length,
      first_awaiting_review_item_id:
        row.item_id && row.item_status === 'awaiting_review'
          ? row.item_id
          : embed.first_awaiting_review_item_id,
      wizard_furthest_step: embed.wizard_furthest_step,
      batch_step1_configured: embed.batch_step1_configured,
      awaiting_review_count: embed.progress?.awaiting_review,
      redacted_count: embed.progress?.completed,
    },
    labels: navLabels,
  });
}

const HISTORY_ACTION_ICON_BTN_BASE = 'size-7 rounded-lg shadow-none hover:translate-y-0';
const historyGridStyle: CSSProperties = {
  gridTemplateColumns:
    '32px minmax(220px,1.5fr) minmax(150px,0.72fr) minmax(52px,0.28fr) minmax(152px,0.78fr) minmax(124px,0.62fr) minmax(72px,0.36fr) minmax(58px,0.3fr) minmax(58px,0.3fr) minmax(58px,0.3fr)',
  columnGap: '10px',
};

type HistoryTableGroup =
  | { kind: 'single'; id: string; row: FileListItem }
  | {
      kind: 'batch';
      id: string;
      rows: FileListItem[];
      expectedCount: number;
    };

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

function getBatchSelectionState(rows: FileListItem[], selected: Set<string>) {
  const selectedCount = rows.reduce((count, row) => count + (selected.has(row.file_id) ? 1 : 0), 0);
  return {
    selectedCount,
    checked:
      selectedCount === 0 ? false : selectedCount === rows.length ? true : ('indeterminate' as const),
  };
}

type HistoryDataRowProps = {
  row: FileListItem;
  selected: boolean;
  treeLevel?: 'single' | 'batch-child';
  density: HistoryTableDensity;
  navLabels: ReturnType<typeof buildJobPrimaryNavigationLabels>;
  t: (key: string) => string;
  onToggle: (id: string) => void;
  onDownload: (row: FileListItem) => void;
  onDelete: (row: FileListItem) => void;
  onCompare: (row: FileListItem) => void;
};

const HistoryDataRow = memo(function HistoryDataRow({
  row,
  selected,
  treeLevel = 'single',
  density,
  navLabels,
  t,
  onToggle,
  onDownload,
  onDelete,
  onCompare,
}: HistoryDataRowProps) {
  const deliveryState = getHistoryDeliveryState(row, t);
  const reviewAction = buildHistoryReviewAction(row, navLabels);
  const actionIconBtnBase = cn(HISTORY_ACTION_ICON_BTN_BASE, density.rowHeight < 36 && 'size-6');
  const actionPlaceholder = (
    <span
      className={cn(
        'jobs-action-placeholder rounded-lg',
        density.rowHeight < 36 ? '!min-h-6' : '!min-h-7',
      )}
    />
  );

  return (
    <li
      className={cn(
        'shrink-0 transition-colors odd:bg-background even:bg-muted/[0.18] hover:bg-muted/40',
        treeLevel === 'batch-child' && 'bg-background/80',
      )}
    >
      <div
        className="jobs-row-main overflow-hidden px-3 py-2 sm:px-4"
        data-testid={`history-row-${row.file_id}`}
        style={{
          ...historyGridStyle,
          height: `${density.rowHeight}px`,
          minHeight: `${density.rowHeight}px`,
          paddingTop: `${density.rowPaddingY}px`,
          paddingBottom: `${density.rowPaddingY}px`,
        }}
      >
        <div className="jobs-tree-cell">
          <Checkbox
            checked={selected}
            onCheckedChange={() => onToggle(row.file_id)}
            aria-label={t('history.selectFile').replace('{name}', row.original_filename)}
          />
        </div>

        <div className="jobs-task-cell min-w-0">
          <div
            className={cn(
              'flex min-w-0 items-center gap-2',
              treeLevel === 'batch-child' && 'pl-24',
            )}
          >
            {treeLevel === 'batch-child' ? (
              <span className="h-px w-4 shrink-0 bg-border" aria-hidden />
            ) : (
              <Badge
                variant="secondary"
                className="text-2xs shrink-0 rounded-full px-2 py-0.5"
              >
                {t('history.tab.playground')}
              </Badge>
            )}
            <p className="min-w-0 truncate text-sm font-medium" title={row.original_filename}>
              {row.original_filename}
            </p>
          </div>
        </div>

        <div className="jobs-exec-cell hidden min-w-0 flex-nowrap items-center gap-2 md:flex">
          <Badge
            variant="secondary"
            className="text-2xs rounded-full whitespace-nowrap px-2 py-0.5"
          >
            {getHistoryFileTypeLabel(row.file_type, t)}
          </Badge>
        </div>

        <div className="hidden whitespace-nowrap text-caption tabular-nums text-muted-foreground md:block">
          {row.entity_count}
        </div>

        <div className="jobs-status-cell hidden min-w-0 flex-nowrap items-center gap-1.5 md:flex">
          <div className="flex min-w-0 flex-nowrap items-center gap-1.5">
            <Badge
              className={cn(BADGE_BASE, 'shrink-0 whitespace-nowrap', deliveryState.toneClass)}
              data-testid={`history-status-${row.file_id}`}
            >
              {deliveryState.label}
            </Badge>
            {deliveryState.detail ? (
              <span
                className="min-w-0 truncate whitespace-nowrap text-2xs text-muted-foreground"
                style={{ maxWidth: `${density.statusDetailMaxWidth}px` }}
                data-testid={`history-status-detail-${row.file_id}`}
              >
                {deliveryState.detail}
              </span>
            ) : null}
          </div>
        </div>

        <div
          className="jobs-updated-cell hidden text-caption text-muted-foreground tabular-nums whitespace-nowrap md:block"
          title={row.created_at ? new Date(row.created_at).toLocaleString() : '-'}
        >
          {formatCreatedAt(row.created_at)}
        </div>

        <div className="jobs-action-cell">
          {reviewAction.kind === 'link' && (
            <Button
              variant="outline"
              size="icon"
              className={cn(actionIconBtnBase, 'bg-background hover:bg-muted')}
              title={t('history.continueReview')}
              aria-label={t('history.continueReview')}
              asChild
            >
              <Link to={reviewAction.to} data-testid={`continue-review-${row.file_id}`}>
                <ArrowRight data-icon="inline-end" />
              </Link>
            </Button>
          )}
          {reviewAction.kind !== 'link' ? actionPlaceholder : null}
        </div>
        <div className="jobs-action-cell">
          {row.has_output && (
            <Button
              variant="outline"
              size="icon"
              className={cn(actionIconBtnBase, 'bg-background hover:bg-muted')}
              onClick={() => onCompare(row)}
              title={t('history.viewCompare')}
              aria-label={t('history.viewCompare')}
              data-testid={`compare-${row.file_id}`}
            >
              <ArrowLeftRight data-icon="inline-start" />
            </Button>
          )}
          {!row.has_output ? actionPlaceholder : null}
        </div>
        <div className="jobs-action-cell">
          <Button
            variant="outline"
            size="icon"
            className={cn(actionIconBtnBase, 'bg-background hover:bg-muted')}
            onClick={() => onDownload(row)}
            title={t('common.download')}
            aria-label={t('common.download')}
          >
            <Download data-icon="inline-start" />
          </Button>
        </div>
        <div className="jobs-action-cell">
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              actionIconBtnBase,
              'border border-transparent text-muted-foreground hover:border-[var(--error-border)] hover:bg-[var(--error-surface)] hover:text-[var(--error-foreground)]',
            )}
            onClick={() => onDelete(row)}
            title={t('common.delete')}
            aria-label={t('common.delete')}
          >
            <Trash2 data-icon="inline-start" />
          </Button>
        </div>
      </div>
    </li>
  );
});

type HistoryBatchRowProps = {
  group: Extract<HistoryTableGroup, { kind: 'batch' }>;
  collapsed: boolean;
  selected: Set<string>;
  density: HistoryTableDensity;
  navLabels: ReturnType<typeof buildJobPrimaryNavigationLabels>;
  t: (key: string) => string;
  onToggleCollapse?: (batchGroupId: string) => void;
  onSelectGroup?: (ids: string[], checked: boolean) => void;
  onDeleteGroup?: (rows: FileListItem[]) => void;
};

const HistoryBatchRow = memo(function HistoryBatchRow({
  group,
  collapsed,
  selected,
  density,
  navLabels,
  t,
  onToggleCollapse,
  onSelectGroup,
  onDeleteGroup,
}: HistoryBatchRowProps) {
  const rows = group.rows;
  const ids = rows.map((row) => row.file_id);
  const selectionState = getBatchSelectionState(rows, selected);
  const entityCount = rows.reduce((sum, row) => sum + (row.entity_count || 0), 0);
  const redactedCount = rows.filter((row) => row.has_output).length;
  const awaitingReviewCount = rows.filter((row) => {
    const status = String(row.item_status ?? '').toLowerCase();
    return status === 'awaiting_review' || status === 'review_approved';
  }).length;
  const latestCreatedAt = rows.reduce<string | null>((latest, row) => {
    if (!row.created_at) return latest;
    if (!latest) return row.created_at;
    return new Date(row.created_at).getTime() > new Date(latest).getTime() ? row.created_at : latest;
  }, null);
  const deliveryState =
    redactedCount === rows.length
      ? {
          label: t('history.allRedacted'),
          toneClass: REDACTION_STATE_CLASS.redacted,
        }
      : awaitingReviewCount > 0
        ? {
            label: t('job.status.awaiting_review'),
            toneClass: REDACTION_STATE_CLASS.awaiting_review,
          }
      : redactedCount > 0
        ? {
            label: t('history.partialRedacted'),
            toneClass: REDACTION_STATE_CLASS.awaiting_review,
          }
        : {
            label: t('history.unredactedStatus'),
            toneClass: REDACTION_STATE_CLASS.unredacted,
          };
  const reviewAction = rows
    .map((row) => buildHistoryReviewAction(row, navLabels))
    .find((action) => action.kind === 'link');
  const actionIconBtnBase = cn(HISTORY_ACTION_ICON_BTN_BASE, density.rowHeight < 36 && 'size-6');
  const actionPlaceholder = (
    <span
      className={cn(
        'jobs-action-placeholder rounded-lg',
        density.rowHeight < 36 ? '!min-h-6' : '!min-h-7',
      )}
    />
  );
  const batchCountLabel = getHistoryBatchCountLabel(rows.length, group.expectedCount, t);
  const selectedCountLabel =
    selectionState.selectedCount > 0
      ? t('history.selectedCountShort').replace('{n}', String(selectionState.selectedCount))
      : '';
  const batchFileTypeLabel = getHistoryBatchFileTypeLabel(rows, t);
  const batchLabel = t('history.batchGroup').replace('{id}', group.id.slice(0, 8));
  const batchTitle = [batchLabel, batchCountLabel, selectedCountLabel].filter(Boolean).join(' · ');

  return (
    <li className="shrink-0 bg-muted/30 transition-colors hover:bg-muted/45">
      <div
        className="jobs-row-main overflow-hidden px-3 py-2 sm:px-4"
        data-testid={`history-batch-row-${group.id}`}
        style={{
          ...historyGridStyle,
          height: `${density.rowHeight}px`,
          minHeight: `${density.rowHeight}px`,
          paddingTop: `${density.rowPaddingY}px`,
          paddingBottom: `${density.rowPaddingY}px`,
        }}
      >
        <div className="jobs-tree-cell">
          <Checkbox
            checked={selectionState.checked}
            onCheckedChange={(value) => onSelectGroup?.(ids, value === true)}
            aria-label={t('history.selectAllGroup')}
            data-testid={`history-batch-select-${group.id}`}
          />
        </div>

        <div className="jobs-task-cell min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="size-6 shrink-0 rounded-md text-muted-foreground hover:bg-background"
              onClick={() => onToggleCollapse?.(group.id)}
              aria-expanded={!collapsed}
              aria-label={batchLabel}
              data-testid={`history-batch-toggle-${group.id}`}
            >
              {collapsed ? (
                <ChevronRight className="size-3.5" />
              ) : (
                <ChevronDown className="size-3.5" />
              )}
            </Button>
            <div className="flex min-w-0 items-center gap-2">
              <p className="min-w-0 truncate text-sm font-semibold" title={batchTitle}>
                {batchLabel}
              </p>
              <span className="shrink-0 rounded-full border border-border/70 bg-background/70 px-2 py-0.5 text-2xs font-medium text-muted-foreground">
                {batchCountLabel}
              </span>
              {selectedCountLabel ? (
                <span className="shrink-0 rounded-full border border-border/70 bg-muted/40 px-2 py-0.5 text-2xs font-medium text-muted-foreground">
                  {selectedCountLabel}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div
          className="jobs-exec-cell hidden min-w-0 flex-nowrap items-center gap-2 md:flex"
          title={batchFileTypeLabel}
        >
          <Badge
            variant="secondary"
            className="text-2xs rounded-full whitespace-nowrap px-2 py-0.5"
            data-testid={`history-batch-file-kind-${group.id}`}
          >
            {batchFileTypeLabel}
          </Badge>
        </div>

        <div className="hidden whitespace-nowrap text-caption tabular-nums text-muted-foreground md:block">
          {entityCount}
        </div>

        <div className="jobs-status-cell hidden min-w-0 flex-nowrap items-center gap-1.5 md:flex">
          <Badge className={cn(BADGE_BASE, 'shrink-0 whitespace-nowrap', deliveryState.toneClass)}>
            {deliveryState.label}
          </Badge>
        </div>

        <div
          className="jobs-updated-cell hidden text-caption text-muted-foreground tabular-nums whitespace-nowrap md:block"
          title={latestCreatedAt ? new Date(latestCreatedAt).toLocaleString() : '-'}
        >
          {formatCreatedAt(latestCreatedAt)}
        </div>

        <div className="jobs-action-cell">
          {reviewAction?.kind === 'link' && (
            <Button
              variant="outline"
              size="icon"
              className={cn(actionIconBtnBase, 'bg-background hover:bg-muted')}
              title={t('history.continueReview')}
              aria-label={t('history.continueReview')}
              asChild
            >
              <Link to={reviewAction.to} data-testid={`continue-review-batch-${group.id}`}>
                <ArrowRight data-icon="inline-end" />
              </Link>
            </Button>
          )}
          {reviewAction?.kind !== 'link' ? actionPlaceholder : null}
        </div>
        <div className="jobs-action-cell">{actionPlaceholder}</div>
        <div className="jobs-action-cell">{actionPlaceholder}</div>
        <div className="jobs-action-cell">
          {onDeleteGroup ? (
            <Button
              variant="ghost"
              size="icon"
              className={cn(
                actionIconBtnBase,
                'border border-transparent text-muted-foreground hover:border-[var(--error-border)] hover:bg-[var(--error-surface)] hover:text-[var(--error-foreground)]',
              )}
              onClick={() => onDeleteGroup(rows)}
              title={t('history.deleteGroupBtn')}
              aria-label={t('history.deleteGroupBtn')}
            >
              <Trash2 data-icon="inline-start" />
            </Button>
          ) : (
            actionPlaceholder
          )}
        </div>
      </div>
    </li>
  );
});

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
