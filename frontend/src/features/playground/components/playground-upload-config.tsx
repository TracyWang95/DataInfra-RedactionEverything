// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { type FC, useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { PaginationRail } from '@/components/PaginationRail';
import { getEntityTypeName } from '@/config/entityTypes';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { getSelectionToneClasses, type SelectionTone } from '@/ui/selectionPalette';
import { localizeRecognitionTypeName } from '@/features/settings/lib/redaction-display';
import type { usePlayground } from '../hooks/use-playground';
import type { PipelineConfig, VisionTypeConfig } from '../types';

type RecognitionCtx = ReturnType<typeof usePlayground>['recognition'];
const CONFIG_TILE_PAGE_SIZE = 8;
const VISION_PIPELINE_PAGE_SIZE = 4;
const TEXT_SEMANTIC_PAGE_SIZE = 24;
const TEXT_REGEX_PAGE_SIZE = 4;
const CONFIG_TILE_GRID_CLASS =
  'grid min-h-0 flex-1 auto-rows-fr grid-cols-2 gap-1.5 p-2 sm:grid-cols-3 xl:grid-cols-4';
const TEXT_REGEX_TILE_GRID_CLASS =
  'grid shrink-0 auto-rows-[2.42rem] grid-cols-2 gap-1.5 p-2 sm:grid-cols-3 xl:grid-cols-4';
const TEXT_SEMANTIC_TILE_GRID_CLASS =
  'grid shrink-0 auto-rows-[2.42rem] grid-cols-2 gap-1.5 p-2 sm:grid-cols-3 xl:grid-cols-4';
const VISION_TILE_GRID_CLASS =
  'grid min-h-0 flex-1 auto-rows-[minmax(1.75rem,1fr)] grid-cols-2 gap-1.5 p-2 sm:grid-cols-3 xl:grid-cols-4';
const CONFIG_BUBBLE_CLASS =
  'flex min-h-[2.42rem] min-w-0 cursor-pointer items-center gap-1.5 self-stretch overflow-hidden rounded-xl border px-2.5 py-1.5 text-[11px] leading-4 transition-colors';

export function resolveTextTypeName(
  typeId: string,
  fallbackName: string | undefined,
  t: (key: string) => string,
) {
  return localizeRecognitionTypeName({ id: typeId, name: fallbackName }, t) || getEntityTypeName(typeId);
}

export function ConfigEmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div
      className="rounded-[22px] border border-dashed border-border/70 bg-muted/20 px-5 py-8 text-center"
      data-testid="playground-config-empty"
    >
      <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">{title}</p>
      <p className="mt-2 text-xs leading-6 text-muted-foreground">{description}</p>
    </div>
  );
}

function ConfigLoadingState({
  title,
  itemCount = CONFIG_TILE_PAGE_SIZE,
}: {
  title: string;
  itemCount?: number;
}) {
  const items = Array.from({ length: itemCount }, (_, idx) => idx + 1);

  return (
    <section className="flex min-h-0 flex-1 basis-0 flex-col overflow-hidden rounded-[18px] border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]">
      <div className="flex shrink-0 items-center justify-between border-b px-3 py-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <Skeleton className="size-2.5 rounded-full" />
          <span className="sr-only">{title}</span>
          <Skeleton className="h-4 w-36 rounded-md" />
        </div>
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>
      <div className={CONFIG_TILE_GRID_CLASS}>
        {items.map((item) => (
          <div
            key={item}
            className="flex min-w-0 items-center gap-1.5 rounded-xl border border-border/70 px-2.5 py-1.5"
          >
            <Skeleton className="h-3.5 w-3.5 rounded-sm" />
            <Skeleton className="h-4 grow rounded-md" />
          </div>
        ))}
      </div>
    </section>
  );
}

function ConfigGroupEmptyState({ label, compact = false }: { label: string; compact?: boolean }) {
  return (
    <div
      className={cn(
        'flex flex-1 items-center justify-center rounded-xl border border-dashed border-border/70 bg-background/75 px-3 text-center text-xs leading-5 text-muted-foreground',
        compact ? 'min-h-[2.1rem] text-[11px] leading-4 [&_span]:truncate' : 'min-h-[5.75rem]',
      )}
    >
      <span className="min-w-0">{label}</span>
    </div>
  );
}

export const TextTypeGroups: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();
  const [groupPages, setGroupPages] = useState<Record<string, number>>({});

  // Reset pagination when groups change or preset is applied
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clamping page indices when group data changes
    setGroupPages((current) => {
      const next = { ...current };
      rec.playgroundTextGroups.forEach((group) => {
        const pageSize = group.key === 'regex' ? TEXT_REGEX_PAGE_SIZE : TEXT_SEMANTIC_PAGE_SIZE;
        const totalPages = Math.max(1, Math.ceil(group.types.length / pageSize));
        next[group.key] = Math.min(next[group.key] ?? 1, totalPages);
      });
      return next;
    });
  }, [rec.playgroundTextGroups]);

  // Jump to page 1 when preset selection changes so user sees the updated checkboxes
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting pagination on preset change
    setGroupPages({});
  }, [rec.playgroundPresetTextId]);

  if (rec.textConfigState === 'loading') {
    return (
      <div
        className="flex min-h-0 flex-1 flex-col gap-2"
        data-testid="playground-text-config-loading"
        aria-label={t('playground.loading')}
      >
        <ConfigLoadingState title={t('playground.loading')} />
      </div>
    );
  }

  if (rec.textConfigState === 'unavailable') {
    return (
      <ConfigEmptyState
        title={t('playground.textConfigUnavailableTitle')}
        description={t('playground.textConfigUnavailableDesc')}
      />
    );
  }

  if (rec.textConfigState === 'empty' || rec.playgroundTextGroups.length === 0) {
    return (
      <ConfigEmptyState
        title={t('playground.textConfigEmptyTitle')}
        description={t('playground.textConfigEmptyDesc')}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {rec.playgroundTextGroups.map((group) => {
        const isRegexGroup = group.key === 'regex';
        const pageSize = isRegexGroup ? TEXT_REGEX_PAGE_SIZE : TEXT_SEMANTIC_PAGE_SIZE;
        const ids = group.types.map((type) => type.id);
        const allOn = ids.length > 0 && ids.every((id) => rec.selectedTypes.includes(id));
        const toneClasses = getSelectionToneClasses(group.tone);
        const totalPages = Math.max(1, Math.ceil(group.types.length / pageSize));
        const page = groupPages[group.key] ?? 1;
        const visibleTypes = group.types.slice((page - 1) * pageSize, page * pageSize);

        return (
          <section
            key={group.key}
            className={cn(
              'flex min-h-0 flex-col overflow-hidden rounded-[18px] border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]',
              'shrink-0 basis-auto',
            )}
            data-testid={`playground-text-group-${group.key}`}
          >
            <div
              className={cn(
                'flex shrink-0 items-center justify-between gap-2 border-b px-3 py-1.5',
                toneClasses.headerSurface,
              )}
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn('size-2 rounded-full', toneClasses.dot)} />
                <span
                  className={cn(
                    'truncate text-xs font-semibold tracking-[0.02em]',
                    toneClasses.titleText,
                  )}
                >
                  {group.label}
                </span>
                <Badge
                  variant="secondary"
                  className={cn(
                    'rounded-full border bg-background/85 px-2 py-0.5 text-[10px] shadow-none',
                    toneClasses.badgeText,
                  )}
                >
                  {group.types.length}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 shrink-0 whitespace-nowrap rounded-full px-2 text-[10px]"
                disabled={ids.length === 0}
                onClick={() => rec.setPlaygroundTextTypeGroupSelection(ids, !allOn)}
              >
                {allOn ? t('playground.clear') : t('playground.selectAll')}
              </Button>
            </div>
            {group.types.length === 0 ? (
              <div className={cn('flex min-h-0 flex-1', isRegexGroup ? 'p-1' : 'p-2')}>
                <ConfigGroupEmptyState
                  label={t('playground.customFallbackEmpty')}
                  compact={isRegexGroup}
                />
              </div>
            ) : (
              <div
                className={
                  isRegexGroup ? TEXT_REGEX_TILE_GRID_CLASS : TEXT_SEMANTIC_TILE_GRID_CLASS
                }
              >
                {visibleTypes.map((type) => {
                  const checked = rec.selectedTypes.includes(type.id);
                  const typeName = resolveTextTypeName(type.id, type.name, t);
                  return (
                    <label
                      key={`${group.key}-${type.id}`}
                      className={cn(
                        CONFIG_BUBBLE_CLASS,
                        checked
                          ? toneClasses.cardSelectedCompact
                          : 'border-border/70 bg-background hover:border-border hover:bg-accent/35',
                      )}
                      title={type.description || typeName}
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={() => {
                          rec.clearPlaygroundTextPresetTracking();
                          rec.setSelectedTypes((previous: string[]) =>
                            checked
                              ? previous.filter((id) => id !== type.id)
                              : [...previous, type.id],
                          );
                        }}
                        className="h-3.5 w-3.5"
                      />
                      <span className="min-w-0 truncate font-medium">{typeName}</span>
                    </label>
                  );
                })}
              </div>
            )}
            {group.types.length > 0 && (
              <div className="mt-auto shrink-0 border-t border-border/70 px-1.5 py-1.5">
                <PaginationRail
                  page={page}
                  pageSize={pageSize}
                  totalItems={group.types.length}
                  totalPages={totalPages}
                  compact
                  onPageChange={(nextPage) => {
                    setGroupPages((current) => ({
                      ...current,
                      [group.key]: nextPage,
                    }));
                  }}
                />
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
};

export const VisionPipelines: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();
  const [pipelinePages, setPipelinePages] = useState<Record<string, number>>({});
  const pageSize = VISION_PIPELINE_PAGE_SIZE;
  const displayPipelines = useMemo(() => {
    const ocrPipeline = rec.pipelines.find((pipeline) => pipeline.mode === 'ocr_has');
    const visualPipeline = rec.pipelines.find((pipeline) => pipeline.mode === 'visual_features');
    const visualTypes: VisionTypeConfig[] = (visualPipeline?.types ?? []).map((type) => ({
      ...type,
      pipelineMode: 'visual_features',
    }));
    const mergedPipelines: PipelineConfig[] = [];

    if (ocrPipeline) {
      mergedPipelines.push({
        ...ocrPipeline,
        types: ocrPipeline.types.map((type) => ({ ...type, pipelineMode: 'ocr_has' })),
      });
    }

    if (visualPipeline) {
      mergedPipelines.push({
        mode: 'visual_features',
        name: t('settings.pipelineDisplayName.image'),
        description: t('settings.pipelineDescription.image'),
        enabled: visualPipeline.enabled,
        types: visualTypes,
      });
    }

    return mergedPipelines;
  }, [rec.pipelines, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clamping page indices when pipeline data changes
    setPipelinePages((current) => {
      const next = { ...current };
      displayPipelines.forEach((pipeline) => {
        const totalPages = Math.max(1, Math.ceil(pipeline.types.length / pageSize));
        next[pipeline.mode] = Math.min(next[pipeline.mode] ?? 1, totalPages);
      });
      return next;
    });
  }, [displayPipelines, pageSize]);

  if (rec.visionConfigState === 'loading') {
    return (
      <div
        className="flex min-h-0 flex-1 flex-col gap-2"
        data-testid="playground-vision-config-loading"
        aria-label={t('playground.loading')}
      >
        <ConfigLoadingState title={t('playground.loading')} />
      </div>
    );
  }

  if (rec.visionConfigState === 'unavailable') {
    return (
      <ConfigEmptyState
        title={t('playground.visionConfigUnavailableTitle')}
        description={t('playground.visionConfigUnavailableDesc')}
      />
    );
  }

  if (rec.visionConfigState === 'empty' || displayPipelines.length === 0) {
    return (
      <ConfigEmptyState
        title={t('playground.visionConfigEmptyTitle')}
        description={t('playground.visionConfigEmptyDesc')}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {displayPipelines.map((pipeline) => {
        const isVisualFeatures = pipeline.mode === 'visual_features';
        const pipelineTypes = pipeline.types;
        const selectedSet = isVisualFeatures
          ? rec.selectedVisualFeatureTypes
          : rec.selectedOcrHasTypes;
        const recommendedIds = pipelineTypes.map((type) => type.id);
        const allSelected =
          recommendedIds.length > 0 && recommendedIds.every((id) => selectedSet.includes(id));
        const tone: SelectionTone = isVisualFeatures ? 'visual' : 'semantic';
        const toneClasses = getSelectionToneClasses(tone);
        const totalPages = Math.max(1, Math.ceil(pipelineTypes.length / pageSize));
        const page = pipelinePages[pipeline.mode] ?? 1;
        const visibleTypes = pipelineTypes.slice((page - 1) * pageSize, page * pageSize);

        return (
          <section
            key={pipeline.mode}
            className="flex min-h-0 flex-1 basis-0 flex-col overflow-hidden rounded-[18px] border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]"
            data-testid={`playground-pipeline-${pipeline.mode}`}
          >
            <div
              className={cn(
                'flex shrink-0 items-center justify-between gap-2 border-b px-3 py-1.5',
                toneClasses.headerSurface,
              )}
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn('size-2 rounded-full', toneClasses.dot)} />
                <span
                  className={cn(
                    'truncate text-xs font-semibold tracking-[0.02em]',
                    toneClasses.titleText,
                  )}
                >
                  {isVisualFeatures ? t('playground.visualRegionRange') : t('playground.imageTextRange')}
                </span>
                <Badge
                  variant="secondary"
                  className={cn(
                    'rounded-full border bg-background/85 px-2 py-0.5 text-[10px] shadow-none',
                    toneClasses.badgeText,
                  )}
                >
                  {pipelineTypes.length}
                </Badge>
                <Badge
                  variant="secondary"
                  className="rounded-full border border-border/70 bg-background/70 px-2 py-0.5 text-[10px] font-medium text-muted-foreground shadow-none"
                >
                  {isVisualFeatures ? t('playground.visualFeatureShort') : t('playground.ocrShort')}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 shrink-0 whitespace-nowrap rounded-full px-2 text-[10px]"
                disabled={recommendedIds.length === 0}
                onClick={() => {
                  rec.clearPlaygroundVisionPresetTracking();
                  if (allSelected) {
                    if (isVisualFeatures) {
                      rec.updateVisualFeatureTypes([]);
                    } else {
                      rec.updateOcrHasTypes([]);
                    }
                  } else {
                    if (isVisualFeatures) {
                      rec.updateVisualFeatureTypes(recommendedIds);
                    } else {
                      rec.updateOcrHasTypes(recommendedIds);
                    }
                  }
                }}
              >
                {allSelected
                  ? t('playground.clear')
                  : isVisualFeatures
                    ? t('playground.selectRecommended')
                    : t('playground.selectAll')}
              </Button>
            </div>
            {pipelineTypes.length === 0 ? (
              <div className="flex min-h-0 flex-1 p-2">
                <ConfigGroupEmptyState label={t('playground.visionPipelineEmpty')} />
              </div>
            ) : (
              <div className={VISION_TILE_GRID_CLASS}>
                {visibleTypes.map((type) => {
                  const typeMode = type.pipelineMode ?? pipeline.mode;
                  const checked =
                    typeMode === 'visual_features'
                      ? rec.selectedVisualFeatureTypes.includes(type.id)
                      : rec.selectedOcrHasTypes.includes(type.id);
                  return (
                    <label
                      key={`${typeMode}-${type.id}`}
                      className={cn(
                        CONFIG_BUBBLE_CLASS,
                        checked
                          ? toneClasses.cardSelectedCompact
                          : 'border-border/70 bg-background hover:border-border hover:bg-accent/35',
                      )}
                      title={type.description || type.name}
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={() =>
                          rec.toggleVisionType(type.id, typeMode)
                        }
                        aria-label={
                          localizeRecognitionTypeName(type, t)
                        }
                        className="h-3.5 w-3.5"
                      />
                      <span className="min-w-0 truncate font-medium">
                        {localizeRecognitionTypeName(type, t)}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
            {pipelineTypes.length > 0 && (
              <div className="mt-auto shrink-0 border-t border-border/70 px-1.5 py-1.5">
                <PaginationRail
                  page={page}
                  pageSize={pageSize}
                  totalItems={pipelineTypes.length}
                  totalPages={totalPages}
                  compact
                  onPageChange={(nextPage) => {
                    setPipelinePages((current) => ({
                      ...current,
                      [pipeline.mode]: nextPage,
                    }));
                  }}
                />
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
};
