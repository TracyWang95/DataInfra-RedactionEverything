// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchPresets, type RecognitionPreset } from '@/services/presetsApi';
import { queryKeys } from '@/lib/query-keys';
import { useAuth } from '@/features/auth/auth-context';

function usePresetOwnerKey(): string {
  const { status } = useAuth();
  return status?.authenticated && status.username ? status.username.toLowerCase() : 'anonymous';
}

// ── Queries ────────────────────────────────────────────────────────────────

/** Fetch all recognition presets with caching via react-query. */
export function usePresets() {
  const ownerKey = usePresetOwnerKey();
  return useQuery<RecognitionPreset[]>({
    queryKey: queryKeys.presets.all(ownerKey),
    queryFn: fetchPresets,
  });
}

/** Returns a callback to invalidate the presets cache. */
export function useInvalidatePresets() {
  const qc = useQueryClient();
  const ownerKey = usePresetOwnerKey();
  return () => qc.invalidateQueries({ queryKey: queryKeys.presets.all(ownerKey) });
}
