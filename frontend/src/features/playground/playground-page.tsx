/**
 * Playground page orchestrator.
 * Composes upload, toolbar, entity panel, result, and loading overlay
 * based on the current stage from the use-playground hook.
 */
import { type FC, useState, useCallback, useRef, useLayoutEffect } from 'react';
import { usePlayground } from './hooks/use-playground';
import { PlaygroundUpload } from './components/playground-upload';
import { PlaygroundToolbar } from './components/playground-toolbar';
import { PlaygroundEntityPanel } from './components/playground-entity-panel';
import { PlaygroundResult } from './components/playground-result';
import { PlaygroundLoading } from './components/playground-loading';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import { EntityTypeGroupPicker } from '@/components/EntityTypeGroupPicker';
import { getEntityTypeName, getEntityGroup } from '@/config/entityTypes';
import { showToast } from '@/components/Toast';
import { t } from '@/i18n';
import { clampPopoverInCanvas, previewEntityMarkStyle, previewEntityHoverRingClass } from './utils';
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
    if (node === range.endContainer) { end = offset + range.endOffset; break; }
    offset += textLength;
  }
  if (start === -1 || end === -1 || end <= start) return null;
  return { start, end };
}

export const Playground: FC = () => {
  const ctx = usePlayground();
  const {
    stage, setStage, fileInfo, content, isImageMode,
    entities, applyEntities,
    setBoundingBoxes, visibleBoxes,
    isLoading, loadingMessage, loadingElapsedSec,
    entityMap, redactedCount, redactionReport, reportOpen, setReportOpen,
    versionHistory, versionHistoryOpen, setVersionHistoryOpen,
    selectedCount, canUndo, canRedo, handleUndo, handleRedo,
    selectAll, deselectAll, toggleBox, removeEntity,
    handleRerunNer, handleRedact, handleReset, handleDownload,
    imageUrl, redactedImageUrl, mergeVisibleBoxes, openPopout,
    recognition, imageHistory,
  } = ctx;

  // --- Text selection state (preview stage) ---
  const [selectedText, setSelectedText] = useState<{ text: string; start: number; end: number } | null>(null);
  const [selectionPos, setSelectionPos] = useState<{ left: number; top: number } | null>(null);
  const [selectedTypeId, setSelectedTypeId] = useState('');
  const [selectedOverlapIds, setSelectedOverlapIds] = useState<string[]>([]);
  const [clickedEntity, setClickedEntity] = useState<Entity | null>(null);
  const [entityPopupPos, setEntityPopupPos] = useState<{ left: number; top: number } | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const textScrollRef = useRef<HTMLDivElement>(null);
  const selectionRangeRef = useRef<Range | null>(null);

  // Set default type id when entity types load
  const { entityTypes, selectedTypes } = recognition;
  if (!selectedTypeId && entityTypes.length > 0) {
    setSelectedTypeId(entityTypes[0].id);
  }

  // --- Text selection handler ---
  const handleTextSelect = useCallback(() => {
    if (isImageMode || clickedEntity) return;
    const selection = window.getSelection();
    if (!selection || !contentRef.current) { clearTextSelection(); return; }
    if (selection.isCollapsed) { if (!selectedText || !selectionPos) clearTextSelection(); return; }
    const text = selection.toString().trim();
    if (!text || text.length < 2) { clearTextSelection(); return; }
    const range = selection.getRangeAt(0);
    if (!contentRef.current.contains(range.commonAncestorContainer)) { clearTextSelection(); return; }
    const offsets = getSelectionOffsets(range, contentRef.current);
    const start = offsets?.start ?? content.indexOf(text);
    const end = offsets?.end ?? (start + text.length);
    if (start < 0 || end < 0) { clearTextSelection(); return; }
    const overlaps = entities.filter(e => (e.start <= start && e.end > start) || (e.start < end && e.end >= end));
    try { selectionRangeRef.current = range.cloneRange(); } catch { clearTextSelection(); return; }
    setSelectedOverlapIds(overlaps.map(e => e.id));
    if (overlaps.length > 0) setSelectedTypeId(overlaps[0].type);
    else if (!selectedTypeId) { const ft = entityTypes.find(et => selectedTypes.includes(et.id))?.id || entityTypes[0]?.id; if (ft) setSelectedTypeId(ft); }
    setSelectionPos(null);
    setSelectedText({ text, start, end });
  }, [isImageMode, clickedEntity, content, entities, selectedTypeId, entityTypes, selectedTypes, selectedText, selectionPos]);

  const clearTextSelection = useCallback(() => {
    selectionRangeRef.current = null;
    setSelectedText(null); setSelectionPos(null); setSelectedOverlapIds([]);
  }, []);

  // --- Selection position tracking ---
  useLayoutEffect(() => {
    if (!selectedText) { selectionRangeRef.current = null; setSelectionPos(null); return; }
    const root = contentRef.current;
    if (!root) return;
    const update = () => {
      const range = selectionRangeRef.current;
      if (!range || range.collapsed) { setSelectionPos(null); return; }
      let rect: DOMRect;
      try { rect = range.getBoundingClientRect(); } catch { setSelectionPos(null); return; }
      if (rect.width === 0 && rect.height === 0) return;
      setSelectionPos(clampPopoverInCanvas(rect, root.getBoundingClientRect(), 400, 400));
    };
    update();
    const scrollEl = textScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => { window.removeEventListener('resize', update); scrollEl?.removeEventListener('scroll', update); };
  }, [selectedText]);

  useLayoutEffect(() => {
    if (!clickedEntity) { setEntityPopupPos(null); return; }
    const root = contentRef.current;
    if (!root) return;
    const update = () => {
      let el: HTMLElement | null = null;
      try { el = root.querySelector(`[data-entity-id="${CSS.escape(clickedEntity.id)}"]`); } catch { el = null; }
      if (!el) return;
      setEntityPopupPos(clampPopoverInCanvas(el.getBoundingClientRect(), root.getBoundingClientRect(), 240, 220));
    };
    update();
    const scrollEl = textScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => { window.removeEventListener('resize', update); scrollEl?.removeEventListener('scroll', update); };
  }, [clickedEntity]);

  // --- Manual entity operations ---
  const addManualEntity = useCallback((typeId: string) => {
    if (!selectedText) return;
    const ne: Entity = { id: `manual_${Date.now()}`, text: selectedText.text, type: typeId, start: selectedText.start, end: selectedText.end, selected: true, source: 'manual' };
    const next = entities.filter(e => !selectedOverlapIds.includes(e.id)).concat(ne).sort((a, b) => a.start - b.start);
    applyEntities(next);
    showToast(selectedOverlapIds.length > 0 ? '已更新标记' : `已添加: ${recognition.getTypeConfig(typeId).name}`, 'success');
    clearTextSelection();
    window.getSelection()?.removeAllRanges();
  }, [selectedText, entities, selectedOverlapIds, applyEntities, recognition, clearTextSelection]);

  const removeSelectedEntities = useCallback(() => {
    if (selectedOverlapIds.length === 0) return;
    applyEntities(entities.filter(e => !selectedOverlapIds.includes(e.id)));
    clearTextSelection();
    window.getSelection()?.removeAllRanges();
    showToast('已删除标记', 'info');
  }, [selectedOverlapIds, entities, applyEntities, clearTextSelection]);

  const handleEntityClick = useCallback((entity: Entity, event: React.MouseEvent) => {
    event.stopPropagation();
    clearTextSelection();
    setClickedEntity(entity);
    setSelectedTypeId(entity.type);
  }, [clearTextSelection]);

  const confirmRemoveEntity = useCallback(() => {
    if (clickedEntity) { applyEntities(entities.filter(e => e.id !== clickedEntity.id)); showToast('已移除标注', 'info'); }
    setClickedEntity(null); setEntityPopupPos(null);
  }, [clickedEntity, entities, applyEntities]);

  // --- Render marked content ---
  const renderMarkedContent = () => {
    if (!content) return <p className="text-muted-foreground">{t('playground.noContent') || '暂无内容'}</p>;
    const sorted = [...entities].sort((a, b) => a.start - b.start);
    const segs: React.ReactNode[] = [];
    let lastEnd = 0;
    sorted.forEach(entity => {
      if (entity.start < lastEnd) return;
      if (entity.start > lastEnd) segs.push(<span key={`t-${lastEnd}`}>{content.slice(lastEnd, entity.start)}</span>);
      const typeName = getEntityTypeName(entity.type);
      const sourceLabel = entity.source === 'regex' ? '正则' : entity.source === 'manual' ? '手动' : 'AI';
      segs.push(
        <span key={entity.id} data-entity-id={entity.id} onClick={(e) => handleEntityClick(entity, e)} style={previewEntityMarkStyle(entity)} className={`cursor-pointer transition-all inline-flex items-center gap-0.5 rounded px-0.5 -mx-0.5 hover:ring-2 hover:ring-offset-1 hover:shadow-sm ${previewEntityHoverRingClass(entity.source)}`} title={`${typeName} [${sourceLabel}] - 点击编辑或移除`}>
          {content.slice(entity.start, entity.end)}
        </span>,
      );
      lastEnd = entity.end;
    });
    if (lastEnd < content.length) segs.push(<span key="end">{content.slice(lastEnd)}</span>);
    return segs;
  };

  return (
    <div className="playground-root h-full min-h-0 min-w-0 flex flex-col overflow-hidden bg-muted/30" data-testid="playground">
      {stage === 'upload' && <PlaygroundUpload ctx={ctx} />}

      {stage === 'preview' && (
        <div className="flex-1 flex flex-col lg:flex-row gap-2 sm:gap-3 p-2 sm:p-3 min-h-0 min-w-0 overflow-auto lg:overflow-hidden">
          <div className="flex-1 flex flex-col bg-background rounded-xl border overflow-hidden min-w-0">
            <PlaygroundToolbar filename={fileInfo?.filename} isImageMode={isImageMode} canUndo={canUndo} canRedo={canRedo} onUndo={handleUndo} onRedo={handleRedo} onReset={handleReset} hintText={isImageMode ? '拖拽框选添加区域 | 点击区域切换脱敏状态' : '点击高亮文字切换脱敏状态 | 划选文字添加新标记'} onPopout={isImageMode ? openPopout : undefined} />
            <div ref={contentRef} onMouseUp={handleTextSelect} onKeyUp={handleTextSelect} className="flex-1 overflow-hidden select-text flex flex-col" style={{ minHeight: 0 }}>
              {isImageMode ? (
                <div className="flex-1 min-h-0">
                  {fileInfo && <ImageBBoxEditor imageSrc={imageUrl} boxes={visibleBoxes} onBoxesChange={(nb) => setBoundingBoxes(mergeVisibleBoxes(nb))} onBoxesCommit={(pb, nb) => { imageHistory.save(mergeVisibleBoxes(pb, nb)); setBoundingBoxes(mergeVisibleBoxes(nb, pb)); }} getTypeConfig={recognition.getVisionTypeConfig} availableTypes={recognition.visionTypes.map(vt => ({ id: vt.id, name: vt.name, color: '#6366F1' }))} defaultType={recognition.visionTypes[0]?.id || 'CUSTOM'} />}
                </div>
              ) : (
                <div ref={textScrollRef} className="flex-1 overflow-auto min-h-0">
                  <div className="whitespace-pre-wrap text-sm leading-relaxed font-[system-ui] p-4">{renderMarkedContent()}</div>
                </div>
              )}
              {/* Text selection popover */}
              {!isImageMode && selectedText && selectionPos && (
                <div className="fixed z-50 bg-background border rounded-2xl shadow-2xl p-4 min-w-[320px] max-w-[400px]" style={{ left: selectionPos.left, top: selectionPos.top }} onMouseDown={e => e.stopPropagation()} onMouseUp={e => e.stopPropagation()}>
                  <div className="mb-3"><div className="text-[10px] text-muted-foreground mb-1 font-medium">{t('playground.selectedText') || '选中文本'}</div><div className="text-sm bg-muted rounded-lg px-3 py-2 break-all border">{selectedText.text}</div></div>
                  <div className="mb-3"><div className="text-[10px] text-muted-foreground mb-2 font-medium">{t('playground.selectType') || '选择类型'}</div><EntityTypeGroupPicker entityTypes={entityTypes} selectedTypeId={selectedTypeId} onSelectType={setSelectedTypeId} /></div>
                  <div className="flex gap-2 pt-2 border-t">
                    <button onClick={() => addManualEntity(selectedTypeId)} disabled={!selectedTypeId} className="flex-1 text-sm font-medium bg-primary text-primary-foreground rounded-lg px-3 py-2 hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed">{selectedOverlapIds.length > 0 ? '更新标记' : '添加标记'}</button>
                    {selectedOverlapIds.length > 0 && <button onClick={removeSelectedEntities} className="text-sm font-medium text-destructive border border-destructive/30 rounded-lg px-3 py-2 hover:bg-destructive/5">删除</button>}
                    <button onClick={clearTextSelection} className="text-sm text-muted-foreground border rounded-lg px-3 py-2 hover:bg-accent">取消</button>
                  </div>
                </div>
              )}
              {/* Entity click popover */}
              {!isImageMode && clickedEntity && entityPopupPos && (
                <div className="fixed z-50 bg-background border rounded-xl shadow-2xl p-3 min-w-[200px]" style={{ left: entityPopupPos.left, top: entityPopupPos.top }} onMouseDown={e => e.stopPropagation()} onMouseUp={e => e.stopPropagation()}>
                  <div className="mb-3">
                    <div className="flex items-center gap-2 mb-1.5"><span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-muted">{getEntityGroup(clickedEntity.type)?.label} · {getEntityTypeName(clickedEntity.type)}</span></div>
                    <div className="text-sm font-medium px-2 py-1.5 rounded-lg break-all bg-muted border">{clickedEntity.text}</div>
                  </div>
                  <div className="space-y-1.5">
                    <button onClick={confirmRemoveEntity} className="w-full text-sm font-medium text-destructive border border-destructive/30 rounded-lg px-3 py-2 hover:bg-destructive/5 flex items-center justify-center gap-1.5">{t('playground.removeAnnotation') || '移除此标注'}</button>
                    <button onClick={() => { setClickedEntity(null); setEntityPopupPos(null); }} className="w-full text-sm text-muted-foreground border rounded-lg px-3 py-2 hover:bg-accent">{t('playground.cancel') || '取消'}</button>
                  </div>
                </div>
              )}
            </div>
          </div>
          <PlaygroundEntityPanel isImageMode={isImageMode} isLoading={isLoading} entities={entities} visibleBoxes={visibleBoxes} selectedCount={selectedCount} replacementMode={recognition.replacementMode} setReplacementMode={recognition.setReplacementMode} clearPlaygroundTextPresetTracking={recognition.clearPlaygroundTextPresetTracking} onRerunNer={handleRerunNer} onRedact={handleRedact} onSelectAll={selectAll} onDeselectAll={deselectAll} onToggleBox={toggleBox} onEntityClick={handleEntityClick} onRemoveEntity={removeEntity} />
        </div>
      )}

      {stage === 'result' && (
        <PlaygroundResult fileInfo={fileInfo} content={content} entities={entities} entityMap={entityMap} redactedCount={redactedCount} redactionReport={redactionReport} reportOpen={reportOpen} setReportOpen={setReportOpen} versionHistory={versionHistory} versionHistoryOpen={versionHistoryOpen} setVersionHistoryOpen={setVersionHistoryOpen} isImageMode={isImageMode} imageUrl={imageUrl} redactedImageUrl={redactedImageUrl} visibleBoxes={visibleBoxes} visionTypes={recognition.visionTypes} getVisionTypeConfig={recognition.getVisionTypeConfig} onBackToEdit={() => setStage('preview')} onReset={handleReset} onDownload={handleDownload} />
      )}

      {isLoading && <PlaygroundLoading loadingMessage={loadingMessage} isImageMode={isImageMode} elapsedSec={loadingElapsedSec} />}
    </div>
  );
};
