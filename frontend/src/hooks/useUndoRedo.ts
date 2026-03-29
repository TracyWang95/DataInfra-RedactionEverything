import { useCallback, useRef } from 'react';

const MAX_HISTORY = 50;

interface Snapshot<T> {
  data: T;
}

/**
 * Generic undo/redo hook for any serializable state.
 *
 * Usage:
 *   const history = useUndoRedo<MyState>();
 *   // Before mutating: history.save(currentState)
 *   // Undo: const prev = history.undo(currentState)  -> returns previous state or null
 *   // Redo: const next = history.redo(currentState)  -> returns next state or null
 */
export function useUndoRedo<T>() {
  const undoStack = useRef<Snapshot<T>[]>([]);
  const redoStack = useRef<Snapshot<T>[]>([]);

  /** Snapshot current state before a mutation. Clears the redo stack. */
  const save = useCallback((current: T) => {
    undoStack.current.push({ data: current });
    if (undoStack.current.length > MAX_HISTORY) {
      undoStack.current.shift();
    }
    redoStack.current = [];
  }, []);

  /** Undo: pushes current state onto redo stack, returns previous state (or null). */
  const undo = useCallback((current: T): T | null => {
    const prev = undoStack.current.pop();
    if (!prev) return null;
    redoStack.current.push({ data: current });
    return prev.data;
  }, []);

  /** Redo: pushes current state onto undo stack, returns next state (or null). */
  const redo = useCallback((current: T): T | null => {
    const next = redoStack.current.pop();
    if (!next) return null;
    undoStack.current.push({ data: current });
    return next.data;
  }, []);

  /** Reset both stacks (e.g. on file change). */
  const reset = useCallback(() => {
    undoStack.current = [];
    redoStack.current = [];
  }, []);

  return {
    save,
    undo,
    redo,
    reset,
    get canUndo() {
      return undoStack.current.length > 0;
    },
    get canRedo() {
      return redoStack.current.length > 0;
    },
  };
}
