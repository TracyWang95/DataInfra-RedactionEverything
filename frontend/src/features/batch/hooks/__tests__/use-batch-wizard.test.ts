// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';

// ── Mocks ──────────────────────────────────────────────────────────────────

vi.mock('@/services/recognition-config', () => ({
  fetchRecognitionEntityTypes: vi.fn(),
  fetchRecognitionPipelines: vi.fn(),
  fetchRecognitionPresets: vi.fn(),
}));

vi.mock('@/services/batchPipeline', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/batchPipeline')>();
  return {
    ...actual,
    loadBatchWizardConfig: vi.fn(() => null),
    saveBatchWizardConfig: vi.fn(),
    batchGetFileRaw: vi.fn().mockResolvedValue({}),
  };
});

vi.mock('@/services/activePresetBridge', () => ({
  getActivePresetTextId: vi.fn(() => null),
  getActivePresetVisionId: vi.fn(() => null),
  setActivePresetTextId: vi.fn(),
  setActivePresetVisionId: vi.fn(),
}));

vi.mock('@/services/presetsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/presetsApi')>();
  return { ...actual };
});

vi.mock('@/services/jobsApi', () => ({
  createJob: vi.fn().mockResolvedValue({ id: 'new-job-1' }),
  getJob: vi.fn().mockResolvedValue({
    id: 'job-1',
    job_type: 'smart_batch',
    status: 'draft',
    config: {},
    items: [],
    nav_hints: {},
  }),
  updateJobDraft: vi.fn().mockResolvedValue({}),
  putItemReviewDraft: vi.fn().mockResolvedValue({}),
  getItemReviewDraft: vi.fn().mockResolvedValue(null),
}));

vi.mock('@/services/api', () => ({
  fileApi: vi.fn(),
  authenticatedBlobUrl: vi.fn().mockResolvedValue(''),
}));

vi.mock('@/services/api-client', () => ({
  authFetch: vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }),
}));

vi.mock('@/services/defaultRedactionPreset', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/defaultRedactionPreset')>();
  return { ...actual };
});

vi.mock('@/services/hooks/use-presets', () => ({
  usePresets: vi.fn(() => ({ data: [], isLoading: false, error: null })),
  useInvalidatePresets: vi.fn(() => vi.fn().mockResolvedValue(undefined)),
  PRESETS_QUERY_KEY: ['presets'],
}));

vi.mock('@/i18n', () => ({ t: (k: string) => k }));

vi.mock('@/utils/localizeError', () => ({
  localizeErrorMessage: (_e: unknown, key: string) => key,
}));

vi.mock('@/utils/textRedactionSegments', () => ({
  buildTextSegments: vi.fn(() => []),
  mergePreviewMapWithDocumentSlices: vi.fn(() => ({})),
}));

vi.mock('../use-batch-review-data', () => ({
  useBatchReviewData: vi.fn(() => ({
    loadReviewData: vi.fn(),
    rerunCurrentItemRecognition: vi.fn(),
    rerunRecognitionLoading: false,
    reviewImagePreviewLoading: false,
  })),
}));

import {
  fetchRecognitionEntityTypes,
  fetchRecognitionPipelines,
  fetchRecognitionPresets,
} from '@/services/recognition-config';
import { createJob } from '@/services/jobsApi';
import type { TextEntityType, PipelineCfg } from '../../types';
import { useBatchWizard } from '../use-batch-wizard';

// ── Test fixtures ──────────────────────────────────────────────────────────

function makeTextTypes(count = 5): TextEntityType[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `TYPE_${i + 1}`,
    name: `Type ${i + 1}`,
    color: '#0f766e',
    regex_pattern: i < 3 ? '\\d+' : null,
    order: i + 1,
  }));
}

function makePipelines(): PipelineCfg[] {
  return [
    {
      mode: 'ocr_has',
      name: 'OCR',
      description: 'OCR pipeline',
      enabled: true,
      types: [
        { id: 'ocr_1', name: 'OCR Type 1', color: '#0f766e', enabled: true, order: 1 },
      ],
    },
    {
      mode: 'has_image',
      name: 'Image',
      description: 'Image pipeline',
      enabled: true,
      types: [
        { id: 'img_1', name: 'Image Type 1', color: '#b45309', enabled: true, order: 1 },
      ],
    },
  ];
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function setupMocks(
  types: TextEntityType[] = makeTextTypes(),
  pipes: PipelineCfg[] = makePipelines(),
) {
  (fetchRecognitionEntityTypes as Mock).mockResolvedValue(types);
  (fetchRecognitionPipelines as Mock).mockResolvedValue(pipes);
  (fetchRecognitionPresets as Mock).mockResolvedValue([]);
}

/**
 * Creates a wrapper that uses createMemoryRouter + RouterProvider.
 * useBlocker (used in useBatchWizard) requires a data router.
 */
function wrapperWithRoute(path: string) {
  return ({ children }: { children: React.ReactNode }) => {
    const router = createMemoryRouter(
      [{ path: '/batch/:batchMode', element: children }],
      { initialEntries: [path] },
    );
    return createElement(RouterProvider, { router });
  };
}

const defaultWrapper = wrapperWithRoute('/batch/smart');

// ── Tests ───────────────────────────────────────────────────────────────────

describe('useBatchWizard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    localStorage.clear();
  });

  // ── Initial state ──

  describe('initial state', () => {
    it('starts at step 1', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.step).toBe(1);
    });

    it('furthestStep starts at 1', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.furthestStep).toBe(1);
    });

    it('activeJobId starts null', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.activeJobId).toBeNull();
    });

    it('previewMode starts false (no ?preview=1)', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.previewMode).toBe(false);
    });

    it('mode defaults to smart', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.mode).toBe('smart');
    });

    it('modeValid is true for known modes', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), {
        wrapper: wrapperWithRoute('/batch/text'),
      });
      expect(result.current.modeValid).toBe(true);
    });

    it('configLoaded starts false', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.configLoaded).toBe(false);
    });

    it('rows starts empty', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.rows).toEqual([]);
    });

    it('isStep1Complete starts false', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.isStep1Complete).toBe(false);
    });

    it('allReviewConfirmed starts false', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.allReviewConfirmed).toBe(false);
    });

    it('default cfg has expected shape', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.cfg).toHaveProperty('selectedEntityTypeIds');
      expect(result.current.cfg).toHaveProperty('replacementMode');
      expect(result.current.cfg.replacementMode).toBe('structured');
    });
  });

  // ── Step navigation (canGoStep / goStep) ──

  describe('step navigation', () => {
    it('canGoStep(1) is always true', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      expect(result.current.canGoStep(1)).toBe(true);
    });

    it('canGoStep(2) is false when step 1 is incomplete', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      // Without confirmStep1 being set, step1 is incomplete
      expect(result.current.canGoStep(2)).toBe(false);
    });

    it('canGoStep(2) is true when step 1 is complete', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      // After config loads, entity types are populated with defaults
      act(() => result.current.setConfirmStep1(true));
      expect(result.current.isStep1Complete).toBe(true);
      expect(result.current.canGoStep(2)).toBe(true);
    });

    it('goStep shows warning when advancing to step 2 without confirmation', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.goStep(2));

      // Step should remain 1 and a warning message should appear
      expect(result.current.step).toBe(1);
      expect(result.current.msg).not.toBeNull();
    });

    it('goStep(1) from step 1 is a no-op', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });

      act(() => result.current.goStep(1));

      expect(result.current.step).toBe(1);
    });
  });

  // ── Config persistence ──

  describe('config persistence', () => {
    it('setCfg updates the config', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => {
        result.current.setCfg(c => ({ ...c, replacementMode: 'mask' }));
      });

      expect(result.current.cfg.replacementMode).toBe('mask');
    });

    it('setConfirmStep1 toggles the confirmation flag', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.setConfirmStep1(true));
      expect(result.current.confirmStep1).toBe(true);

      act(() => result.current.setConfirmStep1(false));
      expect(result.current.confirmStep1).toBe(false);
    });

    it('setJobPriority updates jobPriority', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.setJobPriority(7));
      expect(result.current.jobPriority).toBe(7);
    });
  });

  // ── Preview mode ──

  describe('preview mode', () => {
    const previewWrapper = wrapperWithRoute('/batch/smart?preview=1');

    it('activates preview mode via ?preview=1', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: previewWrapper });
      expect(result.current.previewMode).toBe(true);
    });

    it('sets furthestStep to 5 in preview mode', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: previewWrapper });
      await waitFor(() => expect(result.current.furthestStep).toBe(5));
    });

    it('populates rows with preview fixtures', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: previewWrapper });
      await waitFor(() => expect(result.current.rows.length).toBeGreaterThan(0));
    });

    it('canGoStep returns true for any step in preview', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: previewWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      expect(result.current.canGoStep(1)).toBe(true);
      expect(result.current.canGoStep(3)).toBe(true);
      expect(result.current.canGoStep(5)).toBe(true);
    });
  });

  // ── advanceToUploadStep ──

  describe('advanceToUploadStep', () => {
    it('shows warning when config is not confirmed', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      await act(async () => {
        await result.current.advanceToUploadStep();
      });

      expect(result.current.step).toBe(1);
      expect(result.current.msg).not.toBeNull();
    });

    it('creates a job and advances to step 2 when config is complete', async () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.setConfirmStep1(true));
      expect(result.current.isStep1Complete).toBe(true);

      await act(async () => {
        await result.current.advanceToUploadStep();
      });

      expect(createJob).toHaveBeenCalled();
      expect(result.current.step).toBe(2);
      expect(result.current.activeJobId).toBe('new-job-1');
    });

    it('does not call createJob in preview mode', async () => {
      setupMocks();
      const previewWrapper = wrapperWithRoute('/batch/smart?preview=1&step=2');
      const { result } = renderHook(() => useBatchWizard(), { wrapper: previewWrapper });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      await waitFor(() => expect(result.current.step).toBe(2));

      // In preview mode, step advancement does not create a job
      expect(createJob).not.toHaveBeenCalled();
      expect(result.current.previewMode).toBe(true);
    });
  });

  // ── Review state pass-through ──

  describe('review state', () => {
    it('exposes reviewIndex starting at 0', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.reviewIndex).toBe(0);
    });

    it('exposes reviewEntities starting empty', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.reviewEntities).toEqual([]);
    });

    it('exposes reviewLoading starting false', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.reviewLoading).toBe(false);
    });

    it('exposes pendingReviewCount', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(typeof result.current.pendingReviewCount).toBe('number');
    });
  });

  // ── Export state ──

  describe('export state', () => {
    it('zipLoading starts false', () => {
      setupMocks();
      const { result } = renderHook(() => useBatchWizard(), { wrapper: defaultWrapper });
      expect(result.current.zipLoading).toBe(false);
    });
  });
});
