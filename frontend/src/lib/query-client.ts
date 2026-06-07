// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { keepPreviousData, QueryClient } from '@tanstack/react-query';
import { QUERY_GC_TIME_MS, QUERY_RETRY_COUNT, QUERY_STALE_TIME_MS } from '@/constants/timing';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Keep data fresh for 30 s so rapid page switches don't spam the backend,
      // but short enough that config changes are picked up without a manual refresh.
      staleTime: QUERY_STALE_TIME_MS,
      gcTime: QUERY_GC_TIME_MS,
      placeholderData: keepPreviousData,
      // A single retry catches transient network blips without masking real errors.
      retry: QUERY_RETRY_COUNT,
      // Disabled because the app already polls active resources; refetch-on-focus
      // would cause jarring UI flickers on tab switches.
      refetchOnWindowFocus: false,
    },
  },
});
