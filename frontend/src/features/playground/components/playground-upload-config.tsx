// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { type FC, useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { PaginationRail } from '@/components/PaginationRail';
import { getEntityTypeName } from '@/config/entityTypes';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { getSelectionToneClasses, type SelectionTone } from '@/ui/selectionPalette';
import type { usePlayground } from '../hooks/use-playground';

type RecognitionCtx = ReturnType<typeof usePlayground>['recognition'];

export function resolveTextTypeName(typeId: string, fallbackName?: string) {
  return fallbackName?.trim() || getEntityTypeName(typeId);
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

export const TextTypeGroups: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();
  const [groupPages, setGroupPages] = useState<Record<string, number>>({});
  const pageSize = 15;

  // Reset pagination when groups change or preset is applied
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clamping page indices when group data changes
    setGroupPages((current) => {
      const next = { ...current };
      rec.playgroundTextGroups.forEach((group) => {
        const totalPages = Math.max(1, Math.ceil(group.types.length / pageSize));
        next[group.key] = Math.min(next[group.key] ?? 1, totalPages);
      });
      return next;
    });
  }, [pageSize, rec.playgroundTextGroups]);

  // Jump to page 1 when preset selection changes so user sees the updated checkboxes
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting pagination on preset change
    setGroupPages({});
  }, [rec.playgroundPresetTextId]);

  if (rec.textConfigState === 'loading') {
    return <p className="py-10 text-center text-sm text-muted-foreground">{t('playground.loading')}</p>;
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
        const ids = group.types.map((type) => type.id);
        const allOn = ids.length > 0 && ids.every((id) => rec.selectedTypes.includes(id));
        const toneClasses = getSelectionToneClasses(group.tone);
        const totalPages = Math.max(1, Math.ceil(group.types.length / pageSize));
        const page = groupPages[group.key] ?? 1;
        const visibleTypes = group.types.slice((page - 1) * pageSize, page * pageSize);

        return (
          <section
            key={group.key}
            className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[20px] border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]"
            data-testid={`playground-text-group-${group.key}`}
          >
            <div className={cn('flex items-center justify-between gap-2 border-b px-3 py-2', toneClasses.headerSurface)}>
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn('size-2 rounded-full', toneClasses.dot)} />
                <span className={cn('truncate text-xs font-semibold tracking-[0.02em]', toneClasses.titleText)}>
                  {group.label}
                </span>
                <Badge
                  variant="secondary"
                  className={cn('rounded-full border bg-background/85 px-2 py-0.5 text-[10px] shadow-none', toneClasses.badgeText)}
                >
                  {group.types.length}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-6.5 rounded-full px-2 text-[10px]"
                onClick={() => rec.setPlaygroundTextTypeGroupSelection(ids, !allOn)}
              >
                {allOn ? t('playground.clear') : t('playground.selectAll')}
              </Button>
            </div>
            <div className="grid flex-1 grid-cols-3 grid-rows-5 content-start gap-1.5 p-2">
              {visibleTypes.map((type) => {
                const checked = rec.selectedTypes.includes(type.id);
                const typeName = resolveTextTypeName(type.id, type.name);
                return (
                  <label
                    key={`${group.key}-${type.id}`}
                    className={cn(
                      'flex min-w-0 cursor-pointer items-center gap-1.5 self-stretch rounded-xl border px-2.5 py-1.5 text-[11px] leading-4 transition-colors',
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
                          checked ? previous.filter((id) => id !== type.id) : [...previous, type.id],
                        );
                      }}
                      className="h-3.5 w-3.5"
                    />
                    <span className="min-w-0 truncate font-medium">{typeName}</span>
                  </label>
                );
              })}
            </div>
            {group.types.length > 0 && (
              <div className="mt-auto border-t border-border/70 px-2 py-2">
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
  const pageSize = 15;

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clamping page indices when pipeline data changes
    setPipelinePages((current) => {
      const next = { ...current };
      rec.pipelines.forEach((pipeline) => {
        const totalPages = Math.max(1, Math.ceil(pipeline.types.length / pageSize));
        next[pipeline.mode] = Math.min(next[pipeline.mode] ?? 1, totalPages);
      });
      return next;
    });
  }, [pageSize, rec.pipelines]);

  if (rec.visionConfigState === 'loading') {
    return <p className="py-10 text-center text-sm text-muted-foreground">{t('playground.loading')}</p>;
  }

  if (rec.visionConfigState === 'unavailable') {
    return (
      <ConfigEmptyState
        title={t('playground.visionConfigUnavailableTitle')}
        description={t('playground.visionConfigUnavailableDesc')}
      />
    );
  }

  if (rec.visionConfigState === 'empty' || rec.pipelines.length === 0) {
    return (
      <ConfigEmptyState
        title={t('playground.visionConfigEmptyTitle')}
        description={t('playground.visionConfigEmptyDesc')}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {rec.pipelines.map((pipeline) => {
        const isHasImage = pipeline.mode === 'has_image';
        const selectedSet = isHasImage ? rec.selectedHasImageTypes : rec.selectedOcrHasTypes;
        const allSelected = pipeline.types.length > 0 && pipeline.types.every((type) => selectedSet.includes(type.id));
        const tone: SelectionTone = isHasImage ? 'visual' : 'semantic';
        const toneClasses = getSelectionToneClasses(tone);
        const totalPages = Math.max(1, Math.ceil(pipeline.types.length / pageSize));
        const page = pipelinePages[pipeline.mode] ?? 1;
        const visibleTypes = pipeline.types.slice((page - 1) * pageSize, page * pageSize);

        return (
          <section
            key={pipeline.mode}
            className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[20px] border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]"
            data-testid={`playground-pipeline-${pipeline.mode}`}
          >
            <div className={cn('flex items-center justify-between gap-2 border-b px-3 py-2', toneClasses.headerSurface)}>
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn('size-2 rounded-full', toneClasses.dot)} />
                <span className={cn('truncate text-xs font-semibold tracking-[0.02em]', toneClasses.titleText)}>
                  {isHasImage ? t('playground.imageFeatures') : t('playground.ocrText')}
                </span>
                <Badge
                  variant="secondary"
                  className={cn('rounded-full border bg-background/85 px-2 py-0.5 text-[10px] shadow-none', toneClasses.badgeText)}
                >
                  {pipeline.types.length}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-6.5 rounded-full px-2 text-[10px]"
                onClick={() => {
                  rec.clearPlaygroundVisionPresetTracking();
                  const ids = pipeline.types.map((type) => type.id);
                  if (allSelected) {
                    if (isHasImage) {
                      rec.updateHasImageTypes([]);
                    } else {
                      rec.updateOcrHasTypes([]);
                    }
                  } else {
                    if (isHasImage) {
                      rec.updateHasImageTypes(ids);
                    } else {
                      rec.updateOcrHasTypes(ids);
                    }
                  }
                }}
              >
                {allSelected ? t('playground.clear') : t('playground.selectAll')}
              </Button>
            </div>
            <div className="grid flex-1 grid-cols-3 grid-rows-5 content-start gap-1.5 p-2">
              {visibleTypes.map((type) => {
                const checked = selectedSet.includes(type.id);
                return (
                  <label
                    key={type.id}
                    className={cn(
                      'flex min-w-0 cursor-pointer items-center gap-1.5 self-stretch rounded-xl border px-2.5 py-1.5 text-[11px] leading-4 transition-colors',
                      checked
                        ? toneClasses.cardSelectedCompact
                        : 'border-border/70 bg-background hover:border-border hover:bg-accent/35',
                    )}
                    title={type.description || type.name}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => rec.toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'has_image')}
                      className="h-3.5 w-3.5"
                    />
                    <span className="min-w-0 truncate font-medium">{type.name}</span>
                  </label>
                );
              })}
            </div>
            {pipeline.types.length > 0 && (
              <div className="mt-auto border-t border-border/70 px-2 py-2">
                <PaginationRail
                  page={page}
                  pageSize={pageSize}
                  totalItems={pipeline.types.length}
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
