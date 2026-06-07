// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { ChevronsLeft, ChevronsRight } from 'lucide-react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

type PaginationRailProps = {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  pageSizeOptions?: readonly number[];
  rangeLabel?: string;
  perPageLabel?: string;
  itemsUnitLabel?: string;
  className?: string;
  compact?: boolean;
  disabled?: boolean;
  reserveWhenEmpty?: boolean;
  testIdPrefix?: string;
};

export function PaginationRail({
  page,
  pageSize,
  totalItems,
  totalPages,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions,
  rangeLabel,
  perPageLabel,
  itemsUnitLabel,
  className,
  compact = false,
  disabled = false,
  reserveWhenEmpty = false,
  testIdPrefix,
}: PaginationRailProps) {
  const t = useT();

  if (totalItems <= 0 && !reserveWhenEmpty) return null;

  const safeTotalItems = Math.max(0, totalItems);
  const safeTotalPages = Math.max(1, totalPages);
  const safePageSize = Math.max(1, pageSize);
  const safePage = Math.min(Math.max(1, page), safeTotalPages);
  const hasItems = safeTotalItems > 0;
  const rangeStart = hasItems ? (safePage - 1) * safePageSize + 1 : 0;
  const rangeEnd = hasItems ? Math.min(safeTotalItems, safePage * safePageSize) : 0;
  const pageButtonDisabled = disabled || !hasItems;
  const rangeTemplate = rangeLabel ?? t('jobs.showRange');
  const pageSizeUnit = itemsUnitLabel ?? t('jobs.itemsUnit');
  const getTestId = (suffix: string) => (testIdPrefix ? `${testIdPrefix}-${suffix}` : undefined);
  const formatPageSizeOption = (size: number) => `${size} ${pageSizeUnit}`.trim();

  return (
    <div
      className={cn(
        'pagination-rail overflow-x-auto overflow-y-hidden',
        compact && 'pagination-rail--compact',
        className,
      )}
      data-testid="pagination-rail"
    >
      <div className="pagination-rail__meta">
        <div className="pagination-rail__meta-group">
          <span className="block min-w-0 truncate whitespace-nowrap tabular-nums">
            {rangeTemplate
              .replace('{start}', String(rangeStart))
              .replace('{end}', String(rangeEnd))
              .replace('{total}', String(safeTotalItems))}
          </span>
          <span className="pagination-rail__separator">|</span>
        </div>
        <span className="pagination-rail__pill tabular-nums">
          {safePage} / {safeTotalPages}
        </span>
        {onPageSizeChange && pageSizeOptions && pageSizeOptions.length > 0 && (
          <div className="pagination-rail__meta-group shrink-0">
            <span className="pagination-rail__separator">|</span>
            <span className="shrink-0 whitespace-nowrap">{perPageLabel ?? t('jobs.perPage')}</span>
            <Select
              value={String(safePageSize)}
              disabled={disabled}
              onValueChange={(value) => onPageSizeChange(Number(value))}
            >
              <SelectTrigger
                className={cn(
                  'pagination-rail__page-size h-9 w-[5.75rem] shrink-0 justify-between rounded-xl text-xs tabular-nums',
                  compact && 'h-8 w-[5.25rem] rounded-lg text-[11px]',
                )}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {pageSizeOptions.map((size) => (
                    <SelectItem key={size} value={String(size)}>
                      {formatPageSizeOption(size)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      <div className="pagination-rail__actions">
        <Button
          variant="outline"
          size="sm"
          disabled={pageButtonDisabled || safePage <= 1}
          onClick={() => onPageChange(1)}
          title={t('jobs.firstPage')}
          className={cn('size-8 rounded-xl p-0', compact && 'size-7 rounded-lg')}
          data-testid={getTestId('first')}
        >
          <ChevronsLeft data-icon="inline-start" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={pageButtonDisabled || safePage <= 1}
          onClick={() => onPageChange(safePage - 1)}
          className={cn(
            'h-8 min-w-14 rounded-xl whitespace-nowrap',
            compact && 'h-7 min-w-11 rounded-lg px-2 text-[10px]',
          )}
          data-testid={getTestId('prev')}
        >
          {t('jobs.prevPage')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={pageButtonDisabled || safePage >= safeTotalPages}
          onClick={() => onPageChange(safePage + 1)}
          className={cn(
            'h-8 min-w-14 rounded-xl whitespace-nowrap',
            compact && 'h-7 min-w-11 rounded-lg px-2 text-[10px]',
          )}
          data-testid={getTestId('next')}
        >
          {t('jobs.nextPage')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={pageButtonDisabled || safePage >= safeTotalPages}
          onClick={() => onPageChange(safeTotalPages)}
          title={t('jobs.lastPage')}
          className={cn('size-8 rounded-xl p-0', compact && 'size-7 rounded-lg')}
          data-testid={getTestId('last')}
        >
          <ChevronsRight data-icon="inline-start" />
        </Button>
      </div>
    </div>
  );
}
