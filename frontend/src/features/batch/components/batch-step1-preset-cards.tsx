// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { memo, useMemo } from 'react';

import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Card, CardContent } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { RecognitionPreset } from '@/services/presetsApi';
import type { BatchWizardMode, BatchWizardPersistedConfig } from '@/services/batchPipeline';

const DEFAULT_PRESET_VALUE = '__default__';

export interface BatchStep1PresetCardsProps {
  mode: BatchWizardMode;
  cfg: BatchWizardPersistedConfig;
  setCfg: React.Dispatch<React.SetStateAction<BatchWizardPersistedConfig>>;
  disabled?: boolean;
  textPresets: RecognitionPreset[];
  visionPresets: RecognitionPreset[];
  onBatchTextPresetChange: (id: string) => void;
  onBatchVisionPresetChange: (id: string) => void;
  textRedactionMode: string;
  textModeLabel: string;
  imageRedactionMethod: string;
  imageMethodLabel: string;
  imageMethodHint: string;
  imageRedactionStrength: number;
  imageFillColor: string;
  defaultTextSummary: string;
  defaultVisionSummary: string;
  defaultVisionExcludedSummary: string;
}

function BatchStep1PresetCardsInner({
  mode,
  cfg,
  setCfg,
  disabled = false,
  textPresets,
  visionPresets,
  onBatchTextPresetChange,
  onBatchVisionPresetChange,
  textRedactionMode,
  textModeLabel,
  imageRedactionMethod,
  imageMethodLabel,
  imageMethodHint,
  imageRedactionStrength,
  imageFillColor,
  defaultTextSummary,
  defaultVisionSummary,
  defaultVisionExcludedSummary,
}: BatchStep1PresetCardsProps) {
  const t = useT();
  const showTextConfig = mode !== 'image';
  const showVisionConfig = mode !== 'text';
  const showIndustryConfig = mode === 'smart';
  const industryPresets = useMemo(() => {
    const byId = new Map<string, RecognitionPreset>();
    [...textPresets, ...visionPresets].forEach((preset) => {
      if (preset.readonly || preset.id.startsWith('industry_')) byId.set(preset.id, preset);
    });
    return [...byId.values()];
  }, [textPresets, visionPresets]);
  const activeIndustryPresetId =
    industryPresets.find(
      (preset) => preset.id === cfg.presetTextId || preset.id === cfg.presetVisionId,
    )?.id ?? DEFAULT_PRESET_VALUE;

  const onIndustryPresetChange = (value: string) => {
    if (value === DEFAULT_PRESET_VALUE) {
      onBatchTextPresetChange('');
      onBatchVisionPresetChange('');
      return;
    }
    const preset = industryPresets.find((item) => item.id === value);
    if (!preset) return;
    if ((preset.kind ?? 'full') === 'full') {
      onBatchTextPresetChange(value);
      return;
    }
    if (preset.kind === 'text') onBatchTextPresetChange(value);
    if (preset.kind === 'vision') onBatchVisionPresetChange(value);
  };

  const textModeBullets = [
    { key: 'structured', label: t('batchWizard.step1.textModeBulletStructured') },
    { key: 'smart', label: t('batchWizard.step1.textModeBulletSmart') },
    { key: 'mask', label: t('batchWizard.step1.textModeBulletMask') },
  ];

  return (
    <div className="flex shrink-0 flex-col gap-2">
      {showIndustryConfig && industryPresets.length > 0 && (
        <div className="shrink-0 rounded-xl border border-border/70 !bg-white px-2.5 py-2">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] sm:items-center">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
                <span className="truncate text-sm font-semibold">
                  {t('batchWizard.step1.industryPreset')}
                </span>
              </div>
              <p className="mt-0.5 text-xs leading-tight text-muted-foreground">
                {t('batchWizard.step1.industryPresetDesc')}
              </p>
            </div>
            <Select
              disabled={disabled}
              value={activeIndustryPresetId}
              onValueChange={onIndustryPresetChange}
            >
              <SelectTrigger className="text-xs" data-testid="industry-preset-select">
                <SelectValue placeholder={t('batchWizard.step1.industryPresetPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DEFAULT_PRESET_VALUE}>
                  {t('batchWizard.step1.industryPresetPlaceholder')}
                </SelectItem>
                {industryPresets.map((preset) => (
                  <SelectItem key={preset.id} value={preset.id}>
                    {preset.name}
                    {(preset.kind ?? 'full') === 'full'
                      ? ` (${t('batchWizard.step1.comboPreset')})`
                      : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}
      <div
        className={cn(
          'grid shrink-0 gap-2',
          showTextConfig && showVisionConfig && 'xl:grid-cols-2',
        )}
      >
        {showTextConfig && (
          <Card
            className="min-h-0 rounded-xl border-border/70 !bg-white shadow-[var(--shadow-sm)]"
            data-testid="step1-text-config-card"
          >
            <CardContent className="flex h-full flex-col gap-1.5 p-2.5">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                <span className="truncate text-sm font-semibold">
                  {t('batchWizard.step1.textPreset')}
                </span>
              </div>
              <p className="text-xs leading-tight text-muted-foreground">
                {t('batchWizard.step1.textPresetDesc')}
              </p>
              <Select
                disabled={disabled}
                value={cfg.presetTextId || DEFAULT_PRESET_VALUE}
                onValueChange={(value) =>
                  onBatchTextPresetChange(value === DEFAULT_PRESET_VALUE ? '' : value)
                }
              >
                <SelectTrigger className="text-xs" data-testid="text-preset-select">
                  <SelectValue placeholder={t('batchWizard.step1.defaultPreset')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT_PRESET_VALUE}>
                    {t('batchWizard.step1.defaultPreset')}
                  </SelectItem>
                  {textPresets.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                      {p.kind === 'full' ? ` (${t('batchWizard.step1.comboPreset')})` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {!cfg.presetTextId && (
                <p className="rounded-lg border border-border/70 !bg-white px-2.5 py-1.5 text-[11px] leading-4 text-muted-foreground">
                  {defaultTextSummary}
                </p>
              )}
              <div className="flex flex-col gap-1 rounded-xl border border-border/70 !bg-white px-2.5 py-1.5">
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {t('batchWizard.step1.textRedactionMode')}
                  </p>
                  <span className="shrink-0 rounded-full border border-border/70 bg-background px-2.5 py-0.5 text-[11px] font-medium text-foreground">
                    {textModeLabel}
                  </span>
                </div>
                <Select
                  disabled={disabled}
                  value={textRedactionMode}
                  onValueChange={(value: 'structured' | 'smart' | 'mask') =>
                    setCfg((current) => ({ ...current, replacementMode: value }))
                  }
                >
                  <SelectTrigger className="text-xs" data-testid="text-redaction-mode-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="structured">
                      {t('batchWizard.step1.textMethodStructured')}
                    </SelectItem>
                    <SelectItem value="smart">{t('batchWizard.step1.textMethodSmart')}</SelectItem>
                    <SelectItem value="mask">{t('batchWizard.step1.textMethodMask')}</SelectItem>
                  </SelectContent>
                </Select>
                <ul className="mt-1.5 space-y-1 overflow-hidden">
                  {textModeBullets.map((bullet) => (
                    <li
                      key={bullet.key}
                      className={cn(
                        'flex items-center gap-1.5 text-[11px] leading-4',
                        bullet.key === textRedactionMode
                          ? 'font-medium text-foreground'
                          : 'text-muted-foreground',
                      )}
                    >
                      <span className="inline-block size-1 shrink-0 rounded-full bg-current" />
                      <span className="truncate">{bullet.label}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </CardContent>
          </Card>
        )}

        {showVisionConfig && (
          <Card
            className="min-h-0 rounded-xl border-border/70 !bg-white shadow-[var(--shadow-sm)]"
            data-testid="step1-vision-config-card"
          >
            <CardContent className="flex h-full flex-col gap-1.5 p-2.5">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--selection-yolo-accent)]" />
                <span className="truncate text-sm font-semibold">
                  {t('batchWizard.step1.imagePreset')}
                </span>
              </div>
              <p className="text-xs leading-tight text-muted-foreground">
                {t('batchWizard.step1.imagePresetDesc')}
              </p>
              <Select
                disabled={disabled}
                value={cfg.presetVisionId || DEFAULT_PRESET_VALUE}
                onValueChange={(value) =>
                  onBatchVisionPresetChange(value === DEFAULT_PRESET_VALUE ? '' : value)
                }
              >
                <SelectTrigger className="text-xs" data-testid="vision-preset-select">
                  <SelectValue placeholder={t('batchWizard.step1.defaultPreset')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT_PRESET_VALUE}>
                    {t('batchWizard.step1.defaultPreset')}
                  </SelectItem>
                  {visionPresets.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                      {p.kind === 'full' ? ` (${t('batchWizard.step1.comboPreset')})` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {!cfg.presetVisionId && (
                <div className="rounded-lg border border-border/70 !bg-white px-2.5 py-1.5 text-[11px] leading-4 text-muted-foreground">
                  <p>{defaultVisionSummary}</p>
                  {defaultVisionExcludedSummary ? (
                    <p className="mt-1 text-amber-700">{defaultVisionExcludedSummary}</p>
                  ) : null}
                </div>
              )}
              <div className="flex flex-col gap-1 rounded-xl border border-border/70 !bg-white px-2.5 py-1.5">
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {t('batchWizard.step1.imageRedactionMode')}
                  </p>
                  <span className="shrink-0 rounded-full border border-border/70 !bg-white px-2.5 py-0.5 text-[11px] font-medium text-foreground">
                    {imageMethodLabel}
                  </span>
                </div>
                <p
                  className="truncate text-[11px] leading-4 text-muted-foreground"
                  title={imageMethodHint}
                >
                  {imageMethodHint}
                </p>
                <Select
                  disabled={disabled}
                  value={imageRedactionMethod}
                  onValueChange={(value: 'mosaic' | 'blur' | 'fill') =>
                    setCfg((current) => ({ ...current, imageRedactionMethod: value }))
                  }
                >
                  <SelectTrigger className="text-xs" data-testid="image-redaction-mode-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="mosaic">
                      {t('batchWizard.step1.imageMethodMosaic')}
                    </SelectItem>
                    <SelectItem value="blur">{t('batchWizard.step1.imageMethodBlur')}</SelectItem>
                    <SelectItem value="fill">{t('batchWizard.step1.imageMethodFill')}</SelectItem>
                  </SelectContent>
                </Select>

                {imageRedactionMethod === 'fill' ? (
                  <div className="grid gap-1.5 sm:grid-cols-[minmax(0,1fr)_6rem]">
                    <div className="space-y-0.5">
                      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        {t('batchWizard.step1.imageFillColorLabel')}
                      </p>
                      <div className="flex items-center gap-2 rounded-2xl border border-border/70 !bg-white px-2.5 py-1.5">
                        <input
                          type="color"
                          value={imageFillColor}
                          disabled={disabled}
                          onChange={(event) =>
                            setCfg((current) => ({
                              ...current,
                              imageFillColor: event.target.value,
                            }))
                          }
                          className="h-6 w-6 rounded-md border-0 bg-transparent p-0"
                          data-testid="image-redaction-color"
                        />
                        <span className="text-xs font-medium text-foreground">
                          {imageFillColor.toUpperCase()}
                        </span>
                      </div>
                    </div>
                    <div className="space-y-0.5">
                      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        {t('batchWizard.step1.previewSwatch')}
                      </p>
                      <div
                        className="h-[2rem] rounded-2xl border border-border/70"
                        style={{ backgroundColor: imageFillColor }}
                        aria-hidden
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        {t('batchWizard.step1.imageStrengthLabel')}
                      </p>
                      <span className="rounded-full border border-border/70 !bg-white px-2.5 py-0.5 text-[11px] font-medium text-foreground">
                        {imageRedactionStrength}%
                      </span>
                    </div>
                    <input
                      type="range"
                      min="10"
                      max="100"
                      step="5"
                      value={imageRedactionStrength}
                      disabled={disabled}
                      onChange={(event) =>
                        setCfg((current) => ({
                          ...current,
                          imageRedactionStrength: Number(event.target.value),
                        }))
                      }
                      className="w-full accent-primary"
                      data-testid="image-redaction-strength"
                    />
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

export const BatchStep1PresetCards = memo(BatchStep1PresetCardsInner);
