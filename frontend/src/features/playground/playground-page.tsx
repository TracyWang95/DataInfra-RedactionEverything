// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { type FC, type ReactNode } from 'react';
import { useT } from '@/i18n';
import { getEntityTypeName } from '@/config/entityTypes';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import { PlaygroundUpload } from './components/playground-upload';
import { PlaygroundToolbar } from './components/playground-toolbar';
import { PlaygroundEntityPanel } from './components/playground-entity-panel';
import { PlaygroundResult } from './components/playground-result';
import { PlaygroundLoading } from './components/playground-loading';
import { PlaygroundTextSelectionPopover } from './components/playground-text-selection-popover';
import { PlaygroundEntityPopover } from './components/playground-entity-popover';
import { PlaygroundProvider, usePlaygroundContext, usePlaygroundUIContext } from './playground-context';
import { previewEntityHoverRingClass, previewEntityMarkStyle } from './utils';

/** Inner component that consumes the playground context. */
const PlaygroundInner: FC = () => {
  const t = useT();
  const ctx = usePlaygroundContext();
  const ui = usePlaygroundUIContext();

  const {
    stage, setStage, fileInfo, content, isImageMode,
    entities, setBoundingBoxes, visibleBoxes,
    isLoading, loadingMessage, loadingElapsedSec,
    entityMap, redactedCount, redactionReport, reportOpen, setReportOpen,
    versionHistory, versionHistoryOpen, setVersionHistoryOpen,
    selectedCount, canUndo, canRedo, handleUndo, handleRedo,
    selectAll, deselectAll, toggleBox, removeEntity,
    handleRerunNer, handleRedact, handleReset, handleDownload,
    imageUrl, redactedImageUrl, mergeVisibleBoxes, openPopout,
    recognition, imageHistory,
  } = ctx;

  const { entityTypes } = recognition;

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
        <mark
          key={entity.id}
          data-entity-id={entity.id}
          onClick={(event) => ui.handleEntityClick(entity, event)}
          style={previewEntityMarkStyle(entity)}
          className={`inline cursor-pointer rounded-sm px-0.5 py-[1px] transition-all hover:brightness-95 hover:ring-2 hover:ring-offset-1 hover:shadow-sm ${previewEntityHoverRingClass(entity.source)}`}
          title={`${typeName} [${sourceLabel}]`}
        >
          {content.slice(entity.start, entity.end)}
        </mark>,
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
        <div className="flex flex-1 min-h-0 min-w-0 flex-col gap-3 overflow-hidden p-3 sm:p-5 lg:flex-row">
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
              ref={ui.contentRef}
              onMouseUp={ui.handleTextSelect}
              onKeyUp={ui.handleTextSelect}
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
                <div ref={ui.textScrollRef} className="flex-1 min-h-0 overflow-auto">
                  <div className="p-4 font-[system-ui] text-sm leading-relaxed whitespace-pre-wrap">
                    {renderMarkedContent()}
                  </div>
                </div>
              )}

              {!isImageMode && <PlaygroundTextSelectionPopover entityTypes={entityTypes} />}
              {!isImageMode && <PlaygroundEntityPopover />}
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
            onEntityClick={ui.handleEntityClick}
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

/**
 * Playground page — wrapped in PlaygroundProvider so child components
 * can access the playground context directly without prop drilling.
 */
export const Playground: FC = () => (
  <PlaygroundProvider>
    <PlaygroundInner />
  </PlaygroundProvider>
);
