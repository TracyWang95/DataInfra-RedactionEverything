/**
 * Playground entity panel: entity list, selection controls, and redact action.
 */
import { type FC, type MouseEvent as ReactMouseEvent, useMemo } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { t } from '@/i18n';
import { cn } from '@/lib/utils';
import { ENTITY_GROUPS, getEntityGroup, getEntityTypeName } from '@/config/entityTypes';
import { computeEntityStats, getModePreview } from '../utils';
import type { BoundingBox, Entity } from '../types';

export interface PlaygroundEntityPanelProps {
  isImageMode: boolean;
  isLoading: boolean;
  entities: Entity[];
  visibleBoxes: BoundingBox[];
  selectedCount: number;
  replacementMode: 'structured' | 'smart' | 'mask';
  setReplacementMode: (mode: 'structured' | 'smart' | 'mask') => void;
  clearPlaygroundTextPresetTracking: () => void;
  onRerunNer: () => void;
  onRedact: () => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onToggleBox: (id: string) => void;
  onEntityClick: (entity: Entity, event: ReactMouseEvent) => void;
  onRemoveEntity: (id: string) => void;
}

export const PlaygroundEntityPanel: FC<PlaygroundEntityPanelProps> = ({
  isImageMode,
  isLoading,
  entities,
  visibleBoxes,
  selectedCount,
  replacementMode,
  setReplacementMode,
  clearPlaygroundTextPresetTracking,
  onRerunNer,
  onRedact,
  onSelectAll,
  onDeselectAll,
  onToggleBox,
  onEntityClick,
  onRemoveEntity,
}) => {
  const stats = useMemo(() => computeEntityStats(entities), [entities]);
  const totalCount = isImageMode ? visibleBoxes.length : entities.length;

  return (
    <div
      className="flex min-h-0 w-full flex-shrink-0 flex-col gap-3 self-stretch overflow-x-hidden overflow-y-auto pr-1 lg:w-[320px] lg:max-w-[340px]"
      data-testid="playground-entity-panel"
    >
      <Card className="overflow-hidden">
        <CardContent className="flex flex-col gap-3 p-4">
          <div className="space-y-1">
            <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              Recognition
            </div>
            <p className="text-sm text-foreground">
              Refresh detection after changing rules or recognition settings.
            </p>
          </div>
          <Button onClick={onRerunNer} disabled={isLoading} className="w-full" data-testid="playground-rerun-btn">
            {isLoading ? t('playground.recognizing') || 'Recognizing...' : t('playground.reRecognize') || 'Run Recognition Again'}
          </Button>
          <p className="text-xs leading-6 text-muted-foreground">
            {t('playground.rerunHint') || 'Recognition updates the current file only. Use settings or upload options to change the wider recognition profile.'}
          </p>
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader className="p-4 pb-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="text-sm">{isImageMode ? 'Regions' : t('playground.results') || 'Detection Results'}</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {selectedCount} selected out of {totalCount}
              </p>
            </div>
            <Badge variant="outline" className="rounded-full px-2.5 py-1 text-[11px]">
              {selectedCount}/{totalCount}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 p-4 pt-0">
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" className="flex-1" onClick={onSelectAll} data-testid="playground-select-all">
              {t('playground.selectAll') || 'Select All'}
            </Button>
            <Button variant="outline" size="sm" className="flex-1" onClick={onDeselectAll} data-testid="playground-deselect-all">
              {t('playground.deselectAll') || 'Deselect All'}
            </Button>
          </div>

          {!isImageMode && (
            <ReplacementModeSelector
              entities={entities}
              mode={replacementMode}
              onModeChange={(mode) => {
                clearPlaygroundTextPresetTracking();
                setReplacementMode(mode);
              }}
            />
          )}

          {!isImageMode && Object.keys(stats).length > 0 && (
            <div className="space-y-2">
              {ENTITY_GROUPS.map((group) => {
                const groupedStats = Object.entries(stats).filter(([typeId]) =>
                  group.types.some((groupType) => groupType.id === typeId),
                );
                if (groupedStats.length === 0) return null;

                const total = groupedStats.reduce((sum, [, count]) => sum + count.total, 0);
                const selected = groupedStats.reduce((sum, [, count]) => sum + count.selected, 0);

                return (
                  <div key={group.id} className="rounded-2xl border border-border/70 bg-muted/25">
                    <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
                      <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        {group.label}
                      </span>
                      <span className="text-[11px] tabular-nums text-muted-foreground">
                        {selected}/{total}
                      </span>
                    </div>
                    <div className="space-y-1 px-3 py-2">
                      {groupedStats.map(([typeId, count]) => (
                        <div key={typeId} className="flex items-center justify-between text-xs">
                          <span className="text-muted-foreground">{getEntityTypeName(typeId)}</span>
                          <span className="tabular-nums text-foreground">
                            {count.selected}/{count.total}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-border/60 bg-muted/30 px-4 py-3">
          <div>
            <span className="text-sm font-semibold text-foreground">
              {isImageMode ? t('playground.regionList') || 'Regions' : t('playground.results') || 'Detection Results'}
            </span>
            <p className="mt-1 text-xs text-muted-foreground">
              {t('playground.clickToEdit') || 'Select any item to refine, remove, or review before export.'}
            </p>
          </div>
          <Badge variant="secondary" className="rounded-full px-2.5 py-1 text-[11px]">
            {totalCount}
          </Badge>
        </div>
        <ScrollArea className="flex-1">
          {isImageMode ? (
            <BoxList boxes={visibleBoxes} onToggle={onToggleBox} />
          ) : (
            <EntityList entities={entities} onClick={onEntityClick} onRemove={onRemoveEntity} />
          )}
        </ScrollArea>
      </Card>

      <Button
        onClick={onRedact}
        disabled={selectedCount === 0 || isLoading}
        className={cn('h-12 rounded-2xl text-sm font-semibold shadow-[0_22px_44px_-28px_rgba(15,23,42,0.45)]', selectedCount === 0 && 'opacity-50')}
        data-testid="playground-redact-btn"
      >
        {isLoading ? t('playground.processing') || 'Processing...' : `${t('playground.startRedact') || 'Start Redaction'} (${selectedCount})`}
      </Button>
    </div>
  );
};

const ReplacementModeSelector: FC<{
  entities: Entity[];
  mode: 'structured' | 'smart' | 'mask';
  onModeChange: (mode: 'structured' | 'smart' | 'mask') => void;
}> = ({ entities, mode, onModeChange }) => {
  const sampleEntity = entities.find((entity) => entity.text && entity.text.length > 0);
  const modes: { value: 'structured' | 'smart' | 'mask'; label: string; badge?: string }[] = [
    { value: 'structured', label: 'Structured Tags', badge: 'Recommended' },
    { value: 'smart', label: 'Smart Replace' },
    { value: 'mask', label: 'Mask' },
  ];

  return (
    <div className="space-y-2">
      <label className="block text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
        {t('playground.redactMode') || 'Redaction Style'}
      </label>
      <div className="space-y-2">
        {modes.map((item) => (
          <label
            key={item.value}
            className={cn(
              'flex cursor-pointer flex-col rounded-2xl border px-3 py-3 transition-colors',
              mode === item.value ? 'border-primary/50 bg-primary/5' : 'border-border/70 bg-background hover:border-primary/30',
            )}
          >
            <div className="flex items-center gap-2">
              <input
                type="radio"
                name="replacementMode"
                value={item.value}
                checked={mode === item.value}
                onChange={() => onModeChange(item.value)}
                className="accent-primary"
              />
              <span className="text-sm font-medium text-foreground">{item.label}</span>
              {item.badge && <Badge variant="outline" className="rounded-full px-2 py-0.5 text-[10px]">{item.badge}</Badge>}
            </div>
            <span className="ml-6 mt-1 text-[11px] text-muted-foreground">
              {getModePreview(item.value, sampleEntity)}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
};

const BoxList: FC<{ boxes: BoundingBox[]; onToggle: (id: string) => void }> = ({ boxes, onToggle }) => {
  if (boxes.length === 0) {
    return <p className="p-6 text-center text-sm text-muted-foreground">{t('playground.noResults') || 'No detections yet.'}</p>;
  }

  return (
    <>
      {boxes.map((box) => {
        const group = getEntityGroup(box.type);
        const sourceLabel = box.source === 'ocr_has' ? 'OCR' : box.source === 'has_image' ? 'Image' : 'Manual';

        return (
          <div
            key={box.id}
            className="flex cursor-pointer items-center gap-3 border-b border-border/50 px-3 py-3 transition-colors hover:bg-accent/40"
            onClick={() => onToggle(box.id)}
            data-testid={`playground-box-${box.id}`}
          >
            <Checkbox checked={box.selected} onCheckedChange={() => onToggle(box.id)} className="h-4 w-4" />
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-1.5">
                <Badge variant="secondary" className="text-[10px]">{group?.label} / {getEntityTypeName(box.type)}</Badge>
                <Badge variant="outline" className="text-[10px]">{sourceLabel}</Badge>
              </div>
              <p className="truncate text-sm text-foreground">{box.text || 'Image region'}</p>
            </div>
          </div>
        );
      })}
    </>
  );
};

const EntityList: FC<{
  entities: Entity[];
  onClick: (entity: Entity, event: ReactMouseEvent) => void;
  onRemove: (id: string) => void;
}> = ({ entities, onClick, onRemove }) => {
  if (entities.length === 0) {
    return <p className="p-6 text-center text-sm text-muted-foreground">{t('playground.noResults') || 'No detections yet.'}</p>;
  }

  return (
    <>
      {ENTITY_GROUPS.map((group) => {
        const groupedEntities = entities.filter((entity) => group.types.some((groupType) => groupType.id === entity.type));
        if (groupedEntities.length === 0) return null;

        return (
          <div key={group.id}>
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border/60 bg-background/95 px-3 py-2 backdrop-blur">
              <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                {group.label}
              </span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {groupedEntities.length}
              </span>
            </div>

            {groupedEntities.map((entity) => {
              const sourceLabel = entity.source === 'regex' ? 'Regex' : entity.source === 'manual' ? 'Manual' : 'AI';

              return (
                <div
                  key={entity.id}
                  className="flex cursor-pointer items-center gap-2 border-b border-border/40 px-3 py-3 transition-colors hover:bg-accent/40"
                  onClick={(event) => onClick(entity, event)}
                  data-testid={`playground-entity-${entity.id}`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      <Badge variant="secondary" className="text-[10px]">{getEntityTypeName(entity.type)}</Badge>
                      <span className="text-[11px] text-muted-foreground">{sourceLabel}</span>
                    </div>
                    <p className="truncate text-sm text-foreground">{entity.text}</p>
                  </div>

                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0 rounded-xl text-muted-foreground hover:text-destructive"
                    onClick={(event) => {
                      event.stopPropagation();
                      onRemove(entity.id);
                    }}
                    aria-label={t('playground.removeAnnotation') || 'Remove annotation'}
                  >
                    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </Button>
                </div>
              );
            })}
          </div>
        );
      })}
    </>
  );
};
