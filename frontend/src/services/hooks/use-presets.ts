// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchPresets,
  createPreset,
  updatePreset,
  deletePreset,
  type PresetPayload,
  type RecognitionPreset,
} from '@/services/presetsApi';
import { queryKeys } from '@/lib/query-keys';

/** Shared query-key constant so invalidation is consistent across the app. */
export const PRESETS_QUERY_KEY = queryKeys.presets.all();

// ── Queries ────────────────────────────────────────────────────────────────

/** Fetch all recognition presets with caching via react-query. */
export function usePresets() {
  return useQuery<RecognitionPreset[]>({
    queryKey: PRESETS_QUERY_KEY,
    queryFn: fetchPresets,
  });
}

/** Returns a callback to invalidate the presets cache. */
export function useInvalidatePresets() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: PRESETS_QUERY_KEY });
}

// ── Mutations ──────────────────────────────────────────────────────────────

/** Create a new preset and invalidate the presets cache on success. */
export function useCreatePreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PresetPayload) => createPreset(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PRESETS_QUERY_KEY });
    },
  });
}

/** Update an existing preset and invalidate the presets cache on success. */
export function useUpdatePreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<PresetPayload> }) =>
      updatePreset(id, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PRESETS_QUERY_KEY });
    },
  });
}

/** Delete a preset and invalidate the presets cache on success. */
export function useDeletePreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deletePreset(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: PRESETS_QUERY_KEY });
    },
  });
}
