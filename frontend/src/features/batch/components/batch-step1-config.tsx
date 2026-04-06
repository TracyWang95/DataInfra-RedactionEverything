
import { Link } from 'react-router-dom';
import { useT } from '@/i18n';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
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
        <div className="surface-subtle flex flex-col gap-3 px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">{t('batchWizard.step1.execPath')}</p>
          <div className="flex flex-col gap-2 sm:flex-row sm:gap-4">
            <label className="surface-muted flex cursor-pointer items-center gap-2 px-3 py-3 text-sm">
              <input
                type="radio"
                name="batch-exec-path"
                className="h-3.5 w-3.5 accent-primary"
                checked={(cfg.executionDefault ?? 'queue') === 'queue'}
                onChange={() => setCfg(c => ({ ...c, executionDefault: 'queue' }))}
                data-testid="exec-queue"
              />
              <span>
                <span className="font-medium">{t('batchWizard.step1.execQueue')}</span>
                <span className="text-muted-foreground ml-1">
                  {t('batchWizard.step1.execQueueDesc')}
                </span>
              </span>
            </label>
            <label className="surface-muted flex cursor-pointer items-center gap-2 px-3 py-3 text-sm">
              <input
                type="radio"
                name="batch-exec-path"
                className="h-3.5 w-3.5 accent-primary"
                checked={cfg.executionDefault === 'local'}
                onChange={() => setCfg(c => ({ ...c, executionDefault: 'local' }))}
                data-testid="exec-local"
              />
              <span>
                <span className="font-medium">{t('batchWizard.step1.execLocal')}</span>
                <span className="text-muted-foreground ml-1">
                  {t('batchWizard.step1.execLocalDesc')}
                </span>
              </span>
            </label>
          </div>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          <Card className="rounded-[20px] border-border/70 bg-card/90 shadow-[var(--shadow-sm)]">
            <CardContent className="flex h-full flex-col gap-2 p-4">
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
            </CardContent>
          </Card>

          <Card className="rounded-[20px] border-border/70 bg-card/90 shadow-[var(--shadow-sm)]">
            <CardContent className="flex h-full flex-col gap-2 p-4">
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
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          <SelectionPreviewCard
            title={t('batchWizard.step1.textSummary')}
            presetName={textPresetName}
            presetLabel={t('batchWizard.step1.activePreset')}
            groups={[
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
            ]}
          />
          <SelectionPreviewCard
            title={t('batchWizard.step1.imageSummary')}
            presetName={visionPresetName}
            presetLabel={t('batchWizard.step1.activePreset')}
            groups={[
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
            ]}
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
    </Card>
  );
}

function SelectionPreviewCard({
  title,
  presetLabel,
  presetName,
  groups,
}: {
  title: string;
  presetLabel: string;
  presetName: string;
  groups: Array<{ title: string; items: string[]; emptyLabel: string }>;
}) {
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);

  return (
    <Card className="rounded-[20px] border-border/70 bg-card/90 shadow-[var(--shadow-sm)]">
      <CardContent className="flex h-full flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">{title}</p>
            <p className="text-xs text-muted-foreground">
              {presetLabel}
              <span className="ml-1 font-medium text-foreground">{presetName}</span>
            </p>
          </div>
          <span className="rounded-full border border-border/70 bg-muted/35 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
            {total}
          </span>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          {groups.map((group) => (
            <div key={group.title} className="surface-subtle flex min-h-[9.25rem] flex-col gap-2.5 px-3 py-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {group.title}
                </span>
                <span className="text-[11px] text-muted-foreground">{group.items.length}</span>
              </div>
              {group.items.length > 0 ? (
                <div className="max-h-28 overflow-y-auto pr-1">
                  <div className="flex flex-wrap gap-1.5">
                    {group.items.map((item) => (
                      <span
                        key={`${group.title}-${item}`}
                        className="rounded-full border border-border/70 bg-background px-2 py-1 text-[11px] leading-4 text-foreground"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="flex min-h-[4.75rem] items-center justify-center rounded-2xl border border-dashed border-border/70 bg-background/80 px-4 text-center text-xs text-muted-foreground">
                  {group.emptyLabel}
                </div>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
