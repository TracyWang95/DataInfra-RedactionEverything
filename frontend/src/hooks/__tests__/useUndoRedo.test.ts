// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useUndoRedo } from '../useUndoRedo';

describe('useUndoRedo', () => {
  it('starts with empty stacks (cannot undo or redo)', () => {
    const { result } = renderHook(() => useUndoRedo<string>());
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  // ── save (push) ──────────────────────────────────────────────────────────
  it('save() adds to the undo stack', () => {
    const { result } = renderHook(() => useUndoRedo<string>());

    act(() => {
      result.current.save('state-A');
    });

    expect(result.current.canUndo).toBe(true);
    expect(result.current.canRedo).toBe(false);
  });

  it('save() clears the redo stack', () => {
    const { result } = renderHook(() => useUndoRedo<string>());

    // Build an undo entry then undo to create a redo entry
    act(() => {
      result.current.save('state-A');
    });

    let undone: string | null = null;
    act(() => {
      undone = result.current.undo('state-B');
    });
    expect(undone).toBe('state-A');
    expect(result.current.canRedo).toBe(true);

    // Now save a new state -> redo should be cleared
    act(() => {
      result.current.save('state-C');
    });
    expect(result.current.canRedo).toBe(false);
  });

  it('save() respects MAX_HISTORY (50) by dropping oldest entry', () => {
    const { result } = renderHook(() => useUndoRedo<number>());

    // Push 51 entries
    act(() => {
      for (let i = 0; i < 51; i++) {
        result.current.save(i);
      }
    });

    // Should still be able to undo 50 times
    let count = 0;
    let val: number | null = -1;
    act(() => {
      while (val !== null) {
        val = result.current.undo(999);
        if (val !== null) count++;
      }
    });
    expect(count).toBe(50);
  });

  // ── undo ─────────────────────────────────────────────────────────────────
  it('undo() returns the previous snapshot and moves current to redo stack', () => {
    const { result } = renderHook(() => useUndoRedo<string>());

    act(() => {
      result.current.save('state-A');
      result.current.save('state-B');
    });

    let undone: string | null = null;
    act(() => {
      undone = result.current.undo('state-C');
    });

    expect(undone).toBe('state-B');
    expect(result.current.canRedo).toBe(true);
    expect(result.current.canUndo).toBe(true); // state-A is still there
  });

  it('undo() on empty stack returns null (no-op)', () => {
    const { result } = renderHook(() => useUndoRedo<string>());

    let undone: string | null = 'not-null';
    act(() => {
      undone = result.current.undo('current');
    });

    expect(undone).toBeNull();
    expect(result.current.canRedo).toBe(false);
  });

  // ── redo ─────────────────────────────────────────────────────────────────
  it('redo() returns the next snapshot and moves current to undo stack', () => {
    const { result } = renderHook(() => useUndoRedo<string>());

    act(() => {
      result.current.save('state-A');
    });
    act(() => {
      result.current.undo('state-B');
    });

    let redone: string | null = null;
    act(() => {
      redone = result.current.redo('state-A');
    });

    expect(redone).toBe('state-B');
    expect(result.current.canUndo).toBe(true);
    expect(result.current.canRedo).toBe(false);
  });

  it('redo() on empty stack returns null (no-op)', () => {
    const { result } = renderHook(() => useUndoRedo<string>());

    let redone: string | null = 'not-null';
    act(() => {
      redone = result.current.redo('current');
    });

    expect(redone).toBeNull();
    expect(result.current.canUndo).toBe(false);
  });

  // ── reset (clear) ───────────────────────────────────────────────────────
  it('reset() clears both undo and redo stacks', () => {
    const { result } = renderHook(() => useUndoRedo<string>());

    act(() => {
      result.current.save('A');
      result.current.save('B');
    });
    act(() => {
      result.current.undo('C');
    });

    expect(result.current.canUndo).toBe(true);
    expect(result.current.canRedo).toBe(true);

    act(() => {
      result.current.reset();
    });

    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  // ── full round-trip ─────────────────────────────────────────────────────
  it('supports undo → redo → undo round-trip', () => {
    const { result } = renderHook(() => useUndoRedo<string>());

    act(() => {
      result.current.save('A');
      result.current.save('B');
    });

    let val: string | null;

    // undo twice
    act(() => {
      val = result.current.undo('C');
      expect(val).toBe('B');
    });
    act(() => {
      val = result.current.undo('B');
      expect(val).toBe('A');
    });

    // redo once
    act(() => {
      val = result.current.redo('A');
      expect(val).toBe('B');
    });

    // undo once more
    act(() => {
      val = result.current.undo('B');
      expect(val).toBe('A');
    });
  });
});
