// Copyright 2026 DataInfra-RedactionEverything Contributors

import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import {
  selectableCardClass,
  selectableCheckboxClass,
  type SelectionVariant,
} from '@/ui/selectionClasses';
import { localizeRecognitionTypeName } from '../lib/redaction-display';
import type { EntityTypeConfig, PipelineConfig } from '../hooks/use-entity-types';

const checkboxGridClass =
  'grid grid-cols-2 gap-2 rounded-xl border bg-muted/20 p-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6';
const checkboxTileClass =
  'flex min-h-9 min-w-0 cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-xs leading-4 transition-colors';

function getPipelineLabel(pipelineMode: PipelineConfig['mode'], t: (key: string) => string) {
  if (pipelineMode === 'ocr_has') return t('settings.redaction.ocrGroup');
  return t('settings.redaction.imageGroup');
}

export function TypeCheckboxGrid({
  title,
  types,
  selectedIds,
  onToggle,
  onSelectAll,
  onClear,
  variant,
}: {
  title: string;
  types: EntityTypeConfig[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  onSelectAll?: (ids: string[]) => void;
  onClear?: (ids: string[]) => void;
  variant: SelectionVariant;
}) {
  const t = useT();
  const visibleIds = types.map((type) => type.id);

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex min-h-6 items-center justify-between gap-2">
        <p className="border-l-[3px] border-muted-foreground/30 pl-2 text-sm font-semibold">
          {title} <span className="text-xs text-muted-foreground">({types.length})</span>
        </p>
        {types.length > 0 && (
          <div className="flex shrink-0 items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => onSelectAll?.(visibleIds)}
            >
              {t('settings.redaction.selectAll')}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => onClear?.(visibleIds)}
            >
              {t('settings.redaction.clearSelection')}
            </Button>
          </div>
        )}
      </div>
      <div role="group" aria-label={title} className={checkboxGridClass}>
        {types.length === 0 ? (
          <div className="col-span-full flex min-h-24 items-center justify-center rounded-xl border border-dashed border-border/70 bg-background/75 px-4 text-center text-xs leading-5 text-muted-foreground">
            {variant === 'regex'
              ? t('settings.redaction.regexEmptyInline')
              : t('settings.noTypeConfig')}
          </div>
        ) : (
          types.map((type) => {
            const checked = selectedIds.includes(type.id);
            const label = localizeRecognitionTypeName(type, t);
            return (
              <label
                key={type.id}
                title={label}
                className={cn(checkboxTileClass, selectableCardClass(checked, variant))}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(type.id)}
                  className={cn('shrink-0', selectableCheckboxClass(variant, 'md'))}
                />
                <span className="min-w-0 truncate font-medium">{label}</span>
              </label>
            );
          })
        )}
      </div>
    </div>
  );
}

export function PipelineCheckboxGrid({
  pipeline,
  selectedOcr,
  selectedImg,
  onToggle,
  onSelectAll,
  onClear,
}: {
  pipeline: PipelineConfig;
  selectedOcr: string[];
  selectedImg: string[];
  onToggle: (mode: string, id: string) => void;
  onSelectAll?: (mode: string, ids: string[]) => void;
  onClear?: (mode: string, ids: string[]) => void;
}) {
  const t = useT();
  const variant: SelectionVariant = pipeline.mode === 'ocr_has' ? 'semantic' : 'visual';
  const selectedIds = pipeline.mode === 'ocr_has' ? selectedOcr : selectedImg;
  const pipelineLabel = getPipelineLabel(pipeline.mode, t);
  const imageHintId = pipeline.mode === 'visual_features' ? 'settings-has-image-types-hint' : undefined;
  const visibleTypes = pipeline.types;
  const visibleIds = visibleTypes.map((type) => type.id);

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex min-h-6 min-w-0 flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <p className="shrink-0 border-l-[3px] border-muted-foreground/30 pl-2 text-sm font-semibold">
          {pipelineLabel}{' '}
          <span className="text-xs text-muted-foreground">({visibleTypes.length})</span>
        </p>
        <div className="flex min-w-0 items-center justify-end gap-2">
          {pipeline.mode === 'visual_features' && (
            <p
              id={imageHintId}
              data-testid="settings-has-image-types-hint"
              title={t('settings.redaction.imageGroupHint')}
              className="min-w-0 truncate text-xs leading-4 text-muted-foreground sm:max-w-[26rem] sm:text-right"
            >
              {t('settings.redaction.imageGroupHint')}
            </p>
          )}
          {visibleTypes.length > 0 && (
            <div className="flex shrink-0 items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => onSelectAll?.(pipeline.mode, visibleIds)}
              >
                {t('settings.redaction.selectAll')}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={() => onClear?.(pipeline.mode, visibleIds)}
              >
                {t('settings.redaction.clearSelection')}
              </Button>
            </div>
          )}
        </div>
      </div>
      <div
        role="group"
        aria-label={pipelineLabel}
        aria-describedby={imageHintId}
        className={cn(checkboxGridClass, pipeline.mode === 'visual_features' && 'bg-white')}
      >
        {visibleTypes.length === 0 ? (
          <div className="col-span-full flex min-h-24 items-center justify-center rounded-xl border border-dashed border-border/70 bg-background/75 px-4 text-center text-xs leading-5 text-muted-foreground">
            {t('settings.redaction.pipelineEmptyInline')}
          </div>
        ) : (
          visibleTypes.map((type) => {
            const active = selectedIds.includes(type.id);
            const label = localizeRecognitionTypeName(type, t);
            return (
              <label
                key={type.id}
                title={label}
                className={cn(checkboxTileClass, selectableCardClass(active, variant))}
              >
                <input
                  type="checkbox"
                  checked={active}
                  onChange={() => onToggle(pipeline.mode, type.id)}
                  aria-label={label}
                  className={cn('shrink-0', selectableCheckboxClass(variant, 'md'))}
                />
                <span className="min-w-0 truncate font-medium">{label}</span>
              </label>
            );
          })
        )}
      </div>
    </div>
  );
}
