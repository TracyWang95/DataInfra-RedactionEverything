// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

// NOTE: This test mocks sub-hooks to avoid OOM on Node 24+.
// The individual sub-hooks (use-playground-recognition, use-playground-entities,
// etc.) should be tested in their own dedicated test files.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';

// ── Mocks for sub-hooks ────────────────────────────────────────────────────

const mockSetTypeTab = vi.fn();
const mockRecognition = {
  entityTypes: [{ id: 'TYPE_1', name: 'Name', color: '#0f766e', enabled: true, order: 1 }],
  selectedTypes: ['TYPE_1'],
  selectedOcrHasTypes: ['ocr_1'],
  selectedHasImageTypes: ['img_1'],
  visionTypes: [{ id: 'ocr_1', name: 'OCR', color: '#0f766e', enabled: true }],
  typeTab: 'text' as const,
  setTypeTab: mockSetTypeTab,
  replacementMode: 'structured' as const,
  textConfigState: 'ready' as const,
  visionConfigState: 'ready' as const,
  sortedEntityTypes: [],
  playgroundPresetTextId: null,
  playgroundPresetVisionId: null,
  presetDialogKind: null,
  presetDialogName: '',
  presetSaving: false,
  presetApplySeq: 0,
  setSelectedTypes: vi.fn(),
  setReplacementMode: vi.fn(),
  getTypeConfig: vi.fn((id: string) => ({ id, name: id, color: '#6366F1' })),
  getVisionTypeConfig: vi.fn((id: string) => ({ id, name: id, color: '#6366F1' })),
  selectPlaygroundTextPresetById: vi.fn(),
  selectPlaygroundVisionPresetById: vi.fn(),
  setPlaygroundTextTypeGroupSelection: vi.fn(),
  toggleVisionType: vi.fn(),
  updateOcrHasTypes: vi.fn(),
  updateHasImageTypes: vi.fn(),
  openTextPresetDialog: vi.fn(),
  openVisionPresetDialog: vi.fn(),
  closePresetDialog: vi.fn(),
  saveCurrentAsPreset: vi.fn(),
};

vi.mock('../use-playground-recognition', () => ({
  usePlaygroundRecognition: vi.fn(() => mockRecognition),
}));

const mockDropzone = {
  getRootProps: vi.fn(() => ({})),
  getInputProps: vi.fn(() => ({})),
  isDragActive: false,
  open: vi.fn(),
  acceptedFiles: [],
  fileRejections: [],
  isFocused: false,
  isDragAccept: false,
  isDragReject: false,
  rootRef: { current: null },
  inputRef: { current: null },
};

vi.mock('../use-playground-file', () => ({
  usePlaygroundFile: vi.fn(() => ({
    stage: 'upload',
    setStage: vi.fn(),
    fileInfo: null,
    setFileInfo: vi.fn(),
    content: '',
    setContent: vi.fn(),
    isLoading: false,
    setIsLoading: vi.fn(),
    loadingMessage: '',
    setLoadingMessage: vi.fn(),
    loadingElapsedSec: 0,
    isImageMode: false,
    dropzone: mockDropzone,
  })),
}));

const mockImageHistory = {
  canUndo: false,
  canRedo: false,
  save: vi.fn(),
  undo: vi.fn(() => null),
  redo: vi.fn(() => null),
  reset: vi.fn(),
};

vi.mock('../use-playground-image', () => ({
  usePlaygroundImage: vi.fn(() => ({
    boundingBoxes: [],
    setBoundingBoxes: vi.fn(),
    visibleBoxes: [],
    imageUrl: '',
    redactedImageUrl: '',
    imageHistory: mockImageHistory,
    toggleBox: vi.fn(),
    mergeVisibleBoxes: vi.fn(),
    openPopout: vi.fn(),
    handleRerunNerImage: vi.fn(),
  })),
}));

vi.mock('@/services/api-client', () => ({
  authFetch: vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({}),
  }),
  downloadFile: vi.fn().mockResolvedValue(undefined),
  authenticatedBlobUrl: vi.fn().mockResolvedValue(''),
  revokeObjectUrl: vi.fn(),
  VISION_TIMEOUT: 60_000,
}));

vi.mock('@/i18n', () => ({ t: (k: string) => k }));

vi.mock('@/components/Toast', () => ({
  showToast: vi.fn(),
}));

vi.mock('@/utils/localizeError', () => ({
  localizeErrorMessage: (_e: unknown, key: string) => key,
}));

import { usePlayground } from '../use-playground';
import { usePlaygroundFile } from '../use-playground-file';
import type { Mock } from 'vitest';

// ── Helpers ─────────────────────────────────────────────────────────────────

const wrapper = ({ children }: { children: React.ReactNode }) =>
  createElement(MemoryRouter, null, children);

function renderUsePlayground() {
  return renderHook(() => usePlayground(), { wrapper });
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe('usePlayground', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  // ── Initial state ──

  describe('initial state', () => {
    it('stage starts as upload', () => {
      const { result } = renderUsePlayground();
      expect(result.current.stage).toBe('upload');
    });

    it('fileInfo starts null', () => {
      const { result } = renderUsePlayground();
      expect(result.current.fileInfo).toBeNull();
    });

    it('content starts empty', () => {
      const { result } = renderUsePlayground();
      expect(result.current.content).toBe('');
    });

    it('isImageMode starts false', () => {
      const { result } = renderUsePlayground();
      expect(result.current.isImageMode).toBe(false);
    });

    it('entities starts empty', () => {
      const { result } = renderUsePlayground();
      expect(result.current.entities).toEqual([]);
    });

    it('boundingBoxes starts empty', () => {
      const { result } = renderUsePlayground();
      expect(result.current.boundingBoxes).toEqual([]);
    });

    it('isLoading starts false', () => {
      const { result } = renderUsePlayground();
      expect(result.current.isLoading).toBe(false);
    });

    it('redactedCount starts at 0', () => {
      const { result } = renderUsePlayground();
      expect(result.current.redactedCount).toBe(0);
    });

    it('entityMap starts empty', () => {
      const { result } = renderUsePlayground();
      expect(result.current.entityMap).toEqual({});
    });

    it('redactionReport starts null', () => {
      const { result } = renderUsePlayground();
      expect(result.current.redactionReport).toBeNull();
    });

    it('reportOpen starts false', () => {
      const { result } = renderUsePlayground();
      expect(result.current.reportOpen).toBe(false);
    });

    it('versionHistory starts empty', () => {
      const { result } = renderUsePlayground();
      expect(result.current.versionHistory).toEqual([]);
    });

    it('versionHistoryOpen starts false', () => {
      const { result } = renderUsePlayground();
      expect(result.current.versionHistoryOpen).toBe(false);
    });
  });

  // ── Recognition pass-through ──

  describe('recognition config pass-through', () => {
    it('exposes recognition object', () => {
      const { result } = renderUsePlayground();
      expect(result.current.recognition).toBeDefined();
    });

    it('recognition.typeTab starts as text', () => {
      const { result } = renderUsePlayground();
      expect(result.current.recognition.typeTab).toBe('text');
    });

    it('recognition.replacementMode starts as structured', () => {
      const { result } = renderUsePlayground();
      expect(result.current.recognition.replacementMode).toBe('structured');
    });

    it('recognition entityTypes come from sub-hook', () => {
      const { result } = renderUsePlayground();
      expect(result.current.recognition.entityTypes.length).toBe(1);
      expect(result.current.recognition.entityTypes[0].id).toBe('TYPE_1');
    });
  });

  // ── Entity management ──

  describe('entity management', () => {
    it('setEntities updates entities', () => {
      const { result } = renderUsePlayground();

      act(() => {
        result.current.setEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: true, source: 'regex' },
        ]);
      });

      expect(result.current.entities).toHaveLength(1);
      expect(result.current.entities[0].text).toBe('Alice');
    });

    it('applyEntities saves to undo history', () => {
      const { result } = renderUsePlayground();

      act(() => {
        result.current.applyEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: true, source: 'regex' },
        ]);
      });

      expect(result.current.entities).toHaveLength(1);
      expect(result.current.canUndo).toBe(true);
    });

    it('undo restores previous entities', () => {
      const { result } = renderUsePlayground();

      act(() => {
        result.current.applyEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: true, source: 'regex' },
        ]);
      });

      act(() => result.current.handleUndo());

      expect(result.current.entities).toEqual([]);
    });

    it('redo restores undone entities', () => {
      const { result } = renderUsePlayground();

      act(() => {
        result.current.applyEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: true, source: 'regex' },
        ]);
      });

      act(() => result.current.handleUndo());
      act(() => result.current.handleRedo());

      expect(result.current.entities).toHaveLength(1);
    });

    it('removeEntity removes a specific entity', () => {
      const { result } = renderUsePlayground();

      act(() => {
        result.current.setEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: true, source: 'regex' },
          { id: 'e2', text: 'Bob', type: 'PERSON', start: 10, end: 13, selected: true, source: 'llm' },
        ]);
      });

      act(() => result.current.removeEntity('e1'));

      expect(result.current.entities).toHaveLength(1);
      expect(result.current.entities[0].id).toBe('e2');
    });
  });

  // ── Selection management ──

  describe('selection management', () => {
    it('selectedCount reflects selected entities count', () => {
      const { result } = renderUsePlayground();

      act(() => {
        result.current.setEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: true, source: 'regex' },
          { id: 'e2', text: 'Bob', type: 'PERSON', start: 10, end: 13, selected: false, source: 'llm' },
        ]);
      });

      expect(result.current.selectedCount).toBe(1);
    });

    it('selectAll selects all entities', () => {
      const { result } = renderUsePlayground();

      act(() => {
        result.current.setEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: false, source: 'regex' },
          { id: 'e2', text: 'Bob', type: 'PERSON', start: 10, end: 13, selected: false, source: 'llm' },
        ]);
      });

      act(() => result.current.selectAll());

      expect(result.current.entities.every(e => e.selected)).toBe(true);
    });

    it('deselectAll deselects all entities', () => {
      const { result } = renderUsePlayground();

      act(() => {
        result.current.setEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: true, source: 'regex' },
          { id: 'e2', text: 'Bob', type: 'PERSON', start: 10, end: 13, selected: true, source: 'llm' },
        ]);
      });

      act(() => result.current.deselectAll());

      expect(result.current.entities.every(e => !e.selected)).toBe(true);
    });
  });

  // ── Reset ──

  describe('handleReset', () => {
    it('resets all state to initial values', () => {
      const { result } = renderUsePlayground();

      // Set some state
      act(() => {
        result.current.setEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: true, source: 'regex' },
        ]);
        result.current.setReportOpen(true);
      });

      // Reset
      act(() => result.current.handleReset());

      expect(result.current.stage).toBe('upload');
      expect(result.current.fileInfo).toBeNull();
      expect(result.current.content).toBe('');
      expect(result.current.entities).toEqual([]);
      expect(result.current.redactedCount).toBe(0);
      expect(result.current.entityMap).toEqual({});
      expect(result.current.redactionReport).toBeNull();
      expect(result.current.reportOpen).toBe(false);
    });
  });

  // ── UI state toggles ──

  describe('UI state toggles', () => {
    it('setReportOpen toggles report panel', () => {
      const { result } = renderUsePlayground();

      act(() => result.current.setReportOpen(true));
      expect(result.current.reportOpen).toBe(true);

      act(() => result.current.setReportOpen(false));
      expect(result.current.reportOpen).toBe(false);
    });

    it('setVersionHistoryOpen toggles version history', () => {
      const { result } = renderUsePlayground();

      act(() => result.current.setVersionHistoryOpen(true));
      expect(result.current.versionHistoryOpen).toBe(true);

      act(() => result.current.setVersionHistoryOpen(false));
      expect(result.current.versionHistoryOpen).toBe(false);
    });
  });

  // ── Undo/redo state ──

  describe('undo/redo state', () => {
    it('canUndo is false initially', () => {
      const { result } = renderUsePlayground();
      expect(result.current.canUndo).toBe(false);
    });

    it('canRedo is false initially', () => {
      const { result } = renderUsePlayground();
      expect(result.current.canRedo).toBe(false);
    });

    it('canRedo is true after undo', () => {
      const { result } = renderUsePlayground();

      act(() => {
        result.current.applyEntities([
          { id: 'e1', text: 'Alice', type: 'PERSON', start: 0, end: 5, selected: true, source: 'regex' },
        ]);
      });
      act(() => result.current.handleUndo());

      expect(result.current.canRedo).toBe(true);
    });
  });

  // ── Error handling ──

  describe('error handling', () => {
    it('handleRedact is a no-op when no file is loaded', async () => {
      const { result } = renderUsePlayground();

      await act(async () => {
        await result.current.handleRedact();
      });

      expect(result.current.stage).toBe('upload');
    });

    it('handleDownload is a no-op when no file is loaded', () => {
      const { result } = renderUsePlayground();
      act(() => result.current.handleDownload());
    });

    it('handleRerunNer is a no-op when no file is loaded', async () => {
      const { result } = renderUsePlayground();

      await act(async () => {
        await result.current.handleRerunNer();
      });

      expect(result.current.entities).toEqual([]);
    });
  });

  // ── Dropzone exposure ──

  describe('dropzone', () => {
    it('exposes dropzone object', () => {
      const { result } = renderUsePlayground();
      expect(result.current.dropzone).toBeDefined();
      expect(result.current.dropzone.getRootProps).toBeDefined();
      expect(result.current.dropzone.getInputProps).toBeDefined();
    });
  });

  // ── Auto type-tab switch on file mode ──

  describe('auto type-tab switch', () => {
    it('calls setTypeTab(text) when not in image mode', () => {
      renderUsePlayground();
      // isImageMode is false from mock, so setTypeTab('text') should be called
      expect(mockSetTypeTab).toHaveBeenCalledWith('text');
    });

    it('calls setTypeTab(vision) when in image mode', () => {
      (usePlaygroundFile as Mock).mockReturnValue({
        stage: 'preview',
        setStage: vi.fn(),
        fileInfo: { file_id: 'f1', filename: 'test.jpg', file_size: 1024, file_type: 'image', is_scanned: false },
        setFileInfo: vi.fn(),
        content: '',
        setContent: vi.fn(),
        isLoading: false,
        setIsLoading: vi.fn(),
        loadingMessage: '',
        setLoadingMessage: vi.fn(),
        loadingElapsedSec: 0,
        isImageMode: true,
        dropzone: mockDropzone,
      });

      renderUsePlayground();
      expect(mockSetTypeTab).toHaveBeenCalledWith('vision');
    });
  });

  // ── Image-related pass-through ──

  describe('image pass-through', () => {
    it('imageUrl starts empty', () => {
      const { result } = renderUsePlayground();
      expect(result.current.imageUrl).toBe('');
    });

    it('visibleBoxes starts empty', () => {
      const { result } = renderUsePlayground();
      expect(result.current.visibleBoxes).toEqual([]);
    });
  });
});
