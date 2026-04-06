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
  perPageLabel?: string;
  itemsUnitLabel?: string;
  className?: string;
  compact?: boolean;
};

export function PaginationRail({
  page,
  pageSize,
  totalItems,
  totalPages,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions,
  perPageLabel,
  itemsUnitLabel,
  className,
  compact = false,
}: PaginationRailProps) {
  const t = useT();

  if (totalItems <= 0) return null;

  const rangeStart = (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(totalItems, page * pageSize);

  return (
    <div
      className={cn(
        'pagination-rail',
        compact && 'pagination-rail--compact',
        className,
      )}
    >
      <div className="pagination-rail__meta">
        <div className="pagination-rail__meta-group">
          <span className="truncate">
            {t('jobs.showRange')
              .replace('{start}', String(rangeStart))
              .replace('{end}', String(rangeEnd))
              .replace('{total}', String(totalItems))}
          </span>
          <span className="pagination-rail__separator">|</span>
        </div>
        <span className="pagination-rail__pill">
          {page} / {totalPages}
        </span>
        {onPageSizeChange && pageSizeOptions && pageSizeOptions.length > 0 && (
          <div className="pagination-rail__meta-group">
            <span className="pagination-rail__separator">|</span>
            <span>{perPageLabel ?? t('jobs.perPage')}</span>
            <Select value={String(pageSize)} onValueChange={(value) => onPageSizeChange(Number(value))}>
              <SelectTrigger
                className={cn(
                  'pagination-rail__page-size h-9 rounded-xl text-xs',
                  compact && 'h-8 rounded-lg text-[11px]',
                )}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {pageSizeOptions.map((size) => (
                    <SelectItem key={size} value={String(size)}>
                      {size} {itemsUnitLabel ?? t('jobs.itemsUnit')}
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
          disabled={page <= 1}
          onClick={() => onPageChange(1)}
          title={t('jobs.firstPage')}
          className={cn('h-8 rounded-xl px-2.5', compact && 'h-6.5 rounded-lg px-2')}
        >
          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          className={cn('h-8 rounded-xl whitespace-nowrap', compact && 'h-6.5 rounded-lg px-2 text-[10px]')}
        >
          {t('jobs.prevPage')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          className={cn('h-8 rounded-xl whitespace-nowrap', compact && 'h-6.5 rounded-lg px-2 text-[10px]')}
        >
          {t('jobs.nextPage')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(totalPages)}
          title={t('jobs.lastPage')}
          className={cn('h-8 rounded-xl px-2.5', compact && 'h-6.5 rounded-lg px-2')}
        >
          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
          </svg>
        </Button>
      </div>
    </div>
  );
}
