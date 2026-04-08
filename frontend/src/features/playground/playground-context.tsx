// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * PlaygroundContext — eliminates prop drilling from playground-page.tsx.
 *
 * Instead of destructuring 23+ values from usePlayground() and threading
 * them through props, child components consume this context directly.
 *
 * The context is split into three parts to avoid unnecessary re-renders:
 *   - PlaygroundDataCtx:    frequently-changing data (file, entities, recognition state, etc.)
 *   - PlaygroundActionsCtx: stable callbacks (wrapped in useCallback by the underlying hooks)
 *   - PlaygroundUICtx:      UI-specific state (selection popups, text selection, etc.)
 */

import { createContext, useContext, useMemo, type FC, type ReactNode } from 'react';
import { usePlayground } from './hooks/use-playground';
import { usePlaygroundUI } from './hooks/use-playground-ui';

/** The full return type of usePlayground(). */
export type PlaygroundContextValue = ReturnType<typeof usePlayground>;

/** The full return type of usePlaygroundUI(). */
export type PlaygroundUIContextValue = ReturnType<typeof usePlaygroundUI>;

/** Frequently-changing data from usePlayground(). */
export interface PlaygroundDataContextValue {
  stage: PlaygroundContextValue['stage'];
  fileInfo: PlaygroundContextValue['fileInfo'];
  content: PlaygroundContextValue['content'];
  isImageMode: PlaygroundContextValue['isImageMode'];
  entities: PlaygroundContextValue['entities'];
  boundingBoxes: PlaygroundContextValue['boundingBoxes'];
  visibleBoxes: PlaygroundContextValue['visibleBoxes'];
  isLoading: PlaygroundContextValue['isLoading'];
  loadingMessage: PlaygroundContextValue['loadingMessage'];
  loadingElapsedSec: PlaygroundContextValue['loadingElapsedSec'];
  entityMap: PlaygroundContextValue['entityMap'];
  redactedCount: PlaygroundContextValue['redactedCount'];
  redactionReport: PlaygroundContextValue['redactionReport'];
  reportOpen: PlaygroundContextValue['reportOpen'];
  versionHistory: PlaygroundContextValue['versionHistory'];
  versionHistoryOpen: PlaygroundContextValue['versionHistoryOpen'];
  selectedCount: PlaygroundContextValue['selectedCount'];
  canUndo: PlaygroundContextValue['canUndo'];
  canRedo: PlaygroundContextValue['canRedo'];
  entityHistory: PlaygroundContextValue['entityHistory'];
  imageHistory: PlaygroundContextValue['imageHistory'];
  imageUrl: PlaygroundContextValue['imageUrl'];
  redactedImageUrl: PlaygroundContextValue['redactedImageUrl'];
  recognition: PlaygroundContextValue['recognition'];
  dropzone: PlaygroundContextValue['dropzone'];
}

/** Stable action callbacks from usePlayground(). */
export interface PlaygroundActionsContextValue {
  setStage: PlaygroundContextValue['setStage'];
  setEntities: PlaygroundContextValue['setEntities'];
  applyEntities: PlaygroundContextValue['applyEntities'];
  setBoundingBoxes: PlaygroundContextValue['setBoundingBoxes'];
  setReportOpen: PlaygroundContextValue['setReportOpen'];
  setVersionHistoryOpen: PlaygroundContextValue['setVersionHistoryOpen'];
  handleUndo: PlaygroundContextValue['handleUndo'];
  handleRedo: PlaygroundContextValue['handleRedo'];
  selectAll: PlaygroundContextValue['selectAll'];
  deselectAll: PlaygroundContextValue['deselectAll'];
  toggleBox: PlaygroundContextValue['toggleBox'];
  removeEntity: PlaygroundContextValue['removeEntity'];
  handleRerunNer: PlaygroundContextValue['handleRerunNer'];
  handleRedact: PlaygroundContextValue['handleRedact'];
  handleReset: PlaygroundContextValue['handleReset'];
  handleDownload: PlaygroundContextValue['handleDownload'];
  mergeVisibleBoxes: PlaygroundContextValue['mergeVisibleBoxes'];
  openPopout: PlaygroundContextValue['openPopout'];
}

const PlaygroundDataCtx = createContext<PlaygroundDataContextValue | null>(null);
const PlaygroundActionsCtx = createContext<PlaygroundActionsContextValue | null>(null);
const PlaygroundUICtx = createContext<PlaygroundUIContextValue | null>(null);

/**
 * Wrap the playground page with this provider.
 * It calls usePlayground() + usePlaygroundUI() once and shares the result.
 */
export const PlaygroundProvider: FC<{ children: ReactNode }> = ({ children }) => {
  const ctx = usePlayground();
  const { entityTypes, selectedTypes } = ctx.recognition;

  const ui = usePlaygroundUI({
    isImageMode: ctx.isImageMode,
    content: ctx.content,
    entities: ctx.entities,
    entityTypes,
    selectedTypes,
    applyEntities: ctx.applyEntities,
    getTypeConfig: ctx.recognition.getTypeConfig,
  });

  // Data context — depends on frequently-changing values
  const dataValue = useMemo<PlaygroundDataContextValue>(() => ({
    stage: ctx.stage,
    fileInfo: ctx.fileInfo,
    content: ctx.content,
    isImageMode: ctx.isImageMode,
    entities: ctx.entities,
    boundingBoxes: ctx.boundingBoxes,
    visibleBoxes: ctx.visibleBoxes,
    isLoading: ctx.isLoading,
    loadingMessage: ctx.loadingMessage,
    loadingElapsedSec: ctx.loadingElapsedSec,
    entityMap: ctx.entityMap,
    redactedCount: ctx.redactedCount,
    redactionReport: ctx.redactionReport,
    reportOpen: ctx.reportOpen,
    versionHistory: ctx.versionHistory,
    versionHistoryOpen: ctx.versionHistoryOpen,
    selectedCount: ctx.selectedCount,
    canUndo: ctx.canUndo,
    canRedo: ctx.canRedo,
    entityHistory: ctx.entityHistory,
    imageHistory: ctx.imageHistory,
    imageUrl: ctx.imageUrl,
    redactedImageUrl: ctx.redactedImageUrl,
    recognition: ctx.recognition,
    dropzone: ctx.dropzone,
  }), [
    ctx.stage, ctx.fileInfo, ctx.content, ctx.isImageMode,
    ctx.entities, ctx.boundingBoxes, ctx.visibleBoxes,
    ctx.isLoading, ctx.loadingMessage, ctx.loadingElapsedSec,
    ctx.entityMap, ctx.redactedCount, ctx.redactionReport, ctx.reportOpen,
    ctx.versionHistory, ctx.versionHistoryOpen,
    ctx.selectedCount, ctx.canUndo, ctx.canRedo,
    ctx.entityHistory, ctx.imageHistory,
    ctx.imageUrl, ctx.redactedImageUrl,
    ctx.recognition, ctx.dropzone,
  ]);

  // Actions context — all callbacks, typically stable across renders
  const actionsValue = useMemo<PlaygroundActionsContextValue>(() => ({
    setStage: ctx.setStage,
    setEntities: ctx.setEntities,
    applyEntities: ctx.applyEntities,
    setBoundingBoxes: ctx.setBoundingBoxes,
    setReportOpen: ctx.setReportOpen,
    setVersionHistoryOpen: ctx.setVersionHistoryOpen,
    handleUndo: ctx.handleUndo,
    handleRedo: ctx.handleRedo,
    selectAll: ctx.selectAll,
    deselectAll: ctx.deselectAll,
    toggleBox: ctx.toggleBox,
    removeEntity: ctx.removeEntity,
    handleRerunNer: ctx.handleRerunNer,
    handleRedact: ctx.handleRedact,
    handleReset: ctx.handleReset,
    handleDownload: ctx.handleDownload,
    mergeVisibleBoxes: ctx.mergeVisibleBoxes,
    openPopout: ctx.openPopout,
  }), [
    ctx.setStage, ctx.setEntities, ctx.applyEntities, ctx.setBoundingBoxes,
    ctx.setReportOpen, ctx.setVersionHistoryOpen,
    ctx.handleUndo, ctx.handleRedo, ctx.selectAll, ctx.deselectAll,
    ctx.toggleBox, ctx.removeEntity,
    ctx.handleRerunNer, ctx.handleRedact, ctx.handleReset, ctx.handleDownload,
    ctx.mergeVisibleBoxes, ctx.openPopout,
  ]);

  // UI context — explicit property-level deps to avoid re-renders when `ui` ref changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const uiValue = useMemo(() => ui, [
    ui.selectedText, ui.selectionPos, ui.selectedTypeId, ui.setSelectedTypeId,
    ui.selectedOverlapIds,
    ui.clickedEntity, ui.setClickedEntity, ui.entityPopupPos, ui.setEntityPopupPos,
    ui.contentRef, ui.textScrollRef,
    ui.clearTextSelection, ui.handleTextSelect,
    ui.addManualEntity, ui.removeSelectedEntities,
    ui.handleEntityClick, ui.confirmRemoveEntity,
  ]);

  return (
    <PlaygroundActionsCtx.Provider value={actionsValue}>
      <PlaygroundDataCtx.Provider value={dataValue}>
        <PlaygroundUICtx.Provider value={uiValue}>
          {children}
        </PlaygroundUICtx.Provider>
      </PlaygroundDataCtx.Provider>
    </PlaygroundActionsCtx.Provider>
  );
};

/** Access the playground data context. Throws if used outside PlaygroundProvider. */
export function usePlaygroundDataContext(): PlaygroundDataContextValue {
  const ctx = useContext(PlaygroundDataCtx);
  if (!ctx) throw new Error('usePlaygroundDataContext must be used within PlaygroundProvider');
  return ctx;
}

/** Access the playground actions context. Throws if used outside PlaygroundProvider. */
export function usePlaygroundActionsContext(): PlaygroundActionsContextValue {
  const ctx = useContext(PlaygroundActionsCtx);
  if (!ctx) throw new Error('usePlaygroundActionsContext must be used within PlaygroundProvider');
  return ctx;
}

/**
 * Access the playground data/actions context merged.
 * Backward-compatible: returns the same shape as the old single context.
 * Note: This causes re-renders on both data AND action changes.
 * Prefer usePlaygroundDataContext() / usePlaygroundActionsContext() for new code.
 */
export function usePlaygroundContext(): PlaygroundContextValue {
  const data = usePlaygroundDataContext();
  const actions = usePlaygroundActionsContext();
  return { ...data, ...actions } as PlaygroundContextValue;
}

/** Access the playground UI context (selections, popups, etc.). */
export function usePlaygroundUIContext(): PlaygroundUIContextValue {
  const ctx = useContext(PlaygroundUICtx);
  if (!ctx) throw new Error('usePlaygroundUIContext must be used within PlaygroundProvider');
  return ctx;
}
