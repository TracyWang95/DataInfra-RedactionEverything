// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { createContext, useContext, useMemo, type FC, type ReactNode } from 'react';
import { usePlayground } from './hooks/use-playground';
import { usePlaygroundUI } from './hooks/use-playground-ui';

export type PlaygroundContextValue = ReturnType<typeof usePlayground>;
export type PlaygroundUIContextValue = ReturnType<typeof usePlaygroundUI>;

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
  uploadIssue: PlaygroundContextValue['uploadIssue'];
  recognitionIssue: PlaygroundContextValue['recognitionIssue'];
  entityMap: PlaygroundContextValue['entityMap'];
  redactedCount: PlaygroundContextValue['redactedCount'];
  redactionReport: PlaygroundContextValue['redactionReport'];
  reportOpen: PlaygroundContextValue['reportOpen'];
  resetConfirmOpen: PlaygroundContextValue['resetConfirmOpen'];
  versionHistory: PlaygroundContextValue['versionHistory'];
  versionHistoryOpen: PlaygroundContextValue['versionHistoryOpen'];
  selectedCount: PlaygroundContextValue['selectedCount'];
  canUndo: PlaygroundContextValue['canUndo'];
  canRedo: PlaygroundContextValue['canRedo'];
  entityHistory: PlaygroundContextValue['entityHistory'];
  imageHistory: PlaygroundContextValue['imageHistory'];
  imageUrl: PlaygroundContextValue['imageUrl'];
  redactedImageUrl: PlaygroundContextValue['redactedImageUrl'];
  redactedImageError: PlaygroundContextValue['redactedImageError'];
  currentPage: PlaygroundContextValue['currentPage'];
  totalPages: PlaygroundContextValue['totalPages'];
  recognition: PlaygroundContextValue['recognition'];
  dropzone: PlaygroundContextValue['dropzone'];
}

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
  cancelProcessing: PlaygroundContextValue['cancelProcessing'];
  handleReset: PlaygroundContextValue['handleReset'];
  confirmReset: PlaygroundContextValue['confirmReset'];
  cancelReset: PlaygroundContextValue['cancelReset'];
  handleDownload: PlaygroundContextValue['handleDownload'];
  mergeVisibleBoxes: PlaygroundContextValue['mergeVisibleBoxes'];
  setCurrentPage: PlaygroundContextValue['setCurrentPage'];
  openPopout: PlaygroundContextValue['openPopout'];
}

const PlaygroundDataCtx = createContext<PlaygroundDataContextValue | null>(null);
const PlaygroundActionsCtx = createContext<PlaygroundActionsContextValue | null>(null);
const PlaygroundUICtx = createContext<PlaygroundUIContextValue | null>(null);

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

  const dataValue = useMemo<PlaygroundDataContextValue>(
    () => ({
      stage: ctx.stage,
      fileInfo: ctx.fileInfo,
      content: ctx.content,
      isImageMode: ctx.isImageMode,
      entities: ctx.entities,
      boundingBoxes: ctx.boundingBoxes,
      visibleBoxes: ctx.visibleBoxes,
      isLoading: ctx.isLoading,
      loadingMessage: ctx.loadingMessage,
      uploadIssue: ctx.uploadIssue,
      recognitionIssue: ctx.recognitionIssue,
      entityMap: ctx.entityMap,
      redactedCount: ctx.redactedCount,
      redactionReport: ctx.redactionReport,
      reportOpen: ctx.reportOpen,
      resetConfirmOpen: ctx.resetConfirmOpen,
      versionHistory: ctx.versionHistory,
      versionHistoryOpen: ctx.versionHistoryOpen,
      selectedCount: ctx.selectedCount,
      canUndo: ctx.canUndo,
      canRedo: ctx.canRedo,
      entityHistory: ctx.entityHistory,
      imageHistory: ctx.imageHistory,
      imageUrl: ctx.imageUrl,
      redactedImageUrl: ctx.redactedImageUrl,
      redactedImageError: ctx.redactedImageError,
      currentPage: ctx.currentPage,
      totalPages: ctx.totalPages,
      recognition: ctx.recognition,
      dropzone: ctx.dropzone,
    }),
    [
      ctx.stage,
      ctx.fileInfo,
      ctx.content,
      ctx.isImageMode,
      ctx.entities,
      ctx.boundingBoxes,
      ctx.visibleBoxes,
      ctx.isLoading,
      ctx.loadingMessage,
      ctx.uploadIssue,
      ctx.recognitionIssue,
      ctx.entityMap,
      ctx.redactedCount,
      ctx.redactionReport,
      ctx.reportOpen,
      ctx.resetConfirmOpen,
      ctx.versionHistory,
      ctx.versionHistoryOpen,
      ctx.selectedCount,
      ctx.canUndo,
      ctx.canRedo,
      ctx.entityHistory,
      ctx.imageHistory,
      ctx.imageUrl,
      ctx.redactedImageUrl,
      ctx.redactedImageError,
      ctx.currentPage,
      ctx.totalPages,
      ctx.recognition,
      ctx.dropzone,
    ],
  );

  const actionsValue = useMemo<PlaygroundActionsContextValue>(
    () => ({
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
      cancelProcessing: ctx.cancelProcessing,
      handleReset: ctx.handleReset,
      confirmReset: ctx.confirmReset,
      cancelReset: ctx.cancelReset,
      handleDownload: ctx.handleDownload,
      mergeVisibleBoxes: ctx.mergeVisibleBoxes,
      setCurrentPage: ctx.setCurrentPage,
      openPopout: ctx.openPopout,
    }),
    [
      ctx.setStage,
      ctx.setEntities,
      ctx.applyEntities,
      ctx.setBoundingBoxes,
      ctx.setReportOpen,
      ctx.setVersionHistoryOpen,
      ctx.handleUndo,
      ctx.handleRedo,
      ctx.selectAll,
      ctx.deselectAll,
      ctx.toggleBox,
      ctx.removeEntity,
      ctx.handleRerunNer,
      ctx.handleRedact,
      ctx.cancelProcessing,
      ctx.handleReset,
      ctx.confirmReset,
      ctx.cancelReset,
      ctx.handleDownload,
      ctx.mergeVisibleBoxes,
      ctx.setCurrentPage,
      ctx.openPopout,
    ],
  );

  // Keep UI context reference stable across unrelated state changes.
  const uiValue = useMemo<PlaygroundUIContextValue>(
    () => ({
      selectedText: ui.selectedText,
      selectionPos: ui.selectionPos,
      selectedTypeId: ui.selectedTypeId,
      setSelectedTypeId: ui.setSelectedTypeId,
      selectedOverlapIds: ui.selectedOverlapIds,
      clickedEntity: ui.clickedEntity,
      setClickedEntity: ui.setClickedEntity,
      entityPopupPos: ui.entityPopupPos,
      setEntityPopupPos: ui.setEntityPopupPos,
      contentRef: ui.contentRef,
      textScrollRef: ui.textScrollRef,
      clearTextSelection: ui.clearTextSelection,
      handleTextSelect: ui.handleTextSelect,
      addManualEntity: ui.addManualEntity,
      removeSelectedEntities: ui.removeSelectedEntities,
      handleEntityClick: ui.handleEntityClick,
      getTypeConfig: ui.getTypeConfig,
      confirmRemoveEntity: ui.confirmRemoveEntity,
    }),
    [
      ui.selectedText,
      ui.selectionPos,
      ui.selectedTypeId,
      ui.setSelectedTypeId,
      ui.selectedOverlapIds,
      ui.clickedEntity,
      ui.setClickedEntity,
      ui.entityPopupPos,
      ui.setEntityPopupPos,
      ui.contentRef,
      ui.textScrollRef,
      ui.clearTextSelection,
      ui.handleTextSelect,
      ui.addManualEntity,
      ui.removeSelectedEntities,
      ui.handleEntityClick,
      ui.getTypeConfig,
      ui.confirmRemoveEntity,
    ],
  );

  return (
    <PlaygroundActionsCtx.Provider value={actionsValue}>
      <PlaygroundDataCtx.Provider value={dataValue}>
        <PlaygroundUICtx.Provider value={uiValue}>{children}</PlaygroundUICtx.Provider>
      </PlaygroundDataCtx.Provider>
    </PlaygroundActionsCtx.Provider>
  );
};

export function usePlaygroundDataContext(): PlaygroundDataContextValue {
  const ctx = useContext(PlaygroundDataCtx);
  if (!ctx) throw new Error('usePlaygroundDataContext must be used within PlaygroundProvider');
  return ctx;
}

export function usePlaygroundActionsContext(): PlaygroundActionsContextValue {
  const ctx = useContext(PlaygroundActionsCtx);
  if (!ctx) throw new Error('usePlaygroundActionsContext must be used within PlaygroundProvider');
  return ctx;
}

export function usePlaygroundContext(): PlaygroundContextValue {
  const data = usePlaygroundDataContext();
  const actions = usePlaygroundActionsContext();
  return { ...data, ...actions } as PlaygroundContextValue;
}

export function usePlaygroundUIContext(): PlaygroundUIContextValue {
  const ctx = useContext(PlaygroundUICtx);
  if (!ctx) throw new Error('usePlaygroundUIContext must be used within PlaygroundProvider');
  return ctx;
}
