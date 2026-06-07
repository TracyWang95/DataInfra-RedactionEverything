// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { PaginationRail } from '@/components/PaginationRail';
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
  rangeStart: _rangeStart,
  rangeEnd: _rangeEnd,
  jumpPage: _jumpPage,
  tableBusy,
  onGoPage,
  onChangePageSize,
  onJumpPageChange: _onJumpPageChange,
}: JobsPaginationProps) {
  const t = useT();

  return (
    <PaginationRail
      page={page}
      pageSize={pageSize}
      totalItems={total}
      totalPages={totalPages}
      onPageChange={(nextPage) => {
        if (tableBusy) return;
        onGoPage(nextPage);
      }}
      onPageSizeChange={(size) => {
        if (tableBusy) return;
        onChangePageSize(size);
      }}
      pageSizeOptions={PAGE_SIZE_OPTIONS}
      rangeLabel={t('jobs.showRange')}
      perPageLabel={t('jobs.perPage')}
      itemsUnitLabel={t('jobs.itemsUnit')}
      compact
      disabled={tableBusy}
      reserveWhenEmpty
      className="jobs-pagination-rail !min-h-10 !rounded-xl border-border/70 bg-muted/40"
    />
  );
}
