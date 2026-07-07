// Copyright 2026 DataInfra-RedactionEverything Contributors

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
import { useAuth } from '@/features/auth/auth-context';

/** Shared query-key constant so invalidation is consistent across the app. */
export const PRESETS_QUERY_KEY = queryKeys.presets.root();

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

// ── Mutations ──────────────────────────────────────────────────────────────

/** Create a new preset and invalidate the presets cache on success. */
export function useCreatePreset() {
  const qc = useQueryClient();
  const ownerKey = usePresetOwnerKey();
  return useMutation({
    mutationFn: (body: PresetPayload) => createPreset(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.presets.all(ownerKey) });
    },
  });
}

/** Update an existing preset and invalidate the presets cache on success. */
export function useUpdatePreset() {
  const qc = useQueryClient();
  const ownerKey = usePresetOwnerKey();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<PresetPayload> }) =>
      updatePreset(id, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.presets.all(ownerKey) });
    },
  });
}

/** Delete a preset and invalidate the presets cache on success. */
export function useDeletePreset() {
  const qc = useQueryClient();
  const ownerKey = usePresetOwnerKey();
  return useMutation({
    mutationFn: (id: string) => deletePreset(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.presets.all(ownerKey) });
    },
  });
}
