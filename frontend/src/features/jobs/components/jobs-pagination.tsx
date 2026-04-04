import { t } from '@/i18n';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { PAGE_SIZE_OPTIONS } from '../hooks/use-jobs';

type JobsPaginationProps = {
  page: number;
  pageSize: number;
  totalPages: number;
  total: number;
  rangeStart: number;
  rangeEnd: number;
  jumpPage: string;
  tableBusy: boolean;
  onGoPage: (page: number) => void;
  onChangePageSize: (size: number) => void;
  onJumpPageChange: (value: string) => void;
};

export function JobsPagination({
  page,
  pageSize,
  totalPages,
  total,
  rangeStart,
  rangeEnd,
  jumpPage,
  tableBusy,
  onGoPage,
  onChangePageSize,
  onJumpPageChange,
}: JobsPaginationProps) {
  if (total <= 0) return null;

  return (
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-border/70 bg-muted/25 px-4 py-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>
          {t('jobs.showRange')
            .replace('{start}', String(rangeStart))
            .replace('{end}', String(rangeEnd))
            .replace('{total}', String(total))}
        </span>
        <span className="text-border">|</span>
        <span>{t('jobs.perPage')}</span>
        <Select value={String(pageSize)} onValueChange={(value) => onChangePageSize(Number(value))}>
          <SelectTrigger className="h-8 min-w-[86px] rounded-xl text-xs" data-testid="jobs-page-size-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PAGE_SIZE_OPTIONS.map((size) => (
              <SelectItem key={size} value={String(size)}>
                {size} {t('jobs.itemsUnit')}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-1.5">
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1 || tableBusy}
          onClick={() => onGoPage(1)}
          title={t('jobs.firstPage')}
          data-testid="jobs-first-page"
          className="h-8 rounded-xl px-2.5"
        >
          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </Button>

        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1 || tableBusy}
          onClick={() => onGoPage(page - 1)}
          data-testid="jobs-prev-page"
          className="h-8 rounded-xl"
        >
          {t('jobs.prevPage')}
        </Button>

        <div className="flex items-center gap-1 px-1">
          <Input
            type="text"
            value={jumpPage}
            onChange={(event) => onJumpPageChange(event.target.value.replace(/\D/g, ''))}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return;
              const next = Number.parseInt(jumpPage, 10);
              if (next >= 1 && next <= totalPages) {
                onGoPage(next);
                onJumpPageChange('');
              }
            }}
            placeholder={String(page)}
            className="h-8 w-11 rounded-xl text-center text-xs"
            data-testid="jobs-jump-page"
          />
          <span className="text-xs text-muted-foreground">/ {totalPages}</span>
        </div>

        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages || tableBusy}
          onClick={() => onGoPage(page + 1)}
          data-testid="jobs-next-page"
          className="h-8 rounded-xl"
        >
          {t('jobs.nextPage')}
        </Button>

        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages || tableBusy}
          onClick={() => onGoPage(totalPages)}
          title={t('jobs.lastPage')}
          data-testid="jobs-last-page"
          className="h-8 rounded-xl px-2.5"
        >
          <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
          </svg>
        </Button>
      </div>
    </div>
  );
}
