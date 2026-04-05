/**
 * BatchStep1Config — Step 1: Task configuration.
 * Handles execution path, text/vision preset selection,
 * priority, and confirmation before advancing to upload.
 */
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

const DEFAULT_PRESET_VALUE = '__default__';

interface BatchStep1ConfigProps {
  cfg: BatchWizardPersistedConfig;
  setCfg: React.Dispatch<React.SetStateAction<BatchWizardPersistedConfig>>;
  configLoaded: boolean;
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

  if (!configLoaded) {
    return (
      <Card data-testid="batch-step1-loading">
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
      className="flex flex-col flex-1 min-h-0 overflow-hidden"
      data-testid="batch-step1-config"
    >
      <CardHeader className="pb-2 space-y-1">
        <CardTitle className="text-sm">{t('batchWizard.step1.title')}</CardTitle>
        <p className="text-xs text-muted-foreground leading-snug">
          {t('batchWizard.step1.desc')}
        </p>
      </CardHeader>

      <CardContent className="flex-1 min-h-0 overflow-y-auto space-y-4 pt-0">
        {/* Execution path */}
        <div className="rounded-lg border bg-muted/30 px-3 py-2.5 space-y-2">
          <p className="text-xs font-medium">{t('batchWizard.step1.execPath')}</p>
          <div className="flex flex-col gap-2 sm:flex-row sm:gap-4">
            <label className="flex items-center gap-2 cursor-pointer text-xs">
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
            <label className="flex items-center gap-2 cursor-pointer text-xs">
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

        {/* Preset cards */}
        <div className="flex gap-3 flex-1 min-h-0">
          <div className="w-[280px] shrink-0 flex flex-col gap-3 overflow-y-auto">
            {/* Text preset */}
            <Card>
              <CardContent className="p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  <span className="text-xs font-semibold">
                    {t('batchWizard.step1.textPreset')}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
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

            {/* Vision preset */}
            <Card>
              <CardContent className="p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--selection-yolo-accent)]" />
                  <span className="text-xs font-semibold">
                    {t('batchWizard.step1.imagePreset')}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
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

            {/* Priority */}
            <div className="flex items-center gap-2 px-1">
              <span className="text-xs text-muted-foreground">
                {t('batchWizard.step1.priority')}
              </span>
              <Select
                value={String(jobPriority)}
                onValueChange={v => setJobPriority(Number(v))}
              >
                <SelectTrigger className="text-xs w-24" data-testid="priority-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">{t('batchWizard.step1.priorityNormal')}</SelectItem>
                  <SelectItem value="5">{t('batchWizard.step1.priorityHigh')}</SelectItem>
                  <SelectItem value="10">{t('batchWizard.step1.priorityUrgent')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Confirm + advance */}
            <div className="space-y-3 pt-2 border-t">
              <label className="flex items-start gap-2 cursor-pointer text-xs">
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
        </div>

        {/* Links */}
        <p className="text-xs text-muted-foreground">
          <Link to="/jobs" className="text-primary hover:underline font-medium">
            {t('batchHub.jobCenter')}
          </Link>
          <span className="mx-1">&middot;</span>
          <Link to="/history" className="text-primary hover:underline font-medium">
            {t('batchHub.history')}
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
