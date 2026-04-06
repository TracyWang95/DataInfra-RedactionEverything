
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Eye } from 'lucide-react';
import { useT } from '@/i18n';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { RecognitionPreset } from '@/services/presetsApi';
import type { BatchWizardPersistedConfig } from '@/services/batchPipeline';
import type { PipelineCfg, TextEntityType } from '../types';

const DEFAULT_PRESET_VALUE = '__default__';

interface BatchStep1ConfigProps {
  cfg: BatchWizardPersistedConfig;
  setCfg: React.Dispatch<React.SetStateAction<BatchWizardPersistedConfig>>;
  configLoaded: boolean;
  textTypes: TextEntityType[];
  pipelines: PipelineCfg[];
  textPresets: RecognitionPreset[];
  visionPresets: RecognitionPreset[];
  onBatchTextPresetChange: (id: string) => void;
  onBatchVisionPresetChange: (id: string) => void;
  confirmStep1: boolean;
  setConfirmStep1: (v: boolean) => void;
  isStep1Complete: boolean;
  jobPriority: number;
  setJobPriority: (v: number) => void;
  advanceToUploadStep: () => void;
}

export function BatchStep1Config({
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
}: BatchStep1ConfigProps) {
  const t = useT();
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
  const textModeNotes =
    textRedactionMode === 'smart'
      ? [
          t('batchWizard.step1.textModeSmartLine1'),
          t('batchWizard.step1.textModeSmartLine2'),
          t('batchWizard.step1.textModeSmartLine3'),
        ]
      : textRedactionMode === 'mask'
        ? [
            t('batchWizard.step1.textModeMaskLine1'),
            t('batchWizard.step1.textModeMaskLine2'),
            t('batchWizard.step1.textModeMaskLine3'),
          ]
        : [
            t('batchWizard.step1.textModeStructuredLine1'),
            t('batchWizard.step1.textModeStructuredLine2'),
            t('batchWizard.step1.textModeStructuredLine3'),
          ];
  const textPreviewGroups = [
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
  const imagePreviewGroups = [
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
  const previewDialogConfig =
    previewDialog === 'text'
      ? {
          title: t('batchWizard.step1.textSummary'),
          presetName: textPresetName,
          presetLabel: t('batchWizard.step1.activePreset'),
          groups: textPreviewGroups,
          summaryPills: [`${t('batchWizard.step1.currentTextMethod')}${textModeLabel}`],
        }
      : previewDialog === 'image'
        ? {
            title: t('batchWizard.step1.imageSummary'),
            presetName: visionPresetName,
            presetLabel: t('batchWizard.step1.activePreset'),
            groups: imagePreviewGroups,
            summaryPills: imageDetailPills,
          }
        : null;

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
      className="page-surface rounded-[24px] border-border/70 shadow-[var(--shadow-control)]"
      data-testid="batch-step1-config"
    >
      <CardHeader className="flex flex-col gap-1.5 border-b border-border/70 pb-4">
        <CardTitle className="text-base tracking-[-0.03em]">{t('batchWizard.step1.title')}</CardTitle>
        <p className="text-sm text-muted-foreground leading-relaxed">
          {t('batchWizard.step1.desc')}
        </p>
      </CardHeader>

      <CardContent className="page-surface-body flex flex-col gap-4 pt-5">
        <div className="grid gap-3 xl:grid-cols-2">
          <Card className="rounded-[20px] border-border/70 bg-card/90 shadow-[var(--shadow-sm)]">
            <CardContent className="flex h-full flex-col gap-3 p-4">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                <span className="text-sm font-semibold">
                  {t('batchWizard.step1.textPreset')}
                </span>
              </div>
                <p className="text-sm text-muted-foreground">
                {t('batchWizard.step1.textPresetDesc')}
              </p>
              <Select
                value={cfg.presetTextId || DEFAULT_PRESET_VALUE}
                onValueChange={value => onBatchTextPresetChange(value === DEFAULT_PRESET_VALUE ? '' : value)}
              >
                <SelectTrigger className="text-xs" data-testid="text-preset-select">
                  <SelectValue placeholder={t('batchWizard.step1.defaultPreset')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT_PRESET_VALUE}>{t('batchWizard.step1.defaultPreset')}</SelectItem>
                  {textPresets.map(p => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                      {p.kind === 'full' ? ` (${t('batchWizard.step1.comboPreset')})` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="surface-subtle flex flex-col gap-2 px-3 py-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {t('batchWizard.step1.textRedactionMode')}
                  </p>
                  <span className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-foreground">
                    {textModeLabel}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t('batchWizard.step1.textModeHint')}
                </p>
                <p className="mb-0 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {t('batchWizard.step1.textRedactionMode')}
                </p>
                <Select
                  value={textRedactionMode}
                  onValueChange={(value: 'structured' | 'smart' | 'mask') =>
                    setCfg((current) => ({ ...current, replacementMode: value }))
                  }
                >
                  <SelectTrigger className="text-xs" data-testid="text-redaction-mode-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="structured">{t('mode.structured')}</SelectItem>
                    <SelectItem value="smart">{t('mode.smart')}</SelectItem>
                    <SelectItem value="mask">{t('mode.mask')}</SelectItem>
                  </SelectContent>
                </Select>
                <div className="space-y-1 pt-1">
                  {textModeNotes.map((line) => (
                    <p key={line} className="text-[11px] leading-5 text-muted-foreground">
                      {line}
                    </p>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-[20px] border-border/70 bg-card/90 shadow-[var(--shadow-sm)]">
            <CardContent className="flex h-full flex-col gap-3 p-4">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--selection-yolo-accent)]" />
                <span className="text-sm font-semibold">
                  {t('batchWizard.step1.imagePreset')}
                </span>
              </div>
                <p className="text-sm text-muted-foreground">
                {t('batchWizard.step1.imagePresetDesc')}
              </p>
              <Select
                value={cfg.presetVisionId || DEFAULT_PRESET_VALUE}
                onValueChange={value => onBatchVisionPresetChange(value === DEFAULT_PRESET_VALUE ? '' : value)}
              >
                <SelectTrigger className="text-xs" data-testid="vision-preset-select">
                  <SelectValue placeholder={t('batchWizard.step1.defaultPreset')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT_PRESET_VALUE}>{t('batchWizard.step1.defaultPreset')}</SelectItem>
                  {visionPresets.map(p => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                      {p.kind === 'full' ? ` (${t('batchWizard.step1.comboPreset')})` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="surface-subtle flex flex-col gap-3 px-3 py-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {t('batchWizard.step1.imageRedactionMode')}
                  </p>
                  <span className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-foreground">
                    {imageMethodLabel}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {imageMethodHint}
                </p>
                <p className="mb-0 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {t('batchWizard.step1.imageRedactionMode')}
                </p>
                <Select
                  value={imageRedactionMethod}
                  onValueChange={(value: 'mosaic' | 'blur' | 'fill') =>
                    setCfg((current) => ({ ...current, imageRedactionMethod: value }))
                  }
                >
                  <SelectTrigger className="text-xs" data-testid="image-redaction-mode-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="mosaic">{t('batchWizard.step1.imageMethodMosaic')}</SelectItem>
                    <SelectItem value="blur">{t('batchWizard.step1.imageMethodBlur')}</SelectItem>
                    <SelectItem value="fill">{t('batchWizard.step1.imageMethodFill')}</SelectItem>
                  </SelectContent>
                </Select>

                {imageRedactionMethod === 'fill' ? (
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_7.5rem]">
                    <div className="space-y-1">
                      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        {t('batchWizard.step1.imageFillColorLabel')}
                      </p>
                      <div className="flex items-center gap-2 rounded-2xl border border-border/70 bg-background px-3 py-2">
                        <input
                          type="color"
                          value={imageFillColor}
                          onChange={(event) => setCfg((current) => ({ ...current, imageFillColor: event.target.value }))}
                          className="h-7 w-7 rounded-md border-0 bg-transparent p-0"
                          data-testid="image-redaction-color"
                        />
                        <span className="text-xs font-medium text-foreground">{imageFillColor.toUpperCase()}</span>
                      </div>
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        {t('batchWizard.step1.previewSwatch')}
                      </p>
                      <div
                        className="h-[3rem] rounded-2xl border border-border/70"
                        style={{ backgroundColor: imageFillColor }}
                        aria-hidden
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        {t('batchWizard.step1.imageStrengthLabel')}
                      </p>
                      <span className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-foreground">
                        {imageRedactionStrength}%
                      </span>
                    </div>
                    <input
                      type="range"
                      min="10"
                      max="100"
                      step="5"
                      value={imageRedactionStrength}
                      onChange={(event) =>
                        setCfg((current) => ({ ...current, imageRedactionStrength: Number(event.target.value) }))
                      }
                      className="w-full accent-primary"
                      data-testid="image-redaction-strength"
                    />
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          <SelectionPreviewSummaryCard
            title={t('batchWizard.step1.textSummary')}
            presetName={textPresetName}
            presetLabel={t('batchWizard.step1.activePreset')}
            groups={textPreviewGroups}
            summaryPills={[`${t('batchWizard.step1.currentTextMethod')}${textModeLabel}`]}
            onViewDetails={() => setPreviewDialog('text')}
            viewLabel={t('batchWizard.step1.viewSelection')}
          />
          <SelectionPreviewSummaryCard
            title={t('batchWizard.step1.imageSummary')}
            presetName={visionPresetName}
            presetLabel={t('batchWizard.step1.activePreset')}
            groups={imagePreviewGroups}
            summaryPills={imageDetailPills}
            onViewDetails={() => setPreviewDialog('image')}
            viewLabel={t('batchWizard.step1.viewSelection')}
          />
        </div>
      </CardContent>

      <div className="page-surface-footer">
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
          <div className="surface-subtle flex items-center justify-between gap-3 px-4 py-3">
            <span className="text-sm text-muted-foreground">
              {t('batchWizard.step1.priority')}
            </span>
            <Select
              value={String(jobPriority)}
              onValueChange={v => setJobPriority(Number(v))}
            >
              <SelectTrigger className="w-24 text-xs" data-testid="priority-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="0">{t('batchWizard.step1.priorityNormal')}</SelectItem>
                <SelectItem value="5">{t('batchWizard.step1.priorityHigh')}</SelectItem>
                <SelectItem value="10">{t('batchWizard.step1.priorityUrgent')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="surface-subtle flex flex-col gap-3 px-4 py-3">
            <label className="flex cursor-pointer items-start gap-2 text-sm">
              <Checkbox
                checked={confirmStep1}
                onCheckedChange={v => setConfirmStep1(v === true)}
                className="mt-0.5"
                data-testid="confirm-step1"
              />
              <span>{t('batchWizard.step1.confirm')}</span>
            </label>
            <Button
              className="w-full"
              disabled={!isStep1Complete}
              onClick={() => advanceToUploadStep()}
              data-testid="advance-upload"
            >
              {t('batchWizard.step1.nextUpload')}
            </Button>
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          <Link to="/jobs" className="text-primary hover:underline font-medium">
            {t('batchHub.jobCenter')}
          </Link>
          <span className="mx-1">&middot;</span>
          <Link to="/history" className="text-primary hover:underline font-medium">
            {t('batchHub.history')}
          </Link>
        </p>
      </div>

      <Dialog open={previewDialog !== null} onOpenChange={(open) => !open && setPreviewDialog(null)}>
        {previewDialogConfig ? (
          <DialogContent className="max-w-5xl gap-0 overflow-hidden border-border/70 bg-[var(--surface-overlay)] p-0">
            <DialogHeader className="border-b border-border/70 px-6 pb-4 pt-6">
              <DialogTitle>{previewDialogConfig.title}</DialogTitle>
              <DialogDescription className="text-sm leading-relaxed">
                {previewDialogConfig.presetLabel}
                <span className="ml-1 font-medium text-foreground">{previewDialogConfig.presetName}</span>
              </DialogDescription>
            </DialogHeader>

            <div className="flex max-h-[72vh] flex-col gap-5 overflow-y-auto px-6 py-5">
              {previewDialogConfig.summaryPills.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {previewDialogConfig.summaryPills.map((pill) => (
                    <span
                      key={pill}
                      className="rounded-full border border-border/70 bg-background px-3 py-1.5 text-xs font-medium text-foreground"
                    >
                      {pill}
                    </span>
                  ))}
                </div>
              ) : null}

              <div className="grid gap-4 xl:grid-cols-2">
                {previewDialogConfig.groups.map((group) => (
                  <div
                    key={group.title}
                    className="surface-subtle flex min-h-[16rem] flex-col gap-3 px-4 py-4"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="space-y-1">
                        <p className="text-sm font-semibold text-foreground">{group.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {t('batchWizard.step1.selectedTotal').replace('{n}', String(group.items.length))}
                        </p>
                      </div>
                    </div>

                    {group.items.length > 0 ? (
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {group.items.map((item) => (
                          <span
                            key={`${group.title}-${item}`}
                            className="flex h-9 items-center rounded-2xl border border-border/70 bg-background px-3 text-xs font-medium text-foreground"
                            title={item}
                          >
                            <span className="truncate">{item}</span>
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-border/70 bg-background/80 px-4 text-center text-sm text-muted-foreground">
                        {group.emptyLabel}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </DialogContent>
        ) : null}
      </Dialog>
    </Card>
  );
}

function SelectionPreviewSummaryCard({
  title,
  presetLabel,
  presetName,
  groups,
  summaryPills = [],
  onViewDetails,
  viewLabel,
}: {
  title: string;
  presetLabel: string;
  presetName: string;
  groups: Array<{ title: string; items: string[]; emptyLabel: string }>;
  summaryPills?: string[];
  onViewDetails: () => void;
  viewLabel: string;
}) {
  const t = useT();
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  const firstGroup = groups[0];
  const secondGroup = groups[1];

  return (
    <Card className="rounded-[20px] border-border/70 bg-card/90 shadow-[var(--shadow-sm)]">
      <CardContent className="flex h-full flex-col gap-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">{title}</p>
            <p className="text-xs text-muted-foreground">
              {presetLabel}
              <span className="ml-1 font-medium text-foreground">{presetName}</span>
            </p>
            {summaryPills.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {summaryPills.map((pill) => (
                  <span
                    key={pill}
                    className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-foreground"
                  >
                    {pill}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
              {total}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-full px-3"
              onClick={onViewDetails}
            >
              <Eye data-icon="inline-start" />
              {viewLabel}
            </Button>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {[firstGroup, secondGroup].filter(Boolean).map((group) => (
            <div key={group!.title} className="surface-subtle flex items-center justify-between gap-3 px-3 py-3">
              <div className="space-y-1">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {group!.title}
                </p>
                <p className="text-xs text-muted-foreground">
                  {group!.items.length > 0
                    ? `${group!.items.slice(0, 3).join(' · ')}${t('batchWizard.step1.summaryEtc')}`
                    : group!.emptyLabel}
                </p>
              </div>
              <span className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-foreground">
                {group!.items.length}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
