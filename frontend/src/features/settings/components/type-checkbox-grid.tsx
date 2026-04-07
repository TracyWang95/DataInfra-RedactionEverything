// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import {
  selectableCardClass,
  selectableCheckboxClass,
  type SelectionVariant,
} from '@/ui/selectionClasses';
import type { EntityTypeConfig, PipelineConfig } from '../hooks/use-entity-types';

export function TypeCheckboxGrid({
  title,
  types,
  selectedIds,
  onToggle,
  variant,
}: {
  title: string;
  types: EntityTypeConfig[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  variant: SelectionVariant;
}) {
  return (
    <div>
      <p className="mb-2 border-l-[3px] border-muted-foreground/30 pl-2 text-sm font-semibold">
        {title} <span className="text-xs text-muted-foreground">({types.length})</span>
      </p>
      <div role="group" aria-label={title} className="grid grid-cols-2 gap-2 rounded-xl border bg-muted/20 p-3 sm:grid-cols-3 md:grid-cols-4">
        {types.map(type => {
          const checked = selectedIds.includes(type.id);
          return (
            <label
              key={type.id}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition-colors',
                selectableCardClass(checked, variant),
              )}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(type.id)}
                className={cn('shrink-0', selectableCheckboxClass(variant, 'md'))}
              />
              <span className="min-w-0 break-words">{type.name}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

export function PipelineCheckboxGrid({
  pipeline,
  selectedOcr,
  selectedImg,
  onToggle,
}: {
  pipeline: PipelineConfig;
  selectedOcr: string[];
  selectedImg: string[];
  onToggle: (mode: string, id: string) => void;
}) {
  const t = useT();
  const variant: SelectionVariant = pipeline.mode === 'has_image' ? 'visual' : 'semantic';
  const selectedIds = pipeline.mode === 'ocr_has' ? selectedOcr : selectedImg;

  return (
    <div>
      <p className="mb-2 border-l-[3px] border-muted-foreground/30 pl-2 text-sm font-semibold">
        {pipeline.mode === 'ocr_has' ? t('settings.redaction.ocrGroup') : t('settings.redaction.imageGroup')}
        {' '}<span className="text-xs text-muted-foreground">({pipeline.types.filter(t => t.enabled).length})</span>
      </p>
      <div role="group" aria-label={pipeline.mode === 'ocr_has' ? t('settings.redaction.ocrGroup') : t('settings.redaction.imageGroup')} className="grid grid-cols-2 gap-2 rounded-xl border bg-muted/20 p-3 sm:grid-cols-3 md:grid-cols-4">
        {pipeline.types.filter(type => type.enabled).map(type => {
          const active = selectedIds.includes(type.id);
          return (
            <label
              key={type.id}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition-colors',
                selectableCardClass(active, variant),
              )}
            >
              <input
                type="checkbox"
                checked={active}
                onChange={() => onToggle(pipeline.mode, type.id)}
                className={cn('shrink-0', selectableCheckboxClass(variant, 'md'))}
              />
              <span className="min-w-0 break-words">{type.name}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
