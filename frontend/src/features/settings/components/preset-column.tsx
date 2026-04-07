// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useMemo } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  presetAppliesText,
  presetAppliesVision,
  type RecognitionPreset,
} from '@/services/presetsApi';
import type { EntityTypeConfig, PipelineConfig } from '../hooks/use-entity-types';

const presetMetaPillClass =
  'inline-flex h-7 items-center rounded-full border border-border/70 bg-muted/45 px-2.5 text-[11px] font-medium leading-none text-muted-foreground';
const presetActionButtonClass =
  'h-7 rounded-full border-border/80 bg-background px-3 text-[11px] font-medium leading-none';
const presetDangerButtonClass =
  'h-7 rounded-full border-destructive/25 bg-background px-3 text-[11px] font-medium leading-none text-destructive hover:bg-destructive/8';
const presetPreviewChipClass =
  'inline-flex h-7 w-full items-center rounded-[14px] border border-border/70 bg-background px-2 text-[11px] font-medium leading-none';
const presetPreviewChipGridClass = 'grid grid-cols-3 gap-1.5 xl:grid-cols-4 2xl:grid-cols-5';

export function PresetColumn({
  title,
  defaultPreset,
  presets,
  entityTypes,
  pipelines,
  expanded,
  setExpanded,
  colPrefix,
  onEdit,
  onDelete,
}: {
  title: string;
  defaultPreset: RecognitionPreset;
  presets: RecognitionPreset[];
  entityTypes: EntityTypeConfig[];
  pipelines: PipelineConfig[];
  expanded: string | null;
  setExpanded: React.Dispatch<React.SetStateAction<string | null>>;
  colPrefix: string;
  onEdit: (preset: RecognitionPreset) => void;
  onDelete: (id: string) => void;
}) {
  const t = useT();
  const defaultKey = `${colPrefix}:__default__`;

  return (
    <div className="flex min-h-0 flex-col">
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <ul className="max-h-[min(55vh,520px)] divide-y divide-border overflow-y-auto rounded-md border text-xs">
        <li className="bg-muted/30">
          <div className="flex flex-wrap items-center justify-between gap-1 px-2 py-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{defaultPreset.name}</span>
              <Badge variant="secondary" className={presetMetaPillClass}>
                {t('settings.redaction.systemDefault')}
              </Badge>
            </div>
            <Button
              size="sm"
              variant="outline"
              className={presetActionButtonClass}
              onClick={() => setExpanded(current => current === defaultKey ? null : defaultKey)}
            >
              {expanded === defaultKey ? t('settings.redaction.collapse') : t('settings.redaction.preview')}
            </Button>
          </div>
          {expanded === defaultKey && (
            <PresetPreview preset={defaultPreset} entityTypes={entityTypes} pipelines={pipelines} />
          )}
        </li>

        {presets.map(preset => {
          const rowKey = `${colPrefix}:${preset.id}`;
          return (
            <li key={preset.id} className="bg-muted/30">
              <div className="flex flex-wrap items-center justify-between gap-1 px-2 py-1.5">
                <span className="font-medium">{preset.name}</span>
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="outline"
                    className={presetActionButtonClass}
                    onClick={() => setExpanded(current => current === rowKey ? null : rowKey)}
                  >
                    {expanded === rowKey ? t('settings.redaction.collapse') : t('settings.redaction.preview')}
                  </Button>
                  <Button size="sm" variant="outline" className={presetActionButtonClass} onClick={() => onEdit(preset)}>
                    {t('settings.redaction.edit')}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className={presetDangerButtonClass}
                    onClick={() => void onDelete(preset.id)}
                  >
                    {t('settings.redaction.delete')}
                  </Button>
                </div>
              </div>
              {expanded === rowKey && (
                <PresetPreview preset={preset} entityTypes={entityTypes} pipelines={pipelines} />
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function PresetPreview({
  preset,
  entityTypes,
  pipelines,
}: {
  preset: RecognitionPreset;
  entityTypes: EntityTypeConfig[];
  pipelines: PipelineConfig[];
}) {
  const t = useT();
  const ocrPipeline = pipelines.find(pipeline => pipeline.mode === 'ocr_has');
  const imagePipeline = pipelines.find(pipeline => pipeline.mode === 'has_image');

  const selectedRegexTypes = useMemo(
    () => preset.selectedEntityTypeIds.filter(id => entityTypes.find(type => type.id === id)?.regex_pattern),
    [preset.selectedEntityTypeIds, entityTypes],
  );
  const selectedSemanticTypes = useMemo(
    () => preset.selectedEntityTypeIds.filter(id => {
      const et = entityTypes.find(type => type.id === id);
      return et && et.use_llm && !et.regex_pattern;
    }),
    [preset.selectedEntityTypeIds, entityTypes],
  );

  return (
    <div className="space-y-2 border-t px-2 pb-3 pt-2">
      {presetAppliesText(preset) && selectedRegexTypes.length > 0 && (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
            {t('settings.redaction.regexGroup')} ({selectedRegexTypes.length})
          </p>
          <div className={presetPreviewChipGridClass}>
            {selectedRegexTypes.map(id => (
              <span
                key={id}
                className={cn(presetPreviewChipClass, 'truncate')}
                title={entityTypes.find(type => type.id === id)?.name ?? id}
              >
                {entityTypes.find(type => type.id === id)?.name ?? id}
              </span>
            ))}
          </div>
        </div>
      )}

      {presetAppliesText(preset) && selectedSemanticTypes.length > 0 && (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
            {t('settings.redaction.semanticGroup')} ({selectedSemanticTypes.length})
          </p>
          <div className={presetPreviewChipGridClass}>
            {selectedSemanticTypes.map(id => (
              <span
                key={id}
                className={cn(presetPreviewChipClass, 'truncate')}
                title={entityTypes.find(type => type.id === id)?.name ?? id}
              >
                {entityTypes.find(type => type.id === id)?.name ?? id}
              </span>
            ))}
          </div>
        </div>
      )}

      {presetAppliesVision(preset) && (
        <>
          {preset.ocrHasTypes.length > 0 && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
                {t('settings.redaction.ocrGroup')} ({preset.ocrHasTypes.length})
              </p>
              <div className={presetPreviewChipGridClass}>
                {preset.ocrHasTypes.map(id => (
                  <span
                    key={id}
                    className={cn(presetPreviewChipClass, 'truncate')}
                    title={ocrPipeline?.types.find(type => type.id === id)?.name ?? id}
                  >
                    {ocrPipeline?.types.find(type => type.id === id)?.name ?? id}
                  </span>
                ))}
              </div>
            </div>
          )}
          {preset.hasImageTypes.length > 0 && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
                {t('settings.redaction.imageGroup')} ({preset.hasImageTypes.length})
              </p>
              <div className={presetPreviewChipGridClass}>
                {preset.hasImageTypes.map(id => (
                  <span
                    key={id}
                    className={cn(presetPreviewChipClass, 'truncate')}
                    title={imagePipeline?.types.find(type => type.id === id)?.name ?? id}
                  >
                    {imagePipeline?.types.find(type => type.id === id)?.name ?? id}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
