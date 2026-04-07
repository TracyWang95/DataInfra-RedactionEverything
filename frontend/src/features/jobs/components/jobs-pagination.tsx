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

  if (total <= 0) return null;

  return (
    <PaginationRail
      page={page}
      pageSize={pageSize}
      totalItems={total}
      totalPages={totalPages}
      onPageChange={onGoPage}
      onPageSizeChange={(size) => {
        if (tableBusy) return;
        onChangePageSize(size);
      }}
      pageSizeOptions={PAGE_SIZE_OPTIONS}
      perPageLabel={t('jobs.perPage')}
      itemsUnitLabel={t('jobs.itemsUnit')}
    />
  );
}
