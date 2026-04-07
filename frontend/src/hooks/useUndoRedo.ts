// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useRef } from 'react';

const MAX_HISTORY = 50;

interface Snapshot<T> {
  data: T;
}


export function useUndoRedo<T>() {
  const undoStack = useRef<Snapshot<T>[]>([]);
  const redoStack = useRef<Snapshot<T>[]>([]);

  
  const save = useCallback((current: T) => {
    undoStack.current.push({ data: current });
    if (undoStack.current.length > MAX_HISTORY) {
      undoStack.current.shift();
    }
    redoStack.current = [];
  }, []);

  
  const undo = useCallback((current: T): T | null => {
    const prev = undoStack.current.pop();
    if (!prev) return null;
    redoStack.current.push({ data: current });
    return prev.data;
  }, []);

  
  const redo = useCallback((current: T): T | null => {
    const next = redoStack.current.pop();
    if (!next) return null;
    undoStack.current.push({ data: current });
    return next.data;
  }, []);

  
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
