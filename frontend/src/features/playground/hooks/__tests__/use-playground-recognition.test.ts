// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

// NOTE: This test suite OOMs on Node.js 24.0.0 due to V8 memory pressure
// from renderHook + this complex hook's render cycle. It runs correctly on
// Node 20 (CI ubuntu-latest). Skip locally with: npx vitest run --exclude='**/use-playground-recognition*'
declare const process: { versions: { node: string } };
const nodeVersion = parseInt(process.versions.node.split('.')[0], 10);
if (nodeVersion >= 24) {
  console.warn(`[SKIP] use-playground-recognition tests skipped on Node ${process.versions.node} (OOM). CI uses Node 20.`);
}

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';

// ── Mocks ──────────────────────────────────────────────────────────────────

vi.mock('@/services/recognition-config', () => ({
  fetchRecognitionEntityTypes: vi.fn(),
  fetchRecognitionPipelines: vi.fn(),
}));

vi.mock('@/services/presetsApi', () => ({
  fetchPresets: vi.fn().mockResolvedValue([]),
  createPreset: vi.fn(),
  presetAppliesText: vi.fn((p: { kind?: string }) => {
    const k = p.kind ?? 'full';
    return k === 'text' || k === 'full';
  }),
  presetAppliesVision: vi.fn((p: { kind?: string }) => {
    const k = p.kind ?? 'full';
    return k === 'vision' || k === 'full';
  }),
}));

vi.mock('@/services/hooks/use-presets', () => ({
  usePresets: vi.fn(() => ({ data: [], isLoading: false, error: null })),
  useInvalidatePresets: vi.fn(() => vi.fn().mockResolvedValue(undefined)),
  PRESETS_QUERY_KEY: ['presets'],
}));


vi.mock('@/services/activePresetBridge', () => ({
  getActivePresetTextId: vi.fn(() => null),
  getActivePresetVisionId: vi.fn(() => null),
  setActivePresetTextId: vi.fn(),
  setActivePresetVisionId: vi.fn(),
}));

vi.mock('@/services/defaultRedactionPreset', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/defaultRedactionPreset')>();
  return { ...actual };
});

vi.mock('@/i18n', () => ({ t: (k: string) => k }));

vi.mock('@/components/Toast', () => ({
  showToast: vi.fn(),
}));

vi.mock('@/utils/localizeError', () => ({
  localizeErrorMessage: (_e: unknown, key: string) => key,
}));

import {
  fetchRecognitionEntityTypes,
  fetchRecognitionPipelines,
} from '@/services/recognition-config';
import { fetchPresets } from '@/services/presetsApi';
import type { RecognitionPreset } from '@/services/presetsApi';
import type { EntityTypeConfig, PipelineConfig } from '../../types';
import { usePlaygroundRecognition } from '../use-playground-recognition';

// ── Test fixtures ──────────────────────────────────────────────────────────

function makeEntityTypes(count = 5): EntityTypeConfig[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `TYPE_${i + 1}`,
    name: `Entity ${i + 1}`,
    color: '#0f766e',
    regex_pattern: i < 2 ? '\\d+' : null,
    enabled: true,
    order: i + 1,
  }));
}

function makePipelines(): PipelineConfig[] {
  return [
    {
      mode: 'ocr_has',
      name: 'OCR Pipeline',
      description: 'OCR text detection',
      enabled: true,
      types: [
        { id: 'ocr_1', name: 'OCR Type 1', color: '#0f766e', enabled: true, order: 1 },
        { id: 'ocr_2', name: 'OCR Type 2', color: '#0f766e', enabled: true, order: 2 },
      ],
    },
    {
      mode: 'has_image',
      name: 'Image Pipeline',
      description: 'Image feature detection',
      enabled: true,
      types: [
        { id: 'img_1', name: 'Image Type 1', color: '#b45309', enabled: true, order: 1 },
        { id: 'img_2', name: 'Image Type 2', color: '#b45309', enabled: true, order: 2 },
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

// ── Helpers ─────────────────────────────────────────────────────────────────

const wrapper = ({ children }: { children: React.ReactNode }) =>
  createElement(MemoryRouter, null, children);

function setupMocks(
  types: EntityTypeConfig[] = makeEntityTypes(),
  pipes: PipelineConfig[] = makePipelines(),
  presets: RecognitionPreset[] = [],
) {
  (fetchRecognitionEntityTypes as Mock).mockResolvedValue(types);
  (fetchRecognitionPipelines as Mock).mockResolvedValue(pipes);
  (fetchPresets as Mock).mockResolvedValue(presets);
}

function renderHookUnderTest() {
  return renderHook(() => usePlaygroundRecognition(), { wrapper });
}

// ── Tests ───────────────────────────────────────────────────────────────────

const describeOrSkip = nodeVersion >= 24 ? describe.skip : describe;

describeOrSkip('usePlaygroundRecognition', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  // ── Initial state ──

  describe('initial state', () => {
    it('textConfigState starts as loading', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.textConfigState).toBe('loading');
    });

    it('visionConfigState starts as loading', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.visionConfigState).toBe('loading');
    });

    it('entityTypes starts empty', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.entityTypes).toEqual([]);
    });

    it('selectedTypes starts empty', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.selectedTypes).toEqual([]);
    });

    it('visionTypes starts empty', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.visionTypes).toEqual([]);
    });

    it('selectedOcrHasTypes starts empty', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.selectedOcrHasTypes).toEqual([]);
    });

    it('selectedHasImageTypes starts empty', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.selectedHasImageTypes).toEqual([]);
    });

    it('typeTab starts as text', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.typeTab).toBe('text');
    });

    it('replacementMode starts as structured', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.replacementMode).toBe('structured');
    });

    it('playgroundPresetTextId starts null', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.playgroundPresetTextId).toBeNull();
    });

    it('playgroundPresetVisionId starts null', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.playgroundPresetVisionId).toBeNull();
    });

    it('presetDialogKind starts null', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.presetDialogKind).toBeNull();
    });

    it('presetSaving starts false', () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      expect(result.current.presetSaving).toBe(false);
    });
  });

  // ── Entity types fetch ──

  describe('entity types fetch', () => {
    it('populates entityTypes after mount', async () => {
      const types = makeEntityTypes(4);
      setupMocks(types);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBe(4));
    });

    it('sets textConfigState to ready when types are loaded', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.textConfigState).toBe('ready'));
    });

    it('sets textConfigState to empty when no types', async () => {
      setupMocks([]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.textConfigState).toBe('empty'));
    });

    it('sets textConfigState to unavailable on fetch error', async () => {
      (fetchRecognitionEntityTypes as Mock).mockRejectedValue(new Error('fail'));
      (fetchRecognitionPipelines as Mock).mockResolvedValue(makePipelines());
      (fetchPresets as Mock).mockResolvedValue([]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.textConfigState).toBe('unavailable'));
    });

    it('populates selectedTypes with default IDs from entity types', async () => {
      const types = makeEntityTypes(5);
      setupMocks(types);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.selectedTypes.length).toBeGreaterThan(0));
    });

    it('calls fetchRecognitionEntityTypes with enabledOnly=true', async () => {
      setupMocks();
      renderHookUnderTest();
      await waitFor(() => expect(fetchRecognitionEntityTypes).toHaveBeenCalledWith(true, 1_200));
    });

    it('sortedEntityTypes is sorted (regex types first)', async () => {
      const types = makeEntityTypes(5);
      setupMocks(types);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.sortedEntityTypes.length).toBe(5));
      // First two types have regex_pattern, so they should appear first
      const firstTwo = result.current.sortedEntityTypes.slice(0, 2);
      expect(firstTwo.every(t => t.regex_pattern != null)).toBe(true);
    });
  });

  // ── Vision types fetch ──

  describe('vision types fetch', () => {
    it('populates visionTypes after mount', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionTypes.length).toBeGreaterThan(0));
    });

    it('sets visionConfigState to ready when pipelines are loaded', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('ready'));
    });

    it('populates selectedOcrHasTypes with defaults', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.selectedOcrHasTypes.length).toBeGreaterThan(0));
    });

    it('populates selectedHasImageTypes with defaults', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.selectedHasImageTypes.length).toBeGreaterThan(0));
    });

    it('sets visionConfigState to unavailable on pipeline fetch error', async () => {
      (fetchRecognitionEntityTypes as Mock).mockResolvedValue(makeEntityTypes());
      (fetchRecognitionPipelines as Mock).mockRejectedValue(new Error('fail'));
      (fetchPresets as Mock).mockResolvedValue([]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('unavailable'));
    });

    it('restores ocrHasTypes from localStorage', async () => {
      localStorage.setItem('ocrHasTypes', JSON.stringify(['ocr_1']));
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.selectedOcrHasTypes).toEqual(['ocr_1']));
    });

    it('restores hasImageTypes from localStorage', async () => {
      localStorage.setItem('hasImageTypes', JSON.stringify(['img_1']));
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.selectedHasImageTypes).toEqual(['img_1']));
    });

    it('filters out unknown IDs from localStorage ocrHasTypes', async () => {
      localStorage.setItem('ocrHasTypes', JSON.stringify(['ocr_1', 'nonexistent']));
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.selectedOcrHasTypes).toEqual(['ocr_1']));
    });
  });

  // ── Preset selection ──

  describe('preset selection', () => {
    it('selectPlaygroundTextPresetById updates selectedTypes', async () => {
      const types = makeEntityTypes(5);
      const preset = makeTextPreset(['TYPE_1', 'TYPE_3']);
      setupMocks(types, makePipelines(), [preset]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBe(5));

      act(() => result.current.selectPlaygroundTextPresetById('preset-text-1'));

      expect(result.current.selectedTypes).toEqual(['TYPE_1', 'TYPE_3']);
    });

    it('selectPlaygroundTextPresetById sets playgroundPresetTextId', async () => {
      const types = makeEntityTypes(5);
      const preset = makeTextPreset(['TYPE_1']);
      setupMocks(types, makePipelines(), [preset]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBe(5));

      act(() => result.current.selectPlaygroundTextPresetById('preset-text-1'));

      expect(result.current.playgroundPresetTextId).toBe('preset-text-1');
    });

    it('selectPlaygroundTextPresetById with empty string resets to defaults', async () => {
      const types = makeEntityTypes(5);
      const preset = makeTextPreset(['TYPE_1']);
      setupMocks(types, makePipelines(), [preset]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBe(5));

      act(() => result.current.selectPlaygroundTextPresetById('preset-text-1'));
      act(() => result.current.selectPlaygroundTextPresetById(''));

      expect(result.current.playgroundPresetTextId).toBeNull();
      expect(result.current.replacementMode).toBe('structured');
    });

    it('selectPlaygroundTextPresetById filters out disabled entity type IDs', async () => {
      const types: EntityTypeConfig[] = [
        { id: 'TYPE_1', name: 'E1', color: '#000', enabled: true, order: 1 },
        { id: 'TYPE_2', name: 'E2', color: '#000', enabled: false, order: 2 },
      ];
      const preset = makeTextPreset(['TYPE_1', 'TYPE_2']);
      setupMocks(types, makePipelines(), [preset]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBe(2));

      act(() => result.current.selectPlaygroundTextPresetById('preset-text-1'));

      expect(result.current.selectedTypes).toEqual(['TYPE_1']);
    });

    it('selectPlaygroundVisionPresetById updates ocrHasTypes', async () => {
      const vPreset = makeVisionPreset();
      setupMocks(makeEntityTypes(), makePipelines(), [vPreset]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('ready'));

      act(() => result.current.selectPlaygroundVisionPresetById('preset-vision-1'));

      expect(result.current.selectedOcrHasTypes).toEqual(['ocr_1']);
    });

    it('selectPlaygroundVisionPresetById with empty resets to defaults', async () => {
      const vPreset = makeVisionPreset();
      setupMocks(makeEntityTypes(), makePipelines(), [vPreset]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('ready'));

      act(() => result.current.selectPlaygroundVisionPresetById('preset-vision-1'));
      act(() => result.current.selectPlaygroundVisionPresetById(''));

      expect(result.current.playgroundPresetVisionId).toBeNull();
    });
  });

  // ── toggleVisionType ──

  describe('toggleVisionType', () => {
    it('adds a type to selectedOcrHasTypes when not present', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('ready'));

      // First clear the defaults to have a clean state
      act(() => result.current.updateOcrHasTypes([]));

      act(() => result.current.toggleVisionType('ocr_1', 'ocr_has'));

      expect(result.current.selectedOcrHasTypes).toContain('ocr_1');
    });

    it('removes a type from selectedOcrHasTypes when present', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('ready'));

      // Ensure ocr_1 is selected
      act(() => result.current.updateOcrHasTypes(['ocr_1', 'ocr_2']));

      act(() => result.current.toggleVisionType('ocr_1', 'ocr_has'));

      expect(result.current.selectedOcrHasTypes).not.toContain('ocr_1');
      expect(result.current.selectedOcrHasTypes).toContain('ocr_2');
    });

    it('adds a type to selectedHasImageTypes when not present', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('ready'));

      act(() => result.current.updateHasImageTypes([]));

      act(() => result.current.toggleVisionType('img_1', 'has_image'));

      expect(result.current.selectedHasImageTypes).toContain('img_1');
    });

    it('removes a type from selectedHasImageTypes when present', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('ready'));

      act(() => result.current.updateHasImageTypes(['img_1', 'img_2']));

      act(() => result.current.toggleVisionType('img_1', 'has_image'));

      expect(result.current.selectedHasImageTypes).not.toContain('img_1');
    });

    it('returns info about the toggled type', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('ready'));

      act(() => result.current.updateOcrHasTypes(['ocr_1']));

      let toggleResult: { typeId: string; wasActive: boolean } | undefined;
      act(() => {
        toggleResult = result.current.toggleVisionType('ocr_1', 'ocr_has');
      });

      expect(toggleResult).toEqual({ typeId: 'ocr_1', wasActive: true });
    });

    it('clears vision preset tracking after toggle', async () => {
      const vPreset = makeVisionPreset();
      setupMocks(makeEntityTypes(), makePipelines(), [vPreset]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionConfigState).toBe('ready'));

      act(() => result.current.selectPlaygroundVisionPresetById('preset-vision-1'));
      expect(result.current.playgroundPresetVisionId).toBe('preset-vision-1');

      act(() => result.current.toggleVisionType('ocr_2', 'ocr_has'));
      expect(result.current.playgroundPresetVisionId).toBeNull();
    });
  });

  // ── Text group selection ──

  describe('text group selection', () => {
    it('setPlaygroundTextTypeGroupSelection adds IDs when turnOn=true', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBeGreaterThan(0));

      act(() => result.current.setSelectedTypes([]));

      act(() => result.current.setPlaygroundTextTypeGroupSelection(['TYPE_1', 'TYPE_2'], true));

      expect(result.current.selectedTypes).toContain('TYPE_1');
      expect(result.current.selectedTypes).toContain('TYPE_2');
    });

    it('setPlaygroundTextTypeGroupSelection removes IDs when turnOn=false', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBeGreaterThan(0));

      act(() => result.current.setSelectedTypes(['TYPE_1', 'TYPE_2', 'TYPE_3']));
      act(() => result.current.setPlaygroundTextTypeGroupSelection(['TYPE_1', 'TYPE_2'], false));

      expect(result.current.selectedTypes).toEqual(['TYPE_3']);
    });

    it('clears text preset tracking after group selection change', async () => {
      const preset = makeTextPreset(['TYPE_1']);
      setupMocks(makeEntityTypes(), makePipelines(), [preset]);
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBeGreaterThan(0));

      act(() => result.current.selectPlaygroundTextPresetById('preset-text-1'));
      expect(result.current.playgroundPresetTextId).toBe('preset-text-1');

      act(() => result.current.setPlaygroundTextTypeGroupSelection(['TYPE_3'], true));
      expect(result.current.playgroundPresetTextId).toBeNull();
    });
  });

  // ── Preset dialog ──

  describe('preset dialog', () => {
    it('openTextPresetDialog sets kind to text', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();

      act(() => result.current.openTextPresetDialog());

      expect(result.current.presetDialogKind).toBe('text');
    });

    it('openVisionPresetDialog sets kind to vision', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();

      act(() => result.current.openVisionPresetDialog());

      expect(result.current.presetDialogKind).toBe('vision');
    });

    it('closePresetDialog resets dialog state', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();

      act(() => result.current.openTextPresetDialog());
      act(() => result.current.closePresetDialog());

      expect(result.current.presetDialogKind).toBeNull();
      expect(result.current.presetDialogName).toBe('');
    });
  });

  // ── getTypeConfig / getVisionTypeConfig ──

  describe('type config helpers', () => {
    it('getTypeConfig returns config for known type', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBeGreaterThan(0));

      const config = result.current.getTypeConfig('TYPE_1');
      expect(config.name).toBe('Entity 1');
    });

    it('getTypeConfig returns fallback for unknown type', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.entityTypes.length).toBeGreaterThan(0));

      const config = result.current.getTypeConfig('UNKNOWN');
      expect(config.name).toBe('UNKNOWN');
      expect(config.color).toBe('#6366F1');
    });

    it('getVisionTypeConfig returns config for known vision type', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();
      await waitFor(() => expect(result.current.visionTypes.length).toBeGreaterThan(0));

      const config = result.current.getVisionTypeConfig('ocr_1');
      expect(config.name).toBe('OCR Type 1');
    });

    it('getVisionTypeConfig returns fallback for unknown vision type', async () => {
      setupMocks();
      const { result } = renderHookUnderTest();

      const config = result.current.getVisionTypeConfig('UNKNOWN');
      expect(config.name).toBe('UNKNOWN');
      expect(config.color).toBe('#6366F1');
    });
  });
});
