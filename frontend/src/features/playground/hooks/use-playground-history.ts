// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect } from 'react';
import type { useUndoRedo } from '@/hooks/useUndoRedo';
import type { Entity, BoundingBox } from '../types';

export interface UsePlaygroundHistoryOptions {
  isImageMode: boolean;
  entities: Entity[];
  setEntities: React.Dispatch<React.SetStateAction<Entity[]>>;
  boundingBoxes: BoundingBox[];
  visibleBoxes: BoundingBox[];
  setBoundingBoxes: React.Dispatch<React.SetStateAction<BoundingBox[]>>;
  entityHistory: ReturnType<typeof useUndoRedo<Entity[]>>;
  imageHistory: ReturnType<typeof useUndoRedo<BoundingBox[]>>;
  allSelectedVisionTypes: string[];
}

export function usePlaygroundHistory(options: UsePlaygroundHistoryOptions) {
  const {
    isImageMode,
    entities,
    setEntities,
    boundingBoxes,
    visibleBoxes,
    setBoundingBoxes,
    entityHistory,
    imageHistory,
    allSelectedVisionTypes,
  } = options;

  const canUndo = isImageMode ? imageHistory.canUndo : entityHistory.canUndo;
  const canRedo = isImageMode ? imageHistory.canRedo : entityHistory.canRedo;

  const selectedCount = isImageMode
    ? visibleBoxes.filter((b) => b.selected).length
    : entities.filter((e) => e.selected).length;

  const handleUndo = useCallback(() => {
    if (isImageMode) {
      const prev = imageHistory.undo(boundingBoxes);
      if (prev) setBoundingBoxes(prev);
    } else {
      const prev = entityHistory.undo(entities);
      if (prev) setEntities(prev);
    }
  }, [
    isImageMode,
    boundingBoxes,
    entities,
    imageHistory,
    entityHistory,
    setBoundingBoxes,
    setEntities,
  ]);

  const handleRedo = useCallback(() => {
    if (isImageMode) {
      const next = imageHistory.redo(boundingBoxes);
      if (next) setBoundingBoxes(next);
    } else {
      const next = entityHistory.redo(entities);
      if (next) setEntities(next);
    }
  }, [
    isImageMode,
    boundingBoxes,
    entities,
    imageHistory,
    entityHistory,
    setBoundingBoxes,
    setEntities,
  ]);

  const selectAll = useCallback(() => {
    if (isImageMode) {
      const visibleIds = new Set(visibleBoxes.map((box) => box.id));
      setBoundingBoxes((prev) =>
        prev.map((b) => ({
          ...b,
          selected: visibleIds.has(b.id) ? allSelectedVisionTypes.includes(b.type) : b.selected,
        })),
      );
    } else {
      setEntities((prev) => prev.map((e) => ({ ...e, selected: true })));
    }
  }, [isImageMode, visibleBoxes, allSelectedVisionTypes, setBoundingBoxes, setEntities]);

  const deselectAll = useCallback(() => {
    if (isImageMode) {
      const visibleIds = new Set(visibleBoxes.map((box) => box.id));
      setBoundingBoxes((prev) =>
        prev.map((b) => ({
          ...b,
          selected: visibleIds.has(b.id) ? false : b.selected,
        })),
      );
    } else {
      setEntities((prev) => prev.map((e) => ({ ...e, selected: false })));
    }
  }, [isImageMode, visibleBoxes, setBoundingBoxes, setEntities]);

  // --- Keyboard shortcuts ---
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
      )
        return;
      const isMac = navigator.platform.toLowerCase().includes('mac');
      const modKey = isMac ? e.metaKey : e.ctrlKey;
      if (!modKey) return;
      const key = e.key.toLowerCase();
      if (key === 'z') {
        e.preventDefault();
        if (e.shiftKey) {
          handleRedo();
        } else {
          handleUndo();
        }
      } else if (key === 'y') {
        e.preventDefault();
        handleRedo();
      } else if (key === 'a') {
        e.preventDefault();
        selectAll();
      }
    };
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') deselectAll();
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keydown', handleEsc);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keydown', handleEsc);
    };
  }, [handleUndo, handleRedo, selectAll, deselectAll]);

  return {
    canUndo,
    canRedo,
    selectedCount,
    handleUndo,
    handleRedo,
    selectAll,
    deselectAll,
  };
}
