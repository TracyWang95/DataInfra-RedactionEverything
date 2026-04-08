// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * Centralized query-key factory for @tanstack/react-query.
 *
 * Grouping all keys here prevents typo-based cache misses and makes
 * invalidation / prefetching discoverable in one place.
 *
 * Convention:
 *   queryKeys.<domain>.all()        → list / collection queries
 *   queryKeys.<domain>.detail(id)   → single-resource queries
 *   queryKeys.<domain>.list(params) → filtered / paginated lists
 *
 * All factories return `readonly` tuples so TypeScript catches accidental mutation.
 */

export const queryKeys = {
  // ── Jobs ──────────────────────────────────────────────────────────────────
  jobs: {
    all: () => ['jobs'] as const,
    list: (filters?: { status?: string; page?: number }) =>
      ['jobs', 'list', filters] as const,
    detail: (jobId: string) => ['jobs', jobId] as const,
  },

  // ── Files ─────────────────────────────────────────────────────────────────
  files: {
    all: () => ['files'] as const,
    list: (params?: { page?: number; source?: string; jobId?: string }) =>
      ['files', 'list', params] as const,
    detail: (fileId: string) => ['files', fileId] as const,
  },

  // ── Entity types ──────────────────────────────────────────────────────────
  entityTypes: {
    all: () => ['entityTypes'] as const,
    list: (opts?: { enabledOnly?: boolean }) =>
      ['entityTypes', 'list', opts] as const,
    detail: (typeId: string) => ['entityTypes', typeId] as const,
  },

  // ── Settings / config ─────────────────────────────────────────────────────
  settings: {
    all: () => ['settings'] as const,
    nerBackend: () => ['settings', 'nerBackend'] as const,
    visionModels: () => ['settings', 'visionModels'] as const,
    replacementModes: () => ['settings', 'replacementModes'] as const,
  },

  // ── Presets ───────────────────────────────────────────────────────────────
  presets: {
    all: () => ['presets'] as const,
  },

  // ── Batch preview entity map ─────────────────────────────────────────────
  batchPreview: {
    /** Key for a specific entity-set + replacement-mode combination. */
    entityMap: (contentHash: string) =>
      ['batchPreview', 'entityMap', contentHash] as const,
  },
} as const;
