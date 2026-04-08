// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { memo, useEffect, useState } from 'react';

import { useT } from '@/i18n';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

import { useBatchWizardContext } from '../batch-wizard-context';
import type { PreviewGroup } from './batch-step1-preview';
import { BatchStep1PresetCards } from './batch-step1-preset-cards';
import { BatchStep1PreviewCards } from './batch-step1-preview';
import { BatchStep1Footer } from './batch-step1-footer';

function BatchStep1ConfigInner() {
  const t = useT();
  const {
    cfg,
    setCfg,
    configLoaded,
    textTypes,
    pipelines,
    textPresets,
    visionPresets,
    onBatchTextPresetChange,
    onBatchVisionPresetChange,
    confirmStep1,
    setConfirmStep1,
    isStep1Complete,
    jobPriority,
    setJobPriority,
    advanceToUploadStep,
  } = useBatchWizardContext();

  const [previewDialog, setPreviewDialog] = useState<'text' | 'image' | null>(null);

  useEffect(() => {
    if (cfg.executionDefault !== 'queue') {
      setCfg((current) => ({ ...current, executionDefault: 'queue' }));
    }
  }, [cfg.executionDefault, setCfg]);

  const textRedactionMode = cfg.replacementMode ?? 'structured';
  const imageRedactionMethod = cfg.imageRedactionMethod ?? 'mosaic';
  const imageRedactionStrength = cfg.imageRedactionStrength ?? 25;
  const imageFillColor = cfg.imageFillColor ?? '#000000';
  const textPresetName =
    textPresets.find((preset) => preset.id === cfg.presetTextId)?.name ??
    t('batchWizard.step1.defaultPreset');
  const visionPresetName =
    visionPresets.find((preset) => preset.id === cfg.presetVisionId)?.name ??
    t('batchWizard.step1.defaultPreset');
  const selectedRegexLabels = textTypes
    .filter((type) => cfg.selectedEntityTypeIds.includes(type.id) && Boolean(type.regex_pattern))
    .map((type) => type.name);
  const selectedSemanticLabels = textTypes
    .filter((type) => cfg.selectedEntityTypeIds.includes(type.id) && !type.regex_pattern)
    .map((type) => type.name);
  const ocrTypes = pipelines
    .filter((pipeline) => pipeline.mode === 'ocr_has')
    .flatMap((pipeline) => pipeline.types);
  const hasImageTypes = pipelines
    .filter((pipeline) => pipeline.mode === 'has_image')
    .flatMap((pipeline) => pipeline.types);
  const selectedOcrLabels = ocrTypes
    .filter((type) => cfg.ocrHasTypes.includes(type.id))
    .map((type) => type.name);
  const selectedImageLabels = hasImageTypes
    .filter((type) => cfg.hasImageTypes.includes(type.id))
    .map((type) => type.name);
  const textModeLabel =
    textRedactionMode === 'smart'
      ? t('mode.smart')
      : textRedactionMode === 'mask'
        ? t('mode.mask')
        : t('mode.structured');
  const imageMethodLabel =
    imageRedactionMethod === 'blur'
      ? t('batchWizard.step1.imageMethodBlur')
      : imageRedactionMethod === 'fill'
        ? t('batchWizard.step1.imageMethodFill')
        : t('batchWizard.step1.imageMethodMosaic');
  const imageMethodHint =
    imageRedactionMethod === 'blur'
      ? t('batchWizard.step1.imageMethodBlurHint')
      : imageRedactionMethod === 'fill'
        ? t('batchWizard.step1.imageMethodFillHint')
        : t('batchWizard.step1.imageMethodMosaicHint');
  const imageDetailPills =
    imageRedactionMethod === 'fill'
      ? [
          `${t('batchWizard.step1.currentImageMethod')}${imageMethodLabel}`,
          `${t('batchWizard.step1.currentImageColor')}${imageFillColor.toUpperCase()}`,
        ]
      : [
          `${t('batchWizard.step1.currentImageMethod')}${imageMethodLabel}`,
          `${t('batchWizard.step1.currentImageStrength')}${imageRedactionStrength}%`,
        ];
  const textPreviewGroups: PreviewGroup[] = [
    {
      title: t('settings.regex'),
      items: selectedRegexLabels,
      emptyLabel: t('batchWizard.step1.noTextSelection'),
    },
    {
      title: t('settings.semantic'),
      items: selectedSemanticLabels,
      emptyLabel: t('batchWizard.step1.noTextSelection'),
    },
  ];
  const imagePreviewGroups: PreviewGroup[] = [
    {
      title: t('batchWizard.step1.ocrTypes'),
      items: selectedOcrLabels,
      emptyLabel: t('batchWizard.step1.noVisionSelection'),
    },
    {
      title: t('batchWizard.step1.imageTypes'),
      items: selectedImageLabels,
      emptyLabel: t('batchWizard.step1.noVisionSelection'),
    },
  ];

  if (!configLoaded) {
    return (
      <Card className="rounded-[24px] border-border/70 shadow-[var(--shadow-control)]" data-testid="batch-step1-loading">
        <CardContent className="p-6">
          <p className="text-sm text-muted-foreground">
            {t('batchWizard.step1.loadingConfig')}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card
      className="page-surface flex-1 rounded-[24px] border-border/70 shadow-[var(--shadow-control)]"
      data-testid="batch-step1-config"
    >
      <CardHeader className="flex flex-col gap-0.5 border-b border-border/70 pb-2 pt-3">
        <CardTitle className="text-base tracking-[-0.03em]">{t('batchWizard.step1.title')}</CardTitle>
        <p className="text-sm text-muted-foreground leading-snug">
          {t('batchWizard.step1.desc')}
        </p>
      </CardHeader>

      <CardContent className="page-surface-body flex-1 flex flex-col gap-2 pt-2">
        <BatchStep1PresetCards
          cfg={cfg}
          setCfg={setCfg}
          textPresets={textPresets}
          visionPresets={visionPresets}
          onBatchTextPresetChange={onBatchTextPresetChange}
          onBatchVisionPresetChange={onBatchVisionPresetChange}
          textRedactionMode={textRedactionMode}
          textModeLabel={textModeLabel}
          imageRedactionMethod={imageRedactionMethod}
          imageMethodLabel={imageMethodLabel}
          imageMethodHint={imageMethodHint}
          imageRedactionStrength={imageRedactionStrength}
          imageFillColor={imageFillColor}
        />

        <BatchStep1PreviewCards
          textPreviewGroups={textPreviewGroups}
          imagePreviewGroups={imagePreviewGroups}
          textPresetName={textPresetName}
          visionPresetName={visionPresetName}
          textModeLabel={textModeLabel}
          imageDetailPills={imageDetailPills}
          previewDialog={previewDialog}
          setPreviewDialog={setPreviewDialog}
        />
      </CardContent>

      <BatchStep1Footer
        confirmStep1={confirmStep1}
        setConfirmStep1={setConfirmStep1}
        isStep1Complete={isStep1Complete}
        jobPriority={jobPriority}
        setJobPriority={setJobPriority}
        advanceToUploadStep={advanceToUploadStep}
      />
    </Card>
  );
}

export const BatchStep1Config = memo(BatchStep1ConfigInner);
