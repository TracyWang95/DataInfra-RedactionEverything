// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import type { MutableRefObject } from 'react';

// ── Mocks ──────────────────────────────────────────────────────────────────

vi.mock('@/services/jobsApi', () => ({
  putItemReviewDraft: vi.fn().mockResolvedValue({}),
  getItemReviewDraft: vi.fn().mockResolvedValue(null),
}));

vi.mock('@/services/batchPipeline', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/batchPipeline')>();
  return { ...actual };
});

vi.mock('@/services/api', () => ({
  fileApi: vi.fn(),
  authenticatedBlobUrl: vi.fn().mockResolvedValue(''),
}));

vi.mock('@/services/api-client', () => ({
  authFetch: vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }),
}));

vi.mock('@/utils/localizeError', () => ({
  localizeErrorMessage: (_e: unknown, key: string) => key,
}));

vi.mock('@/i18n', () => ({ t: (k: string) => k }));

vi.mock('../use-batch-review-data', () => ({
  useBatchReviewData: vi.fn(() => ({
    loadReviewData: vi.fn(),
    rerunCurrentItemRecognition: vi.fn(),
    rerunRecognitionLoading: false,
    reviewImagePreviewLoading: false,
  })),
}));

vi.mock('@/utils/textRedactionSegments', () => ({
  buildTextSegments: vi.fn(() => []),
  mergePreviewMapWithDocumentSlices: vi.fn(() => ({})),
}));

import type { BatchWizardPersistedConfig } from '@/services/batchPipeline';
import { FileType } from '@/types';
import type { BatchRow, ReviewEntity, TextEntityType, Step } from '../../types';
import { useBatchReview } from '../use-batch-review';

// ── Test fixtures ──────────────────────────────────────────────────────────

const baseCfg: BatchWizardPersistedConfig = {
  selectedEntityTypeIds: ['TYPE_1'],
  ocrHasTypes: [],
  hasImageTypes: [],
  replacementMode: 'structured',
  imageRedactionMethod: 'mosaic',
  imageRedactionStrength: 25,
  imageFillColor: '#000000',
  presetTextId: null,
  presetVisionId: null,
  presetId: null,
  executionDefault: 'queue',
};

const textTypes: TextEntityType[] = [
  { id: 'TYPE_1', name: 'Name', color: '#0f766e' },
];

function makeEntity(id: string, text: string): ReviewEntity {
  return {
    id,
    text,
    type: 'TYPE_1',
    start: 0,
    end: text.length,
    selected: true,
    page: 1,
    confidence: 0.95,
    source: 'regex',
  };
}

function makeDoneRow(fileId: string): BatchRow {
  return {
    file_id: fileId,
    original_filename: `${fileId}.docx`,
    file_size: 1024,
    file_type: FileType.DOCX,
    created_at: '2026-01-01T00:00:00Z',
    has_output: false,
    entity_count: 1,
    analyzeStatus: 'awaiting_review',
  };
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const wrapper = ({ children }: { children: React.ReactNode }) =>
  createElement(MemoryRouter, null, children);

function renderUseBatchReview(overrides: {
  step?: Step;
  rows?: BatchRow[];
  activeJobId?: string | null;
  isPreviewMode?: boolean;
} = {}) {
  const itemIdByFileIdRef: MutableRefObject<Record<string, string>> = {
    current: { 'file-1': 'item-1', 'file-2': 'item-2' },
  };
  const setMsg = vi.fn();

  return {
    ...renderHook(
      () =>
        useBatchReview(
          overrides.step ?? 4,
          overrides.rows ?? [makeDoneRow('file-1'), makeDoneRow('file-2')],
          overrides.activeJobId ?? 'job-1',
          itemIdByFileIdRef,
          baseCfg,
          overrides.isPreviewMode ?? false,
          textTypes,
          setMsg,
        ),
      { wrapper },
    ),
    setMsg,
  };
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe('useBatchReview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Initial state ──

  describe('initial state', () => {
    it('reviewEntities starts empty', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewEntities).toEqual([]);
    });

    it('reviewBoxes starts empty', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewBoxes).toEqual([]);
    });

    it('reviewIndex starts at 0', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewIndex).toBe(0);
    });

    it('reviewLoading starts false', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewLoading).toBe(false);
    });

    it('reviewExecuteLoading starts false', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewExecuteLoading).toBe(false);
    });

    it('reviewDraftSaving starts false', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewDraftSaving).toBe(false);
    });

    it('reviewDraftError starts null', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewDraftError).toBeNull();
    });

    it('reviewTextUndoStack starts empty', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewTextUndoStack).toEqual([]);
    });

    it('reviewTextRedoStack starts empty', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewTextRedoStack).toEqual([]);
    });

    it('reviewImageUndoStack starts empty', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewImageUndoStack).toEqual([]);
    });

    it('reviewImageRedoStack starts empty', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewImageRedoStack).toEqual([]);
    });

    it('reviewDraftDirtyRef starts false', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewDraftDirtyRef.current).toBe(false);
    });

    it('reviewTextContent starts empty', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewTextContent).toBe('');
    });
  });

  // ── Derived values ──

  describe('derived values', () => {
    it('doneRows filters rows with done statuses', () => {
      const rows: BatchRow[] = [
        makeDoneRow('file-1'),
        { ...makeDoneRow('file-2'), analyzeStatus: 'pending' },
        { ...makeDoneRow('file-3'), analyzeStatus: 'completed' },
      ];
      const { result } = renderUseBatchReview({ rows });
      expect(result.current.doneRows.length).toBe(2);
    });

    it('reviewFile returns first doneRow at index 0', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.reviewFile?.file_id).toBe('file-1');
    });

    it('reviewFile returns null when no done rows', () => {
      const { result } = renderUseBatchReview({ rows: [] });
      expect(result.current.reviewFile).toBeNull();
    });

    it('selectedReviewEntityCount counts selected entities', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.selectedReviewEntityCount).toBe(0);
    });

    it('pendingReviewCount reflects unconfirmed rows', () => {
      const rows = [makeDoneRow('file-1'), makeDoneRow('file-2')];
      const { result } = renderUseBatchReview({ rows });
      expect(result.current.pendingReviewCount).toBe(2);
    });

    it('allReviewConfirmed is false when rows have pending reviews', () => {
      const { result } = renderUseBatchReview();
      expect(result.current.allReviewConfirmed).toBe(false);
    });

    it('allReviewConfirmed is true when all rows are confirmed', () => {
      const rows = [
        { ...makeDoneRow('file-1'), reviewConfirmed: true } as BatchRow,
        { ...makeDoneRow('file-2'), reviewConfirmed: true } as BatchRow,
      ];
      const { result } = renderUseBatchReview({ rows });
      expect(result.current.allReviewConfirmed).toBe(true);
    });
  });

  // ── applyReviewEntities / setReviewEntities ──

  describe('applyReviewEntities', () => {
    it('sets review entities from array', () => {
      const { result } = renderUseBatchReview();
      const entities = [makeEntity('e1', 'Alice'), makeEntity('e2', 'Bob')];

      act(() => result.current.applyReviewEntities(entities));

      expect(result.current.reviewEntities).toEqual(entities);
    });

    it('sets review entities from updater function', () => {
      const { result } = renderUseBatchReview();

      act(() => result.current.applyReviewEntities([makeEntity('e1', 'Alice')]));
      act(() => result.current.applyReviewEntities(prev => [...prev, makeEntity('e2', 'Bob')]));

      expect(result.current.reviewEntities.length).toBe(2);
    });

    it('marks reviewDraftDirtyRef as true on change', () => {
      const { result } = renderUseBatchReview();

      act(() => result.current.applyReviewEntities([makeEntity('e1', 'Alice')]));

      expect(result.current.reviewDraftDirtyRef.current).toBe(true);
    });

    it('pushes previous state to undo stack', () => {
      const { result } = renderUseBatchReview();

      act(() => result.current.applyReviewEntities([makeEntity('e1', 'Alice')]));

      expect(result.current.reviewTextUndoStack.length).toBe(1);
      expect(result.current.reviewTextUndoStack[0]).toEqual([]); // was empty before
    });

    it('clears redo stack on new change', () => {
      const { result } = renderUseBatchReview();

      act(() => result.current.applyReviewEntities([makeEntity('e1', 'Alice')]));
      act(() => result.current.applyReviewEntities([makeEntity('e2', 'Bob')]));

      // Redo stack should be cleared after each new apply
      expect(result.current.reviewTextRedoStack).toEqual([]);
    });
  });

  // ── Undo / Redo ──

  describe('undo / redo', () => {
    it('undo restores previous entities', () => {
      const { result } = renderUseBatchReview();
      const e1 = [makeEntity('e1', 'Alice')];
      const e2 = [makeEntity('e2', 'Bob')];

      act(() => result.current.applyReviewEntities(e1));
      act(() => result.current.applyReviewEntities(e2));

      // Now undo should restore e1
      act(() => result.current.undoReviewText());

      expect(result.current.reviewEntities.map(e => e.id)).toEqual(['e1']);
    });

    it('redo restores the undone state', () => {
      const { result } = renderUseBatchReview();
      const e1 = [makeEntity('e1', 'Alice')];
      const e2 = [makeEntity('e2', 'Bob')];

      act(() => result.current.applyReviewEntities(e1));
      act(() => result.current.applyReviewEntities(e2));
      act(() => result.current.undoReviewText());
      act(() => result.current.redoReviewText());

      expect(result.current.reviewEntities.map(e => e.id)).toEqual(['e2']);
    });

    it('undo with empty stack is a no-op', () => {
      const { result } = renderUseBatchReview();
      const before = result.current.reviewEntities;

      act(() => result.current.undoReviewText());

      expect(result.current.reviewEntities).toEqual(before);
    });

    it('redo with empty stack is a no-op', () => {
      const { result } = renderUseBatchReview();

      act(() => result.current.applyReviewEntities([makeEntity('e1', 'Alice')]));
      const before = result.current.reviewEntities;

      act(() => result.current.redoReviewText());

      expect(result.current.reviewEntities).toEqual(before);
    });

    it('multiple undo steps walk back through history', () => {
      const { result } = renderUseBatchReview();

      act(() => result.current.applyReviewEntities([makeEntity('e1', 'A')]));
      act(() => result.current.applyReviewEntities([makeEntity('e2', 'B')]));
      act(() => result.current.applyReviewEntities([makeEntity('e3', 'C')]));

      act(() => result.current.undoReviewText());
      expect(result.current.reviewEntities[0].id).toBe('e2');

      act(() => result.current.undoReviewText());
      expect(result.current.reviewEntities[0].id).toBe('e1');

      act(() => result.current.undoReviewText());
      expect(result.current.reviewEntities).toEqual([]);
    });

    it('undo marks reviewDraftDirtyRef as true', () => {
      const { result } = renderUseBatchReview();

      act(() => result.current.applyReviewEntities([makeEntity('e1', 'A')]));
      // Reset dirty flag
      result.current.reviewDraftDirtyRef.current = false;

      act(() => result.current.undoReviewText());

      expect(result.current.reviewDraftDirtyRef.current).toBe(true);
    });

    it('redo marks reviewDraftDirtyRef as true', () => {
      const { result } = renderUseBatchReview();

      act(() => result.current.applyReviewEntities([makeEntity('e1', 'A')]));
      act(() => result.current.undoReviewText());
      result.current.reviewDraftDirtyRef.current = false;

      act(() => result.current.redoReviewText());

      expect(result.current.reviewDraftDirtyRef.current).toBe(true);
    });
  });

  // ── toggleReviewEntitySelected ──

  describe('toggleReviewEntitySelected', () => {
    it('toggles entity selected state', () => {
      const { result } = renderUseBatchReview();
      const entity = makeEntity('e1', 'Alice');

      act(() => result.current.applyReviewEntities([entity]));
      // Reset undo stack so we isolate the toggle
      act(() => result.current.toggleReviewEntitySelected('e1'));

      expect(result.current.reviewEntities[0].selected).toBe(false);
    });

    it('toggling back restores selected state', () => {
      const { result } = renderUseBatchReview();
      const entity = makeEntity('e1', 'Alice');

      act(() => result.current.applyReviewEntities([entity]));
      act(() => result.current.toggleReviewEntitySelected('e1'));
      act(() => result.current.toggleReviewEntitySelected('e1'));

      expect(result.current.reviewEntities[0].selected).toBe(true);
    });
  });

  // ── buildCurrentReviewDraftPayload ──

  describe('buildCurrentReviewDraftPayload', () => {
    it('returns entities and bounding_boxes arrays', () => {
      const { result } = renderUseBatchReview();

      act(() => result.current.applyReviewEntities([makeEntity('e1', 'Alice')]));

      const payload = result.current.buildCurrentReviewDraftPayload();
      expect(payload.entities).toHaveLength(1);
      expect(payload.bounding_boxes).toHaveLength(0);
      expect(payload.entities[0]).toHaveProperty('id', 'e1');
    });

    it('returns empty arrays when no entities or boxes', () => {
      const { result } = renderUseBatchReview();
      const payload = result.current.buildCurrentReviewDraftPayload();
      expect(payload.entities).toEqual([]);
      expect(payload.bounding_boxes).toEqual([]);
    });
  });
});
