// Copyright 2026 DataInfra-RedactionEverything Contributors

import {
  type FC,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  useMemo,
  memo,
} from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import {
  ENTITY_GROUPS,
  getEntityGroupLabel,
  getEntityTypeName,
} from '@/config/entityTypes';
import { computeEntityStats, getModePreview } from '../utils';
import type { BoundingBox, Entity } from '../types';

export interface PlaygroundEntityPanelProps {
  isImageMode: boolean;
  isLoading: boolean;
  recognitionIssue?: string | null;
  entities: Entity[];
  entityTypes?: Array<{ id: string; name: string }>;
  visionTypes?: Array<{ id: string; name: string }>;
  visibleBoxes: BoundingBox[];
  selectedCount: number;
  displaySelectedCount?: number;
  displayTotalCount?: number;
  displayStats?: Record<string, { total: number; selected: number }>;
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

export const PlaygroundEntityPanel: FC<PlaygroundEntityPanelProps> = memo(
  ({
    isImageMode,
    isLoading,
    recognitionIssue,
    entities,
    entityTypes = [],
    visionTypes = [],
    visibleBoxes,
    selectedCount,
    displaySelectedCount,
    displayTotalCount,
    displayStats,
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
    const t = useT();
    const stats = useMemo(
      () => (!isImageMode && displayStats ? displayStats : computeEntityStats(entities)),
      [displayStats, entities, isImageMode],
    );
    const shownSelectedCount = isImageMode ? selectedCount : (displaySelectedCount ?? selectedCount);
    const totalCount = isImageMode ? visibleBoxes.length : (displayTotalCount ?? entities.length);
    const listTitle = isImageMode ? t('playground.regionList') : t('playground.results');
    const typeNameById = useMemo(() => {
      // 文本目录 + 图像管线目录都进映射：图像区域的 box.type 可能是
      // custom_ocr_has_* 这类只存在于管线目录里的自定义项 id。
      const map = new Map<string, string>();
      for (const type of entityTypes) map.set(type.id, type.name);
      for (const type of visionTypes) {
        if (!map.has(type.id)) map.set(type.id, type.name);
      }
      return map;
    }, [entityTypes, visionTypes]);
    const disabledReason =
      recognitionIssue && totalCount === 0
        ? recognitionIssue
        : totalCount === 0
          ? t('playground.redactDisabledNoResults')
          : shownSelectedCount === 0
            ? t('playground.redactDisabledNoSelection')
            : '';

    return (
      <div
        className="flex min-h-0 w-full flex-shrink-0 flex-col gap-2.5 self-stretch overflow-x-hidden overflow-y-auto"
        data-testid="playground-entity-panel"
      >
        <Card className="overflow-hidden">
          <CardContent className="flex flex-col gap-2.5 p-3.5">
            <div className="space-y-0.5">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t('playground.recognitionSection')}
              </div>
              <p className="line-clamp-2 text-sm leading-5 text-foreground">
                {t('playground.recognitionSectionDesc')}
              </p>
            </div>
            <Button
              onClick={onRerunNer}
              disabled={isLoading}
              className="h-9 w-full whitespace-nowrap"
              data-testid="playground-rerun-btn"
            >
              {isLoading ? t('playground.recognizing') : t('playground.reRecognize')}
            </Button>
            <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">
              {t('playground.rerunHint')}
            </p>
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader className="p-3.5 pb-2.5">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <CardTitle className="truncate text-sm">
                  {t('playground.reviewSelection')}
                </CardTitle>
                <p className="mt-1 truncate text-xs text-muted-foreground">
                  {t('playground.selectionSummary')
                    .replace('{selected}', String(shownSelectedCount))
                    .replace('{total}', String(totalCount))}
                </p>
              </div>
              <Badge variant="outline" className="shrink-0 rounded-full px-2.5 py-1">
                {shownSelectedCount}/{totalCount}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-2.5 p-3.5 pt-0">
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                className="min-w-0 flex-1 whitespace-nowrap px-2"
                onClick={onSelectAll}
                disabled={totalCount === 0}
                data-testid="playground-select-all"
              >
                {t('playground.selectAll')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="min-w-0 flex-1 whitespace-nowrap px-2"
                onClick={onDeselectAll}
                disabled={totalCount === 0}
                data-testid="playground-deselect-all"
              >
                {t('playground.deselectAll')}
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
              <div className="max-h-32 space-y-2 overflow-y-auto pr-1">
                {ENTITY_GROUPS.map((group) => {
                  const groupedStats = Object.entries(stats).filter(([typeId]) =>
                    group.types.some((groupType) => groupType.id === typeId),
                  );
                  if (groupedStats.length === 0) return null;

                  const total = groupedStats.reduce((sum, [, count]) => sum + count.total, 0);
                  const selected = groupedStats.reduce((sum, [, count]) => sum + count.selected, 0);

                  return (
                    <div key={group.id} className="rounded-[20px] border border-border/70 bg-muted/25">
                      <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
                        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          {getEntityGroupLabel(group.id)}
                        </span>
                        <span className="text-[11px] tabular-nums text-muted-foreground">
                          {selected}/{total}
                        </span>
                      </div>
                      <div className="space-y-1 px-3 py-2">
                        {groupedStats.map(([typeId, count]) => (
                          <div key={typeId} className="flex items-center justify-between text-xs">
                            <span className="text-muted-foreground">
                              {getEntityTypeName(typeId)}
                            </span>
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
          <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border/60 bg-muted/30 px-3.5">
            <div className="min-w-0">
              <span className="block truncate text-sm font-semibold text-foreground">
                {listTitle}
              </span>
              <p className="truncate text-xs text-muted-foreground">
                {t('playground.clickToEdit')}
              </p>
            </div>
            <Badge variant="secondary" className="shrink-0 rounded-full px-2.5 py-1">
              {totalCount}
            </Badge>
          </div>
          <ScrollArea className="flex-1">
            {isImageMode ? (
              <BoxList boxes={visibleBoxes} onToggle={onToggleBox} typeNameById={typeNameById} />
            ) : (
              <EntityList
                entities={entities}
                typeNameById={typeNameById}
                onClick={onEntityClick}
                onRemove={onRemoveEntity}
              />
            )}
          </ScrollArea>
        </Card>

        {disabledReason && !isLoading && (
          <RedactionBlockedNotice
            totalCount={totalCount}
            reason={disabledReason}
            onRerunNer={onRerunNer}
            onSelectAll={onSelectAll}
          />
        )}
        <Button
          onClick={onRedact}
          disabled={shownSelectedCount === 0 || isLoading}
          aria-describedby={disabledReason ? 'playground-redact-disabled-reason' : undefined}
          className={cn(
            'h-11 shrink-0 rounded-[20px] text-sm font-semibold shadow-[var(--shadow-control)]',
            shownSelectedCount === 0 && 'opacity-50',
          )}
          data-testid="playground-redact-btn"
        >
          {isLoading
            ? t('playground.processing')
            : `${t('playground.startRedact')} (${shownSelectedCount})`}
        </Button>
      </div>
    );
  },
);

const ReplacementModeSelector: FC<{
  entities: Entity[];
  mode: 'structured' | 'smart' | 'mask';
  onModeChange: (mode: 'structured' | 'smart' | 'mask') => void;
}> = ({ entities, mode, onModeChange }) => {
  const t = useT();
  const sampleEntity = entities.find((entity) => entity.text && entity.text.length > 0);
  const modes: { value: 'structured' | 'smart' | 'mask'; label: string; badge?: string }[] = [
    { value: 'structured', label: t('mode.structured'), badge: t('playground.recommended') },
    { value: 'smart', label: t('mode.smart') },
    { value: 'mask', label: t('mode.mask') },
  ];

  return (
    <div className="space-y-2">
      <label className="block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t('playground.redactMode')}
      </label>
      <div className="grid grid-cols-3 gap-1.5">
        {modes.map((item) => (
          <label
            key={item.value}
            className={cn(
              'flex min-w-0 cursor-pointer items-center justify-center gap-1.5 rounded-xl border px-2 py-2 text-center transition-colors',
              mode === item.value
                ? 'border-primary/50 bg-primary/5'
                : 'border-border/70 bg-background hover:border-primary/30',
            )}
          >
            <div className="flex items-center gap-2">
              <input
                type="radio"
                name="replacementMode"
                value={item.value}
                checked={mode === item.value}
                onChange={() => onModeChange(item.value)}
                className="sr-only"
              />
              <span className="truncate text-xs font-medium text-foreground">{item.label}</span>
              {item.badge && (
                <Badge
                  variant="outline"
                  className="hidden shrink-0 rounded-full px-1.5 py-0 xl:inline-flex"
                >
                  {item.badge}
                </Badge>
              )}
            </div>
          </label>
        ))}
      </div>
      <p className="truncate text-[11px] text-muted-foreground">
        {getModePreview(mode, sampleEntity)}
      </p>
    </div>
  );
};

const RedactionBlockedNotice: FC<{
  totalCount: number;
  reason: string;
  onRerunNer: () => void;
  onSelectAll: () => void;
}> = ({ totalCount, reason, onRerunNer, onSelectAll }) => {
  const t = useT();
  const isEmpty = totalCount === 0;

  return (
    <div
      id="playground-redact-disabled-reason"
      className="flex shrink-0 items-center justify-between gap-2 rounded-xl border border-border/70 bg-muted/35 px-3 py-2 text-xs leading-5 text-muted-foreground"
      data-testid="playground-redact-disabled-reason"
    >
      <p className="min-w-0 truncate">{reason}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-8 shrink-0 whitespace-nowrap px-3 text-xs"
        onClick={isEmpty ? onRerunNer : onSelectAll}
        data-testid={isEmpty ? 'playground-disabled-rerun' : 'playground-disabled-select-all'}
      >
        {isEmpty ? t('playground.reRecognize') : t('playground.selectAll')}
      </Button>
    </div>
  );
};

const BoxList: FC<{
  boxes: BoundingBox[];
  onToggle: (id: string) => void;
  typeNameById: Map<string, string>;
}> = ({ boxes, onToggle, typeNameById }) => {
  const t = useT();

  if (boxes.length === 0) {
    return <EmptyDetectionState mode="image" />;
  }

  return (
    <>
      {boxes.map((box) => {
        const sourceLabel =
          box.source === 'ocr_has'
            ? t('playground.sourceOcr')
            : box.source === 'visual_features'
              ? t('playground.sourceImage')
              : t('playground.sourceManual');

        return (
          <div
            key={box.id}
            role="button"
            tabIndex={0}
            className="flex cursor-pointer items-center gap-3 border-b border-border/50 px-3 py-3 transition-colors hover:bg-accent/40"
            onClick={() => onToggle(box.id)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' && event.key !== ' ') return;
              event.preventDefault();
              onToggle(box.id);
            }}
            data-testid={`playground-box-${box.id}`}
          >
            <Checkbox
              checked={box.selected}
              onCheckedChange={() => onToggle(box.id)}
              className="h-4 w-4"
            />
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-1.5">
                <Badge variant="secondary">
                  {typeNameById.get(box.type) ?? getEntityTypeName(box.type)}
                </Badge>
                <Badge variant="outline">
                  {sourceLabel}
                </Badge>
              </div>
              <p className="truncate text-sm text-foreground">
                {box.text || t('playground.imageRegion')}
              </p>
            </div>
          </div>
        );
      })}
    </>
  );
};

const EntityRow: FC<{
  entity: Entity;
  typeNameById: Map<string, string>;
  onClick: (entity: Entity, event: ReactMouseEvent) => void;
  onRemove: (id: string) => void;
}> = ({ entity, typeNameById, onClick, onRemove }) => {
  const t = useT();
  const sourceLabel =
    entity.source === 'regex'
      ? t('playground.sourceRegex')
      : entity.source === 'manual'
        ? t('playground.sourceManual')
        : t('playground.sourceAi');

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    // The click handler only reads SyntheticEvent members (stopPropagation),
    // so forwarding the keyboard event is safe.
    onClick(entity, event as unknown as ReactMouseEvent);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      className="flex cursor-pointer items-center gap-2 border-b border-border/40 px-3 py-3 transition-colors hover:bg-accent/40"
      onClick={(event) => onClick(entity, event)}
      onKeyDown={handleKeyDown}
      data-testid={`playground-entity-${entity.id}`}
    >
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary">
            {typeNameById.get(entity.type) ?? getEntityTypeName(entity.type)}
          </Badge>
          <Badge variant="outline">{sourceLabel}</Badge>
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
        aria-label={t('playground.removeAnnotation')}
      >
        <svg
          className="h-3.5 w-3.5"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M6 18L18 6M6 6l12 12"
          />
        </svg>
      </Button>
    </div>
  );
};

const EntityList: FC<{
  entities: Entity[];
  typeNameById: Map<string, string>;
  onClick: (entity: Entity, event: ReactMouseEvent) => void;
  onRemove: (id: string) => void;
}> = ({ entities, typeNameById, onClick, onRemove }) => {
  const t = useT();

  if (entities.length === 0) {
    return <EmptyDetectionState mode="text" />;
  }

  const groupedTypeIds = new Set(ENTITY_GROUPS.flatMap((group) => group.types.map((type) => type.id)));
  const customEntities = entities.filter((entity) => !groupedTypeIds.has(entity.type));

  return (
    <>
      {ENTITY_GROUPS.map((group) => {
        const groupedEntities = entities.filter((entity) =>
          group.types.some((groupType) => groupType.id === entity.type),
        );
        if (groupedEntities.length === 0) return null;

        return (
          <div key={group.id}>
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border/60 bg-background/95 px-3 py-2 backdrop-blur">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {getEntityGroupLabel(group.id)}
              </span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {groupedEntities.length}
              </span>
            </div>

            {groupedEntities.map((entity) => (
              <EntityRow
                key={entity.id}
                entity={entity}
                typeNameById={typeNameById}
                onClick={onClick}
                onRemove={onRemove}
              />
            ))}
          </div>
        );
      })}
      {customEntities.length > 0 && (
        <div key="custom">
          <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border/60 bg-background/95 px-3 py-2 backdrop-blur">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t('entityGroup.other')}
            </span>
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {customEntities.length}
            </span>
          </div>

          {customEntities.map((entity) => (
            <EntityRow
              key={entity.id}
              entity={entity}
              typeNameById={typeNameById}
              onClick={onClick}
              onRemove={onRemove}
            />
          ))}
        </div>
      )}
    </>
  );
};

const EmptyDetectionState: FC<{ mode: 'text' | 'image' }> = ({ mode }) => {
  const t = useT();
  return (
    <div className="space-y-2 p-6 text-center" data-testid="playground-empty-detections">
      <p className="text-sm font-medium text-foreground">{t('playground.noResultsTitle')}</p>
      <p className="mx-auto max-w-[240px] text-xs leading-5 text-muted-foreground">
        {mode === 'image' ? t('playground.noResultsDescImage') : t('playground.noResultsDescText')}
      </p>
    </div>
  );
};
