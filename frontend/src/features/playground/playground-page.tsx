
import { type FC, type MouseEvent as ReactMouseEvent, type ReactNode, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { showToast } from '@/components/Toast';
import { useT } from '@/i18n';
import { getEntityGroup, getEntityGroupLabel, getEntityTypeName } from '@/config/entityTypes';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import { EntityTypeGroupPicker } from '@/components/EntityTypeGroupPicker';
import { PlaygroundUpload } from './components/playground-upload';
import { PlaygroundToolbar } from './components/playground-toolbar';
import { PlaygroundEntityPanel } from './components/playground-entity-panel';
import { PlaygroundResult } from './components/playground-result';
import { PlaygroundLoading } from './components/playground-loading';
import { usePlayground } from './hooks/use-playground';
import { clampPopoverInCanvas, previewEntityHoverRingClass, previewEntityMarkStyle } from './utils';
import type { Entity } from './types';

function getSelectionOffsets(range: Range, root: HTMLElement): { start: number; end: number } | null {
  let start = -1;
  let end = -1;
  let offset = 0;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);

  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    const textLength = node.textContent?.length || 0;
    if (node === range.startContainer) start = offset + range.startOffset;
    if (node === range.endContainer) {
      end = offset + range.endOffset;
      break;
    }
    offset += textLength;
  }

  if (start === -1 || end === -1 || end <= start) return null;
  return { start, end };
}

export const Playground: FC = () => {
  const t = useT();
  const ctx = usePlayground();
  const {
    stage,
    setStage,
    fileInfo,
    content,
    isImageMode,
    entities,
    applyEntities,
    setBoundingBoxes,
    visibleBoxes,
    isLoading,
    loadingMessage,
    loadingElapsedSec,
    entityMap,
    redactedCount,
    redactionReport,
    reportOpen,
    setReportOpen,
    versionHistory,
    versionHistoryOpen,
    setVersionHistoryOpen,
    selectedCount,
    canUndo,
    canRedo,
    handleUndo,
    handleRedo,
    selectAll,
    deselectAll,
    toggleBox,
    removeEntity,
    handleRerunNer,
    handleRedact,
    handleReset,
    handleDownload,
    imageUrl,
    redactedImageUrl,
    mergeVisibleBoxes,
    openPopout,
    recognition,
    imageHistory,
  } = ctx;

  const [selectedText, setSelectedText] = useState<{ text: string; start: number; end: number } | null>(null);
  const [selectionPos, setSelectionPos] = useState<{ left: number; top: number } | null>(null);
  const [selectedTypeId, setSelectedTypeId] = useState('');
  const [selectedOverlapIds, setSelectedOverlapIds] = useState<string[]>([]);
  const [clickedEntity, setClickedEntity] = useState<Entity | null>(null);
  const [entityPopupPos, setEntityPopupPos] = useState<{ left: number; top: number } | null>(null);

  const contentRef = useRef<HTMLDivElement>(null);
  const textScrollRef = useRef<HTMLDivElement>(null);
  const selectionRangeRef = useRef<Range | null>(null);

  const { entityTypes, selectedTypes } = recognition;

  useEffect(() => {
    if (!selectedTypeId && entityTypes.length > 0) {
      setSelectedTypeId(entityTypes[0].id);
    }
  }, [entityTypes, selectedTypeId]);

  const clearTextSelection = useCallback(() => {
    selectionRangeRef.current = null;
    setSelectedText(null);
    setSelectionPos(null);
    setSelectedOverlapIds([]);
  }, []);

  const handleTextSelect = useCallback(() => {
    if (isImageMode || clickedEntity) return;

    const selection = window.getSelection();
    if (!selection || !contentRef.current) {
      clearTextSelection();
      return;
    }

    if (selection.isCollapsed) {
      if (!selectedText || !selectionPos) clearTextSelection();
      return;
    }

    const text = selection.toString().trim();
    if (!text || text.length < 2) {
      clearTextSelection();
      return;
    }

    const range = selection.getRangeAt(0);
    if (!contentRef.current.contains(range.commonAncestorContainer)) {
      clearTextSelection();
      return;
    }

    const offsets = getSelectionOffsets(range, contentRef.current);
    const start = offsets?.start ?? content.indexOf(text);
    const end = offsets?.end ?? (start + text.length);
    if (start < 0 || end < 0) {
      clearTextSelection();
      return;
    }

    const overlaps = entities.filter((entity) =>
      (entity.start <= start && entity.end > start) || (entity.start < end && entity.end >= end),
    );

    try {
      selectionRangeRef.current = range.cloneRange();
    } catch {
      clearTextSelection();
      return;
    }

    setSelectedOverlapIds(overlaps.map((entity) => entity.id));
    if (overlaps.length > 0) {
      setSelectedTypeId(overlaps[0].type);
    } else if (!selectedTypeId) {
      const fallbackType = entityTypes.find((entityType) => selectedTypes.includes(entityType.id))?.id || entityTypes[0]?.id;
      if (fallbackType) setSelectedTypeId(fallbackType);
    }

    setSelectionPos(null);
    setSelectedText({ text, start, end });
  }, [clearTextSelection, clickedEntity, content, entities, entityTypes, isImageMode, selectedText, selectedTypeId, selectedTypes, selectionPos]);

  useLayoutEffect(() => {
    if (!selectedText) {
      selectionRangeRef.current = null;
      setSelectionPos(null);
      return;
    }

    const root = contentRef.current;
    if (!root) return;

    const update = () => {
      const range = selectionRangeRef.current;
      if (!range || range.collapsed) {
        setSelectionPos(null);
        return;
      }

      let rect: DOMRect;
      try {
        rect = range.getBoundingClientRect();
      } catch {
        setSelectionPos(null);
        return;
      }

      if (rect.width === 0 && rect.height === 0) return;
      setSelectionPos(clampPopoverInCanvas(rect, root.getBoundingClientRect(), 400, 400));
    };

    update();

    const scrollEl = textScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [selectedText]);

  useLayoutEffect(() => {
    if (!clickedEntity) {
      setEntityPopupPos(null);
      return;
    }

    const root = contentRef.current;
    if (!root) return;

    const update = () => {
      let element: HTMLElement | null = null;
      try {
        element = root.querySelector(`[data-entity-id="${CSS.escape(clickedEntity.id)}"]`);
      } catch {
        element = null;
      }

      if (!element) return;
      setEntityPopupPos(clampPopoverInCanvas(element.getBoundingClientRect(), root.getBoundingClientRect(), 260, 220));
    };

    update();

    const scrollEl = textScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [clickedEntity]);

  const addManualEntity = useCallback((typeId: string) => {
    if (!selectedText) return;

    const newEntity: Entity = {
      id: `manual_${Date.now()}`,
      text: selectedText.text,
      type: typeId,
      start: selectedText.start,
      end: selectedText.end,
      selected: true,
      source: 'manual',
    };

    const nextEntities = entities
      .filter((entity) => !selectedOverlapIds.includes(entity.id))
      .concat(newEntity)
      .sort((left, right) => left.start - right.start);

    applyEntities(nextEntities);
    showToast(
      selectedOverlapIds.length > 0
        ? t('playground.toast.updated')
        : t('playground.toast.added').replace('{name}', recognition.getTypeConfig(typeId).name),
      'success',
    );
    clearTextSelection();
    window.getSelection()?.removeAllRanges();
  }, [applyEntities, clearTextSelection, entities, recognition, selectedOverlapIds, selectedText, t]);

  const removeSelectedEntities = useCallback(() => {
    if (selectedOverlapIds.length === 0) return;
    applyEntities(entities.filter((entity) => !selectedOverlapIds.includes(entity.id)));
    clearTextSelection();
    window.getSelection()?.removeAllRanges();
    showToast(t('playground.toast.removed'), 'info');
  }, [applyEntities, clearTextSelection, entities, selectedOverlapIds, t]);

  const handleEntityClick = useCallback((entity: Entity, event: ReactMouseEvent) => {
    event.stopPropagation();
    clearTextSelection();
    setClickedEntity(entity);
    setSelectedTypeId(entity.type);
  }, [clearTextSelection]);

  const confirmRemoveEntity = useCallback(() => {
    if (clickedEntity) {
      applyEntities(entities.filter((entity) => entity.id !== clickedEntity.id));
      showToast(t('playground.toast.removed'), 'info');
    }
    setClickedEntity(null);
    setEntityPopupPos(null);
  }, [applyEntities, clickedEntity, entities, t]);

  const renderMarkedContent = () => {
    if (!content) {
      return <p className="text-muted-foreground">{t('playground.noContent')}</p>;
    }

    const sortedEntities = [...entities].sort((left, right) => left.start - right.start);
    const segments: ReactNode[] = [];
    let lastEnd = 0;

    sortedEntities.forEach((entity) => {
      if (entity.start < lastEnd) return;

      if (entity.start > lastEnd) {
        segments.push(<span key={`text-${lastEnd}`}>{content.slice(lastEnd, entity.start)}</span>);
      }

      const typeName = getEntityTypeName(entity.type);
      const sourceLabel = entity.source === 'regex'
        ? t('playground.sourceRegex')
        : entity.source === 'manual'
          ? t('playground.sourceManual')
          : t('playground.sourceAi');

      segments.push(
        <span
          key={entity.id}
          data-entity-id={entity.id}
          onClick={(event) => handleEntityClick(entity, event)}
          style={previewEntityMarkStyle(entity)}
          className={`-mx-0.5 inline-flex cursor-pointer items-center gap-0.5 rounded px-0.5 transition-all hover:ring-2 hover:ring-offset-1 hover:shadow-sm ${previewEntityHoverRingClass(entity.source)}`}
          title={`${typeName} [${sourceLabel}]`}
        >
          {content.slice(entity.start, entity.end)}
        </span>,
      );

      lastEnd = entity.end;
    });

    if (lastEnd < content.length) {
      segments.push(<span key="content-end">{content.slice(lastEnd)}</span>);
    }

    return segments;
  };

  return (
    <div className="playground-root saas-page flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background" data-testid="playground">
      {stage === 'upload' && (
        <div className="page-shell !max-w-[min(100%,2048px)] !px-3 !pt-4 sm:!px-5 sm:!pt-5 2xl:!px-8">
          <PlaygroundUpload ctx={ctx} />
        </div>
      )}

      {stage === 'preview' && (
        <div className="flex flex-1 min-h-0 min-w-0 flex-col gap-3 overflow-auto p-3 sm:p-5 lg:flex-row lg:overflow-hidden">
          <div className="saas-panel flex min-w-0 flex-1 flex-col overflow-hidden">
            <PlaygroundToolbar
              filename={fileInfo?.filename}
              isImageMode={isImageMode}
              canUndo={canUndo}
              canRedo={canRedo}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onReset={handleReset}
              hintText={
                isImageMode
                  ? t('playground.previewHint.image')
                  : t('playground.previewHint.text')
              }
              onPopout={isImageMode ? openPopout : undefined}
            />

            <div
              ref={contentRef}
              onMouseUp={handleTextSelect}
              onKeyUp={handleTextSelect}
              className="flex min-h-0 flex-1 flex-col overflow-hidden select-text"
            >
              {isImageMode ? (
                <div className="flex-1 min-h-0">
                  {fileInfo && (
                    <ImageBBoxEditor
                      imageSrc={imageUrl}
                      boxes={visibleBoxes}
                      onBoxesChange={(nextBoxes) => setBoundingBoxes(mergeVisibleBoxes(nextBoxes))}
                      onBoxesCommit={(previousBoxes, nextBoxes) => {
                        imageHistory.save(mergeVisibleBoxes(previousBoxes, nextBoxes));
                        setBoundingBoxes(mergeVisibleBoxes(nextBoxes, previousBoxes));
                      }}
                      getTypeConfig={recognition.getVisionTypeConfig}
                      availableTypes={recognition.visionTypes.map((visionType) => ({
                        id: visionType.id,
                        name: visionType.name,
                        color: '#6366F1',
                      }))}
                      defaultType={recognition.visionTypes[0]?.id || 'CUSTOM'}
                    />
                  )}
                </div>
              ) : (
                <div ref={textScrollRef} className="flex-1 min-h-0 overflow-auto">
                  <div className="p-4 font-[system-ui] text-sm leading-relaxed whitespace-pre-wrap">
                    {renderMarkedContent()}
                  </div>
                </div>
              )}

              {!isImageMode && selectedText && selectionPos && (
                <div
                  className="fixed z-50 min-w-[320px] max-w-[420px] animate-scale-in rounded-[24px] border border-border/70 bg-[var(--surface-overlay)] p-4 shadow-[var(--shadow-floating)]"
                  style={{ left: selectionPos.left, top: selectionPos.top }}
                  onMouseDown={(event) => event.stopPropagation()}
                  onMouseUp={(event) => event.stopPropagation()}
                >
                  <div className="mb-3">
                    <div className="mb-1 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                      {t('playground.selectedText')}
                    </div>
                    <div className="break-all rounded-2xl border border-border/70 bg-muted/35 px-3 py-3 text-sm text-foreground">
                      {selectedText.text}
                    </div>
                  </div>

                  <div className="mb-3">
                    <div className="mb-2 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                      {t('playground.selectType')}
                    </div>
                    <EntityTypeGroupPicker
                      entityTypes={entityTypes}
                      selectedTypeId={selectedTypeId}
                      onSelectType={setSelectedTypeId}
                    />
                  </div>

                  <div className="flex gap-2 border-t border-border/60 pt-3">
                    <Button
                      onClick={() => addManualEntity(selectedTypeId)}
                      disabled={!selectedTypeId}
                      className="flex-1"
                    >
                      {selectedOverlapIds.length > 0 ? t('playground.updateAnnotation') : t('playground.addAnnotation')}
                    </Button>
                    {selectedOverlapIds.length > 0 && (
                      <Button variant="outline" onClick={removeSelectedEntities} className="border-destructive/30 text-destructive hover:bg-destructive/10">
                        {t('playground.remove')}
                      </Button>
                    )}
                    <Button variant="ghost" onClick={clearTextSelection}>
                      {t('common.cancel')}
                    </Button>
                  </div>
                </div>
              )}

              {!isImageMode && clickedEntity && entityPopupPos && (
                <div
                  className="fixed z-50 min-w-[220px] animate-scale-in rounded-[22px] border border-border/70 bg-[var(--surface-overlay)] p-4 shadow-[var(--shadow-floating)]"
                  style={{ left: entityPopupPos.left, top: entityPopupPos.top }}
                  onMouseDown={(event) => event.stopPropagation()}
                  onMouseUp={(event) => event.stopPropagation()}
                >
                  <div className="mb-3">
                    <div className="mb-2 flex items-center gap-2">
                      <span className="rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-[11px] text-muted-foreground">
                        {getEntityGroupLabel(getEntityGroup(clickedEntity.type)?.id ?? 'other')}
                        {' / '}
                        {getEntityTypeName(clickedEntity.type)}
                      </span>
                    </div>
                    <div className="break-all rounded-2xl border border-border/70 bg-muted/35 px-3 py-3 text-sm text-foreground">
                      {clickedEntity.text}
                    </div>
                  </div>

                  <div className="flex flex-col gap-2">
                    <Button variant="outline" className="border-destructive/30 text-destructive hover:bg-destructive/10" onClick={confirmRemoveEntity}>
                      {t('playground.removeAnnotation')}
                    </Button>
                    <Button variant="ghost" onClick={() => { setClickedEntity(null); setEntityPopupPos(null); }}>
                      {t('common.cancel')}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>

          <PlaygroundEntityPanel
            isImageMode={isImageMode}
            isLoading={isLoading}
            entities={entities}
            visibleBoxes={visibleBoxes}
            selectedCount={selectedCount}
            replacementMode={recognition.replacementMode}
            setReplacementMode={recognition.setReplacementMode}
            clearPlaygroundTextPresetTracking={recognition.clearPlaygroundTextPresetTracking}
            onRerunNer={handleRerunNer}
            onRedact={handleRedact}
            onSelectAll={selectAll}
            onDeselectAll={deselectAll}
            onToggleBox={toggleBox}
            onEntityClick={handleEntityClick}
            onRemoveEntity={removeEntity}
          />
        </div>
      )}

      {stage === 'result' && (
        <PlaygroundResult
          fileInfo={fileInfo}
          content={content}
          entities={entities}
          entityMap={entityMap}
          redactedCount={redactedCount}
          redactionReport={redactionReport}
          reportOpen={reportOpen}
          setReportOpen={setReportOpen}
          versionHistory={versionHistory}
          versionHistoryOpen={versionHistoryOpen}
          setVersionHistoryOpen={setVersionHistoryOpen}
          isImageMode={isImageMode}
          imageUrl={imageUrl}
          redactedImageUrl={redactedImageUrl}
          visibleBoxes={visibleBoxes}
          visionTypes={recognition.visionTypes}
          getVisionTypeConfig={recognition.getVisionTypeConfig}
          onBackToEdit={() => setStage('preview')}
          onReset={handleReset}
          onDownload={handleDownload}
        />
      )}

      {isLoading && (
        <PlaygroundLoading
          loadingMessage={loadingMessage}
          isImageMode={isImageMode}
          elapsedSec={loadingElapsedSec}
        />
      )}
    </div>
  );
};
