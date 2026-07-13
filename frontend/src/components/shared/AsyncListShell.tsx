// Copyright 2026 DataInfra-RedactionEverything Contributors

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface AsyncListShellProps {
  /** First load with no data yet: render the skeleton. */
  hardLoading: boolean;
  skeleton: ReactNode;
  /** No rows after loading settled: render the empty content. */
  isEmpty: boolean;
  emptyContent: ReactNode;
  /** Soft refresh with data on screen: floating pill overlay. */
  refreshing?: boolean;
  refreshingLabel?: string;
  className?: string;
  testId?: string;
  children: ReactNode;
}

/**
 * Shared async-list state shell (3b 收编): one place owns the
 * hardLoading -> empty -> content precedence, aria-busy and the refresh
 * overlay that batch-hub / jobs / history each re-implemented.
 * Row markup stays with the callers - only the state composition is shared.
 */
export function AsyncListShell({
  hardLoading,
  skeleton,
  isEmpty,
  emptyContent,
  refreshing = false,
  refreshingLabel,
  className,
  testId,
  children,
}: AsyncListShellProps) {
  const showOverlay = refreshing && !hardLoading && !isEmpty;
  return (
    <div
      className={cn('relative flex min-h-0 flex-col', className)}
      aria-busy={hardLoading || refreshing}
      data-testid={testId}
    >
      {showOverlay ? (
        <div
          className="table-refresh-overlay pointer-events-none !right-3 !top-2"
          role="status"
          aria-label={refreshingLabel}
          data-testid={testId ? `${testId}-refresh-overlay` : undefined}
        >
          <span className="table-refresh-pill !px-2.5 !py-1 !text-xs shadow-sm">
            <span className="size-3.5 animate-spin rounded-full border-2 border-border border-t-primary" />
            {refreshingLabel}
          </span>
        </div>
      ) : null}
      {hardLoading ? skeleton : isEmpty ? emptyContent : children}
    </div>
  );
}
