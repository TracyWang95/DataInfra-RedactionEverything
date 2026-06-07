// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { setActivePresetTextId, setActivePresetVisionId } from '@/services/activePresetBridge';
import type { RecognitionPreset } from '@/services/presetsApi';
import { localizePresetName } from './lib/redaction-display';

const DEFAULT_PRESET_OPTION = '__default__';

export interface RedactionBridgeConfigProps {
  bridgeText: string;
  bridgeVision: string;
  textPresets: RecognitionPreset[];
  visionPresets: RecognitionPreset[];
  summaryTextLabel: string;
  summaryVisionLabel: string;
  setBridgeText: (value: string) => void;
  setBridgeVision: (value: string) => void;
}

export function RedactionBridgeConfig({
  bridgeText,
  bridgeVision,
  textPresets,
  visionPresets,
  summaryTextLabel,
  summaryVisionLabel,
  setBridgeText,
  setBridgeVision,
}: RedactionBridgeConfigProps) {
  const t = useT();

  return (
    <>
      <div className="surface-subtle flex flex-col gap-2 px-3 py-2 text-xs leading-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="shrink-0 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t('settings.redaction.currentSelection')}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-1">
          <p className="min-w-0">
            <span className="text-muted-foreground">{t('settings.redaction.currentText')}</span>
            <span className="font-medium">{summaryTextLabel}</span>
          </p>
          <p className="min-w-0">
            <span className="text-muted-foreground">{t('settings.redaction.currentVision')}</span>
            <span className="font-medium">{summaryVisionLabel}</span>
          </p>
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-2">
        <div className="space-y-1">
          <Label className="text-xs">{t('settings.redaction.linkText')}</Label>
          <Select
            value={bridgeText || DEFAULT_PRESET_OPTION}
            onValueChange={(value) => {
              const nextValue = value === DEFAULT_PRESET_OPTION ? '' : value;
              setBridgeText(nextValue);
              setActivePresetTextId(nextValue || null);
            }}
          >
            <SelectTrigger className="h-8 rounded-xl text-xs" data-testid="bridge-text-select">
              <SelectValue placeholder={t('settings.redaction.defaultOption')} />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value={DEFAULT_PRESET_OPTION}>
                  {t('settings.redaction.defaultOption')}
                </SelectItem>
                {textPresets.map((preset) => (
                  <SelectItem key={preset.id} value={preset.id}>
                    {localizePresetName(preset, t)}
                    {preset.kind === 'full' ? ` (${t('settings.redaction.kind.full')})` : ''}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">{t('settings.redaction.linkVision')}</Label>
          <Select
            value={bridgeVision || DEFAULT_PRESET_OPTION}
            onValueChange={(value) => {
              const nextValue = value === DEFAULT_PRESET_OPTION ? '' : value;
              setBridgeVision(nextValue);
              setActivePresetVisionId(nextValue || null);
            }}
          >
            <SelectTrigger className="h-8 rounded-xl text-xs" data-testid="bridge-vision-select">
              <SelectValue placeholder={t('settings.redaction.defaultOption')} />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value={DEFAULT_PRESET_OPTION}>
                  {t('settings.redaction.defaultOption')}
                </SelectItem>
                {visionPresets.map((preset) => (
                  <SelectItem key={preset.id} value={preset.id}>
                    {localizePresetName(preset, t)}
                    {preset.kind === 'full' ? ` (${t('settings.redaction.kind.full')})` : ''}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      </div>
    </>
  );
}
