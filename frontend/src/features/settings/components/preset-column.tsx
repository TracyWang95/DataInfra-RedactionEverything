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
import { localizePresetName, localizeRecognitionTypeName } from '../lib/redaction-display';
import type { EntityTypeConfig, PipelineConfig } from '../hooks/use-entity-types';

const presetMetaPillClass =
  'inline-flex h-6 w-[4.5rem] items-center justify-center whitespace-nowrap rounded-full border border-border/70 bg-muted/45 px-2 text-xs font-medium leading-none text-muted-foreground';
const presetActionButtonClass =
  'h-7 whitespace-nowrap rounded-full border-border/80 bg-background px-3 text-xs font-medium leading-none';
const presetDangerButtonClass =
  'h-7 whitespace-nowrap rounded-full border-destructive/25 bg-background px-3 text-xs font-medium leading-none text-destructive hover:bg-destructive/8';
const presetPreviewChipClass =
  'inline-flex h-7 w-full items-center rounded-xl border border-border/70 bg-background px-2 text-xs font-medium leading-none';
const presetPreviewChipGridClass = 'grid grid-cols-3 gap-1.5 xl:grid-cols-4 2xl:grid-cols-5';
const presetRowLeftClass = 'grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_4.5rem] items-center gap-2';
const presetRowNameClass = 'min-w-0 truncate font-medium';
const presetMetaPlaceholderClass = 'h-6 w-[4.5rem]';
type PresetPreviewScope = 'text' | 'vision';

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
  const defaultPresetName = localizePresetName(defaultPreset, t);
  const previewScope: PresetPreviewScope = colPrefix === 'text' ? 'text' : 'vision';

  return (
    <div className="flex min-h-0 flex-col">
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <ul className="divide-y divide-border/70 overflow-hidden rounded-xl border border-border/70 bg-card text-xs shadow-[var(--shadow-sm)]">
        <li className="bg-muted/30">
          <div className="flex min-h-10 flex-wrap items-center justify-between gap-2 px-2.5 py-1.5">
            <div className={presetRowLeftClass}>
              <span className={presetRowNameClass} title={defaultPresetName}>
                {defaultPresetName}
              </span>
              <Badge variant="secondary" className={presetMetaPillClass}>
                {t('settings.redaction.systemDefault')}
              </Badge>
            </div>
            <Button
              size="sm"
              variant="outline"
              className={presetActionButtonClass}
              onClick={() => setExpanded((current) => (current === defaultKey ? null : defaultKey))}
              aria-label={`${expanded === defaultKey ? t('settings.redaction.collapse') : t('settings.redaction.preview')} ${defaultPresetName}`}
            >
              {expanded === defaultKey
                ? t('settings.redaction.collapse')
                : t('settings.redaction.preview')}
            </Button>
          </div>
          {expanded === defaultKey && (
            <PresetPreview
              preset={defaultPreset}
              entityTypes={entityTypes}
              pipelines={pipelines}
              scope={previewScope}
            />
          )}
        </li>

        {presets.map((preset) => {
          const rowKey = `${colPrefix}:${preset.id}`;
          const presetName = localizePresetName(preset, t);
          return (
            <li key={preset.id} className="bg-muted/30">
              <div className="flex min-h-10 flex-wrap items-center justify-between gap-2 px-2.5 py-1.5">
                <div className={presetRowLeftClass}>
                  <span className={presetRowNameClass} title={presetName}>
                    {presetName}
                  </span>
                  {preset.readonly && (
                    <Badge variant="secondary" className={presetMetaPillClass}>
                      {t('settings.redaction.systemDefault')}
                    </Badge>
                  )}
                  {!preset.readonly && <span aria-hidden="true" className={presetMetaPlaceholderClass} />}
                </div>
                <div className="flex shrink-0 flex-wrap justify-end gap-1">
                  <Button
                    size="sm"
                    variant="outline"
                    className={presetActionButtonClass}
                    onClick={() => setExpanded((current) => (current === rowKey ? null : rowKey))}
                    aria-label={`${expanded === rowKey ? t('settings.redaction.collapse') : t('settings.redaction.preview')} ${presetName}`}
                  >
                    {expanded === rowKey
                      ? t('settings.redaction.collapse')
                      : t('settings.redaction.preview')}
                  </Button>
                  {!preset.readonly && (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        className={presetActionButtonClass}
                        onClick={() => onEdit(preset)}
                        aria-label={`${t('settings.redaction.edit')} ${presetName}`}
                      >
                        {t('settings.redaction.edit')}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className={presetDangerButtonClass}
                        onClick={() => void onDelete(preset.id)}
                        aria-label={`${t('settings.redaction.delete')} ${presetName}`}
                      >
                        {t('settings.redaction.delete')}
                      </Button>
                    </>
                  )}
                </div>
              </div>
              {expanded === rowKey && (
                <PresetPreview
                  preset={preset}
                  entityTypes={entityTypes}
                  pipelines={pipelines}
                  scope={previewScope}
                />
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
  scope,
}: {
  preset: RecognitionPreset;
  entityTypes: EntityTypeConfig[];
  pipelines: PipelineConfig[];
  scope: PresetPreviewScope;
}) {
  const t = useT();
  const showText = scope === 'text' && presetAppliesText(preset);
  const showVision = scope === 'vision' && presetAppliesVision(preset);
  const ocrPipeline = pipelines.find((pipeline) => pipeline.mode === 'ocr_has');
  const imagePipeline = pipelines.find((pipeline) => pipeline.mode === 'visual_features');
  const entityTypeById = useMemo(
    () => new Map(entityTypes.map((type) => [type.id, type])),
    [entityTypes],
  );
  const ocrTypeById = useMemo(
    () => new Map((ocrPipeline?.types ?? []).map((type) => [type.id, type])),
    [ocrPipeline?.types],
  );
  const imageTypeById = useMemo(
    () => new Map((imagePipeline?.types ?? []).map((type) => [type.id, type])),
    [imagePipeline?.types],
  );
  const selectedRegexTypes = useMemo(
    () =>
      preset.selectedEntityTypeIds.filter((id) => {
        const type = entityTypeById.get(id);
        return type?.id.startsWith('custom_') && type.regex_pattern;
      }),
    [preset.selectedEntityTypeIds, entityTypeById],
  );
  const selectedSemanticTypes = useMemo(
    () =>
      preset.selectedEntityTypeIds.filter((id) => {
        const et = entityTypeById.get(id);
        return et && et.use_llm && !et.regex_pattern;
      }),
    [preset.selectedEntityTypeIds, entityTypeById],
  );

  return (
    <div className="space-y-2 border-t px-2 pb-3 pt-2">
      {showText && selectedRegexTypes.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t('settings.redaction.regexGroup')} ({selectedRegexTypes.length})
          </p>
          <div className={presetPreviewChipGridClass}>
            {selectedRegexTypes.map((id) => {
              const type = entityTypeById.get(id);
              const label = type ? localizeRecognitionTypeName(type, t) : id;
              return (
                <span key={id} className={cn(presetPreviewChipClass, 'truncate')} title={label}>
                  {label}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {showText && selectedSemanticTypes.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t('settings.redaction.semanticGroup')} ({selectedSemanticTypes.length})
          </p>
          <div className={presetPreviewChipGridClass}>
            {selectedSemanticTypes.map((id) => {
              const type = entityTypeById.get(id);
              const label = type ? localizeRecognitionTypeName(type, t) : id;
              return (
                <span key={id} className={cn(presetPreviewChipClass, 'truncate')} title={label}>
                  {label}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {showVision && (
        <>
          {preset.ocrHasTypes.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t('settings.redaction.ocrGroup')} ({preset.ocrHasTypes.length})
              </p>
              <div className={presetPreviewChipGridClass}>
                {preset.ocrHasTypes.map((id) => {
                  const type = ocrTypeById.get(id);
                  const label = type ? localizeRecognitionTypeName(type, t) : id;
                  return (
                    <span key={id} className={cn(presetPreviewChipClass, 'truncate')} title={label}>
                      {label}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
          {(preset.visualFeatureTypes ?? preset.visualFeatureTypes ?? []).length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t('settings.redaction.imageGroup')} ({(preset.visualFeatureTypes ?? preset.visualFeatureTypes ?? []).length})
              </p>
              <div className={presetPreviewChipGridClass}>
                {(preset.visualFeatureTypes ?? preset.visualFeatureTypes ?? []).map((id: string) => {
                  const type = imageTypeById.get(id);
                  const label = type ? localizeRecognitionTypeName(type, t) : id;
                  return (
                    <span key={id} className={cn(presetPreviewChipClass, 'truncate')} title={label}>
                      {label}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
