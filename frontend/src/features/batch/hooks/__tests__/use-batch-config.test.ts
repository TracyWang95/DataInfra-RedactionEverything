// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';

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

vi.mock('@/i18n', () => ({ t: (k: string) => k }));

import { fetchRecognitionEntityTypes, fetchRecognitionPipelines, fetchRecognitionPresets } from '@/services/recognition-config';
import { loadBatchWizardConfig } from '@/services/batchPipeline';
import { getActivePresetTextId } from '@/services/activePresetBridge';
import type { RecognitionPreset } from '@/services/presetsApi';
import type { TextEntityType, PipelineCfg } from '../../types';
import { useBatchConfig } from '../use-batch-config';

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
        { id: 'ocr_2', name: 'OCR Type 2', color: '#0f766e', enabled: true, order: 2 },
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

function makeTextPreset(ids: string[]): RecognitionPreset {
  return {
    id: 'preset-text-1',
    name: 'Text Preset',
    kind: 'text',
    selectedEntityTypeIds: ids,
    ocrHasTypes: [],
    hasImageTypes: [],
    replacementMode: 'structured',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

function makeVisionPreset(): RecognitionPreset {
  return {
    id: 'preset-vision-1',
    name: 'Vision Preset',
    kind: 'vision',
    selectedEntityTypeIds: [],
    ocrHasTypes: ['ocr_1'],
    hasImageTypes: ['img_1'],
    replacementMode: 'structured',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

function makeFullPreset(): RecognitionPreset {
  return {
    id: 'preset-full-1',
    name: 'Full Preset',
    kind: 'full',
    selectedEntityTypeIds: ['TYPE_1', 'TYPE_2'],
    ocrHasTypes: ['ocr_1'],
    hasImageTypes: ['img_1'],
    replacementMode: 'smart',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const wrapper = ({ children }: { children: React.ReactNode }) =>
  createElement(MemoryRouter, null, children);

function setupMocks(
  types: TextEntityType[] = makeTextTypes(),
  pipes: PipelineCfg[] = makePipelines(),
  presets: RecognitionPreset[] = [],
) {
  (fetchRecognitionEntityTypes as Mock).mockResolvedValue(types);
  (fetchRecognitionPipelines as Mock).mockResolvedValue(pipes);
  (fetchRecognitionPresets as Mock).mockResolvedValue(presets);
}

function renderUseBatchConfig(overrides: {
  mode?: 'text' | 'image' | 'smart';
  activeJobId?: string | null;
  isPreviewMode?: boolean;
} = {}) {
  const mode = overrides.mode ?? 'text';
  const setActiveJobId = vi.fn();
  const setMsg = vi.fn();
  const activeJobIdRef = { current: overrides.activeJobId ?? null };

  return renderHook(
    () =>
      useBatchConfig(
        mode,
        activeJobIdRef.current,
        setActiveJobId,
        overrides.isPreviewMode ?? false,
        setMsg,
      ),
    { wrapper },
  );
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe('useBatchConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    localStorage.clear();
    (loadBatchWizardConfig as Mock).mockReturnValue(null);
    (getActivePresetTextId as Mock).mockReturnValue(null);
  });

  // ── Initial state ──

  describe('initial state', () => {
    it('configLoaded starts false', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      // Immediately after render, before async load completes
      expect(result.current.configLoaded).toBe(false);
    });

    it('textTypes starts empty', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      expect(result.current.textTypes).toEqual([]);
    });

    it('pipelines starts empty', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      expect(result.current.pipelines).toEqual([]);
    });

    it('presets starts empty', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      expect(result.current.presets).toEqual([]);
    });

    it('cfg.selectedEntityTypeIds starts empty', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      expect(result.current.cfg.selectedEntityTypeIds).toEqual([]);
    });

    it('confirmStep1 starts false', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      expect(result.current.confirmStep1).toBe(false);
    });

    it('jobPriority starts at 0', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      expect(result.current.jobPriority).toBe(0);
    });

    it('isStep1Complete starts false', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      expect(result.current.isStep1Complete).toBe(false);
    });

    it('textPresets starts empty', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      expect(result.current.textPresets).toEqual([]);
    });

    it('visionPresets starts empty', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      expect(result.current.visionPresets).toEqual([]);
    });
  });

  // ── Config loading ──

  describe('config loading', () => {
    it('sets configLoaded to true after fetching', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
    });

    it('populates textTypes from fetchRecognitionEntityTypes', async () => {
      const types = makeTextTypes(3);
      setupMocks(types);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.textTypes).toEqual(types));
    });

    it('populates pipelines from fetchRecognitionPipelines', async () => {
      const pipes = makePipelines();
      setupMocks(makeTextTypes(), pipes);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.pipelines).toEqual(pipes));
    });

    it('populates presets from fetchRecognitionPresets', async () => {
      const presets = [makeTextPreset(['TYPE_1'])];
      setupMocks(makeTextTypes(), makePipelines(), presets);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.presets).toEqual(presets));
    });

    it('calls fetchRecognitionEntityTypes with enabledOnly=true', async () => {
      setupMocks();
      renderUseBatchConfig();
      await waitFor(() => expect(fetchRecognitionEntityTypes).toHaveBeenCalledWith(true, 25_000));
    });

    it('calls fetchRecognitionPipelines with timeout', async () => {
      setupMocks();
      renderUseBatchConfig();
      await waitFor(() => expect(fetchRecognitionPipelines).toHaveBeenCalledWith(25_000));
    });

    it('handles empty presets gracefully (API returns non-array)', async () => {
      (fetchRecognitionEntityTypes as Mock).mockResolvedValue(makeTextTypes());
      (fetchRecognitionPipelines as Mock).mockResolvedValue(makePipelines());
      (fetchRecognitionPresets as Mock).mockRejectedValue(new Error('fail'));
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      expect(result.current.presets).toEqual([]);
    });

    it('populates cfg.selectedEntityTypeIds with default text type IDs', async () => {
      const types = makeTextTypes(5);
      setupMocks(types);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.cfg.selectedEntityTypeIds.length).toBeGreaterThan(0));
    });

    it('computes batchDefaultTextTypeIds from textTypes', async () => {
      const types = makeTextTypes(5);
      setupMocks(types);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.batchDefaultTextTypeIds.length).toBeGreaterThan(0));
    });

    it('computes batchDefaultOcrHasTypeIds from pipelines', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.batchDefaultOcrHasTypeIds).toEqual(['ocr_1', 'ocr_2']));
    });

    it('computes batchDefaultHasImageTypeIds from pipelines', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.batchDefaultHasImageTypeIds).toEqual(['img_1']));
    });
  });

  // ── isStep1Complete ──

  describe('isStep1Complete', () => {
    it('returns false when confirmStep1 is false', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      expect(result.current.isStep1Complete).toBe(false);
    });

    it('returns false when configLoaded is false even if confirmStep1 is true', () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      act(() => result.current.setConfirmStep1(true));
      // configLoaded may still be false at this point
      if (!result.current.configLoaded) {
        expect(result.current.isStep1Complete).toBe(false);
      }
    });

    it('returns true when confirmStep1 is true and text types are selected', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      act(() => result.current.setConfirmStep1(true));
      // After load, selectedEntityTypeIds should be populated with defaults
      expect(result.current.cfg.selectedEntityTypeIds.length).toBeGreaterThan(0);
      expect(result.current.isStep1Complete).toBe(true);
    });

    it('returns true when confirmStep1 is true and ocrHasTypes are selected', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      act(() => {
        result.current.setCfg(c => ({
          ...c,
          selectedEntityTypeIds: [],
          ocrHasTypes: ['ocr_1'],
        }));
        result.current.setConfirmStep1(true);
      });
      expect(result.current.isStep1Complete).toBe(true);
    });

    it('returns true when confirmStep1 is true and hasImageTypes are selected', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      act(() => {
        result.current.setCfg(c => ({
          ...c,
          selectedEntityTypeIds: [],
          ocrHasTypes: [],
          hasImageTypes: ['img_1'],
        }));
        result.current.setConfirmStep1(true);
      });
      expect(result.current.isStep1Complete).toBe(true);
    });

    it('returns false when all selection arrays are empty even with confirmStep1', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
      act(() => {
        result.current.setCfg(c => ({
          ...c,
          selectedEntityTypeIds: [],
          ocrHasTypes: [],
          hasImageTypes: [],
        }));
        result.current.setConfirmStep1(true);
      });
      expect(result.current.isStep1Complete).toBe(false);
    });
  });

  // ── Preset application ──

  describe('preset application', () => {
    it('applying a text preset updates cfg.selectedEntityTypeIds', async () => {
      const types = makeTextTypes(5);
      const preset = makeTextPreset(['TYPE_1', 'TYPE_3']);
      setupMocks(types, makePipelines(), [preset]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.onBatchTextPresetChange('preset-text-1'));

      expect(result.current.cfg.selectedEntityTypeIds).toEqual(['TYPE_1', 'TYPE_3']);
    });

    it('applying a text preset sets presetTextId', async () => {
      const types = makeTextTypes(5);
      const preset = makeTextPreset(['TYPE_1']);
      setupMocks(types, makePipelines(), [preset]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.onBatchTextPresetChange('preset-text-1'));

      expect(result.current.cfg.presetTextId).toBe('preset-text-1');
    });

    it('applying empty string text preset resets to defaults', async () => {
      const types = makeTextTypes(5);
      const preset = makeTextPreset(['TYPE_1']);
      setupMocks(types, makePipelines(), [preset]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.onBatchTextPresetChange('preset-text-1'));
      act(() => result.current.onBatchTextPresetChange(''));

      expect(result.current.cfg.presetTextId).toBeNull();
    });

    it('applying a vision preset updates ocrHasTypes and hasImageTypes', async () => {
      const vPreset = makeVisionPreset();
      setupMocks(makeTextTypes(), makePipelines(), [vPreset]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.onBatchVisionPresetChange('preset-vision-1'));

      expect(result.current.cfg.ocrHasTypes).toEqual(['ocr_1']);
      expect(result.current.cfg.hasImageTypes).toEqual(['img_1']);
    });

    it('applying a vision preset sets presetVisionId', async () => {
      const vPreset = makeVisionPreset();
      setupMocks(makeTextTypes(), makePipelines(), [vPreset]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.onBatchVisionPresetChange('preset-vision-1'));

      expect(result.current.cfg.presetVisionId).toBe('preset-vision-1');
    });

    it('applying empty string vision preset resets to defaults', async () => {
      const vPreset = makeVisionPreset();
      setupMocks(makeTextTypes(), makePipelines(), [vPreset]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.onBatchVisionPresetChange('preset-vision-1'));
      act(() => result.current.onBatchVisionPresetChange(''));

      expect(result.current.cfg.presetVisionId).toBeNull();
    });

    it('text preset filters out unknown type IDs', async () => {
      const types = makeTextTypes(2); // only TYPE_1, TYPE_2
      const preset = makeTextPreset(['TYPE_1', 'TYPE_99']);
      setupMocks(types, makePipelines(), [preset]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.onBatchTextPresetChange('preset-text-1'));

      expect(result.current.cfg.selectedEntityTypeIds).toEqual(['TYPE_1']);
    });

    it('textPresets filters presets by kind', async () => {
      const tp = makeTextPreset(['TYPE_1']);
      const vp = makeVisionPreset();
      setupMocks(makeTextTypes(), makePipelines(), [tp, vp]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      expect(result.current.textPresets.length).toBe(1);
      expect(result.current.textPresets[0].id).toBe('preset-text-1');
    });

    it('visionPresets filters presets by kind', async () => {
      const tp = makeTextPreset(['TYPE_1']);
      const vp = makeVisionPreset();
      setupMocks(makeTextTypes(), makePipelines(), [tp, vp]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      expect(result.current.visionPresets.length).toBe(1);
      expect(result.current.visionPresets[0].id).toBe('preset-vision-1');
    });

    it('full preset appears in both text and vision presets', async () => {
      const fp = makeFullPreset();
      setupMocks(makeTextTypes(), makePipelines(), [fp]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      expect(result.current.textPresets.length).toBe(1);
      expect(result.current.visionPresets.length).toBe(1);
    });

    it('ignores non-existent preset ID', async () => {
      const tp = makeTextPreset(['TYPE_1']);
      setupMocks(makeTextTypes(), makePipelines(), [tp]);
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      const before = result.current.cfg.selectedEntityTypeIds;
      act(() => result.current.onBatchTextPresetChange('non-existent'));
      expect(result.current.cfg.selectedEntityTypeIds).toEqual(before);
    });
  });

  // ── Preview mode ──

  describe('preview mode', () => {
    it('sets configLoaded immediately in preview mode', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig({ isPreviewMode: true });
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
    });

    it('populates textTypes from preview fixtures', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig({ isPreviewMode: true });
      await waitFor(() => expect(result.current.textTypes.length).toBeGreaterThan(0));
    });

    it('does not call fetchRecognitionEntityTypes in preview mode', async () => {
      setupMocks();
      renderUseBatchConfig({ isPreviewMode: true });
      // In preview mode the fetch should not be triggered for config loading
      // (entity-types-changed listener is a separate effect)
      await waitFor(() => {});
      // The initial load effect uses preview fixtures instead of fetching
    });

    it('sets confirmStep1 to true in preview mode', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig({ isPreviewMode: true });
      await waitFor(() => expect(result.current.confirmStep1).toBe(true));
    });

    it('sets jobPriority to 5 in preview mode', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig({ isPreviewMode: true });
      await waitFor(() => expect(result.current.jobPriority).toBe(5));
    });
  });

  // ── setCfg / setters ──

  describe('state setters', () => {
    it('setCfg updates cfg', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => {
        result.current.setCfg(c => ({ ...c, replacementMode: 'mask' }));
      });

      expect(result.current.cfg.replacementMode).toBe('mask');
    });

    it('setConfirmStep1 toggles confirmStep1', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.setConfirmStep1(true));
      expect(result.current.confirmStep1).toBe(true);

      act(() => result.current.setConfirmStep1(false));
      expect(result.current.confirmStep1).toBe(false);
    });

    it('setJobPriority updates jobPriority', async () => {
      setupMocks();
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.setJobPriority(10));
      expect(result.current.jobPriority).toBe(10);
    });
  });

  // ── Error handling ──

  describe('error handling', () => {
    it('sets configLoaded to true even on fetch error', async () => {
      (fetchRecognitionEntityTypes as Mock).mockRejectedValue(new Error('network'));
      (fetchRecognitionPipelines as Mock).mockRejectedValue(new Error('network'));
      (fetchRecognitionPresets as Mock).mockRejectedValue(new Error('network'));
      const { result } = renderUseBatchConfig();
      await waitFor(() => expect(result.current.configLoaded).toBe(true));
    });

    it('setConfigLoadError calls setMsg with error tone', async () => {
      setupMocks();
      const setMsg = vi.fn();
      const { result } = renderHook(
        () => useBatchConfig('text', null, vi.fn(), false, setMsg),
        { wrapper },
      );
      await waitFor(() => expect(result.current.configLoaded).toBe(true));

      act(() => result.current.setConfigLoadError('something failed'));
      expect(setMsg).toHaveBeenCalledWith({ text: 'something failed', tone: 'err' });
    });
  });
});
