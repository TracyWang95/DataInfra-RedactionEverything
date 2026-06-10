// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Plus, Upload, X } from 'lucide-react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PaginationRail } from '@/components/PaginationRail';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { getSelectionToneClasses, type SelectionTone } from '@/ui/selectionPalette';
import {
  getPipelineTone,
  getToneColor,
  type PipelineConfig,
  type PipelineTypeConfig,
  type VisualFeatureFewShotSample,
} from '../hooks/use-entity-types';
import type { PipelineMode } from '@/services/defaultRedactionPreset';

const RECOGNITION_PAGE_SIZE = 9;

type PromptRowForm = {
  id: string;
  text: string;
};

type SampleForm = {
  id: string;
  type: 'positive' | 'negative';
  image: string;
  label: string;
  filename?: string | null;
};

type PipelineTypeForm = {
  name: string;
  description: string;
  rulesText: string;
  positivePrompts: PromptRowForm[];
  negativePrompts: PromptRowForm[];
  samples: SampleForm[];
};

type SettingsPipelineTab = Extract<PipelineMode, 'ocr_has' | 'visual_features'>;
type DisplayPipelineType = PipelineTypeConfig & { pipelineMode: PipelineMode };
type DisplayPipeline = Omit<PipelineConfig, 'mode' | 'types'> & {
  mode: SettingsPipelineTab;
  types: DisplayPipelineType[];
};

const MAX_VisualFeature_SAMPLES = 5;

function localId() {
  return `local_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

function emptyPromptRow(text = ''): PromptRowForm {
  return {
    id: localId(),
    text,
  };
}

function emptyForm(): PipelineTypeForm {
  return {
    name: '',
    description: '',
    rulesText: '',
    positivePrompts: [emptyPromptRow()],
    negativePrompts: [emptyPromptRow()],
    samples: [],
  };
}

function positivePromptsFromType(type: PipelineTypeConfig): PromptRowForm[] {
  if (type.checklist?.length) {
    const rows = type.checklist
      .map((item) => item.rule ?? item.positive_prompt ?? '')
      .filter(Boolean)
      .map((text) => emptyPromptRow(text));
    if (rows.length) return rows;
  }

  const rows = (type.rules ?? []).filter(Boolean).map((rule) => emptyPromptRow(rule));
  return rows.length ? rows : [emptyPromptRow()];
}

function negativePromptsFromType(type: PipelineTypeConfig): PromptRowForm[] {
  const rowPrompts = (type.checklist ?? [])
    .map((item) => item.negative_prompt ?? '')
    .filter(Boolean);
  const legacyPrompts = (type.negative_prompt ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  const rows = [...rowPrompts, ...legacyPrompts].map((text) => emptyPromptRow(text));
  return rows.length ? rows : [emptyPromptRow()];
}

function samplesFromType(type: PipelineTypeConfig): SampleForm[] {
  return (type.few_shot_samples ?? []).map((sample) => ({
    id: localId(),
    type: sample.type === 'negative' ? 'negative' : 'positive',
    image: sample.image,
    label: sample.label ?? '',
    filename: sample.filename ?? null,
  }));
}

function readImageAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

interface PipelineConfigPanelProps {
  loading: boolean;
  pipelines: PipelineConfig[];
  onCreateType: (
    mode: PipelineMode,
    name: string,
    desc: string,
    options?: Pick<
      PipelineTypeConfig,
      | 'rules'
      | 'checklist'
      | 'negative_prompt_enabled'
      | 'negative_prompt'
      | 'few_shot_enabled'
      | 'few_shot_samples'
    >,
  ) => Promise<boolean>;
  onUpdateType: (
    mode: string,
    typeId: string,
    update: Partial<PipelineTypeConfig> & { name: string; description?: string },
  ) => Promise<boolean>;
  onDeleteType: (mode: string, typeId: string) => void;
  onReset: () => void;
}

export function PipelineConfigPanel({
  loading,
  pipelines,
  onCreateType,
  onUpdateType,
  onDeleteType,
  onReset,
}: PipelineConfigPanelProps) {
  const t = useT();
  const [activeSub, setActiveSub] = useState<SettingsPipelineTab>('ocr_has');
  const [dialogMode, setDialogMode] = useState<PipelineMode | null>(null);
  const [editing, setEditing] = useState<{ mode: string; type: PipelineTypeConfig } | null>(null);
  const [form, setForm] = useState<PipelineTypeForm>(() => emptyForm());
  const [page, setPage] = useState(1);
  const sampleInputRef = useRef<HTMLInputElement>(null);
  const nameInputId = useId();
  const descriptionInputId = useId();

  const ocrPipeline = pipelines.find((pipeline) => pipeline.mode === 'ocr_has');
  const visualPipeline = pipelines.find((pipeline) => pipeline.mode === 'visual_features');
  const ocrLabel = t('settings.pipelineDisplayName.ocr');
  const imageLabel = t('settings.pipelineDisplayName.image');
  const ocrDisplayPipeline = useMemo<DisplayPipeline | undefined>(() => {
    if (!ocrPipeline) return undefined;
    return {
      ...ocrPipeline,
      mode: 'ocr_has',
      types: ocrPipeline.types.map((type) => ({ ...type, pipelineMode: 'ocr_has' })),
    };
  }, [ocrPipeline]);
  const visualDisplayPipeline = useMemo<DisplayPipeline | undefined>(() => {
    if (!visualPipeline) return undefined;
    return {
      ...visualPipeline,
      mode: 'visual_features',
      name: imageLabel,
      description: visualPipeline.description ?? '',
      enabled: Boolean(visualPipeline.enabled),
      types: visualPipeline.types.map((type) => ({
        ...type,
        pipelineMode: 'visual_features' as PipelineMode,
      })),
    };
  }, [imageLabel, visualPipeline]);
  const activePipeline = activeSub === 'visual_features' ? visualDisplayPipeline : ocrDisplayPipeline;

  const openCreate = (mode: PipelineMode) => {
    setEditing(null);
    setForm(emptyForm());
    setDialogMode(mode);
  };

  const openEdit = (mode: string, type: PipelineTypeConfig) => {
    setEditing({ mode, type: { ...type } });
    setForm({
      name: type.name,
      description: type.description ?? '',
      rulesText: (type.rules ?? []).join('\n'),
      positivePrompts: positivePromptsFromType(type),
      negativePrompts: negativePromptsFromType(type),
      samples: samplesFromType(type),
    });
    setDialogMode(mode as PipelineMode);
  };

  const handleSave = async () => {
    if (!dialogMode || !form.name.trim()) return;

    const useVisualChecklist = dialogMode === 'visual_features';
    const positiveRows =
      useVisualChecklist
        ? form.positivePrompts
        : form.rulesText.split('\n').map((line) => emptyPromptRow(line));
    const checklist = positiveRows
      .map((item) => item.text.trim())
      .filter(Boolean)
      .map((rule) => ({
        rule,
        positive_prompt: null,
        negative_prompt: null,
      }));
    const rules = checklist.map((item) => item.rule);
    const negativePrompt = form.negativePrompts
      .map((item) => item.text.trim())
      .filter(Boolean)
      .join('\n');
    const samples: VisualFeatureFewShotSample[] = form.samples.map((sample) => ({
      type: sample.type,
      image: sample.image,
      label: sample.label.trim() || null,
      filename: sample.filename ?? null,
    }));
    let ok: boolean;
    if (editing) {
      ok = await onUpdateType(editing.mode, editing.type.id, {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        examples: editing.type.examples || [],
        color: getToneColor(getPipelineTone(editing.mode as PipelineMode)),
        enabled: editing.type.enabled,
        order: editing.type.order,
        rules,
        checklist,
        negative_prompt_enabled: negativePrompt.length > 0,
        negative_prompt: negativePrompt || null,
        few_shot_enabled: samples.length > 0,
        few_shot_samples: samples,
      });
    } else {
      ok = await onCreateType(dialogMode, form.name, form.description, {
        rules,
        checklist,
        negative_prompt_enabled: negativePrompt.length > 0,
        negative_prompt: negativePrompt || null,
        few_shot_enabled: samples.length > 0,
        few_shot_samples: samples,
      });
    }
    if (!ok) return;

    setDialogMode(null);
    setEditing(null);
    setForm(emptyForm());
  };

  const updatePromptRow = (
    group: 'positivePrompts' | 'negativePrompts',
    rowId: string,
    text: string,
  ) => {
    setForm((current) => ({
      ...current,
      [group]: current[group].map((row) => (row.id === rowId ? { ...row, text } : row)),
    }));
  };

  const addPromptRow = (group: 'positivePrompts' | 'negativePrompts') => {
    setForm((current) => ({
      ...current,
      [group]: [...current[group], emptyPromptRow()],
    }));
  };

  const removePromptRow = (group: 'positivePrompts' | 'negativePrompts', rowId: string) => {
    setForm((current) => {
      const nextRows = current[group].filter((row) => row.id !== rowId);
      return { ...current, [group]: nextRows.length ? nextRows : [emptyPromptRow()] };
    });
  };

  const handleSampleUpload = async (files: FileList | null) => {
    if (!files?.length) return;
    const remaining = Math.max(0, MAX_VisualFeature_SAMPLES - form.samples.length);
    const selectedFiles = Array.from(files)
      .filter((file) => file.type.startsWith('image/'))
      .slice(0, remaining);
    if (selectedFiles.length === 0) return;
    const nextSamples = await Promise.all(
      selectedFiles.map(async (file) => ({
        id: localId(),
        type: 'positive' as const,
        image: await readImageAsDataUrl(file),
        label: '',
        filename: file.name,
      })),
    );
    setForm((current) => ({
      ...current,
      samples: [...current.samples, ...nextSamples].slice(0, MAX_VisualFeature_SAMPLES),
    }));
    if (sampleInputRef.current) sampleInputRef.current.value = '';
  };

  const updateSample = (sampleId: string, patch: Partial<Omit<SampleForm, 'id'>>) => {
    setForm((current) => ({
      ...current,
      samples: current.samples.map((sample) =>
        sample.id === sampleId ? { ...sample, ...patch } : sample,
      ),
    }));
  };

  const removeSample = (sampleId: string) => {
    setForm((current) => ({
      ...current,
      samples: current.samples.filter((sample) => sample.id !== sampleId),
    }));
  };

  const imageModeActive = activeSub === 'visual_features';
  const tone: SelectionTone = imageModeActive ? 'visual' : 'semantic';
  const toneClasses = getSelectionToneClasses(tone);
  const displayName = imageModeActive ? imageLabel : ocrLabel;
  const activeCount = activePipeline?.types.length ?? 0;
  const totalPages = Math.max(1, Math.ceil(activeCount / RECOGNITION_PAGE_SIZE));
  const visualChecklistDialog = dialogMode === 'visual_features';

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting pagination when active tab changes
    setPage(1);
  }, [activeSub]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clamping page to valid range when total changes
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  const visibleTypes = useMemo(() => {
    if (!activePipeline) return [];
    const start = (page - 1) * RECOGNITION_PAGE_SIZE;
    return activePipeline.types.slice(start, start + RECOGNITION_PAGE_SIZE);
  }, [activePipeline, page]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-hidden">
      <div className="flex shrink-0 items-center gap-2">
        <Tabs value={activeSub} onValueChange={(value) => setActiveSub(value as SettingsPipelineTab)}>
          <TabsList className="rounded-xl border border-border/70 bg-muted/40 p-1">
            <TabsTrigger
              value="ocr_has"
              className="whitespace-nowrap"
              data-testid="pipeline-tab-ocr"
            >
              {ocrLabel}
              <span className="ml-1 text-muted-foreground">({ocrPipeline?.types.length ?? 0})</span>
            </TabsTrigger>
            <TabsTrigger
              value="visual_features"
              className="whitespace-nowrap"
              data-testid="pipeline-tab-image"
            >
              {imageLabel}
              <span className="ml-1 text-muted-foreground">
                ({visualDisplayPipeline?.types.length ?? 0})
              </span>
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div
        className="page-surface rounded-[20px] border border-border/70 bg-card shadow-[var(--shadow-control)]"
        data-testid="vision-pipeline-panel"
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border/70 bg-muted/20 px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-2">
            <span className={cn('size-2 shrink-0 rounded-full', toneClasses.dot)} />
            <span className="truncate text-sm font-semibold tracking-normal">{displayName}</span>
            <Badge
              variant="secondary"
              className={cn(
                'border border-border/70 bg-background text-xs shadow-sm',
                toneClasses.badgeText,
              )}
            >
              {activeCount}
            </Badge>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="h-8 whitespace-nowrap"
              onClick={onReset}
              data-testid="reset-pipelines"
            >
              {t('settings.resetVisionRules')}
            </Button>
            <Button
              size="sm"
              className="h-8 whitespace-nowrap"
              onClick={() => openCreate(activeSub)}
              data-testid="add-pipeline-type"
            >
              {t('settings.addNew')}
            </Button>
          </div>
        </div>

        <div className="page-surface-body flex overflow-hidden p-3">
          {loading ? (
            <div className="flex min-h-[240px] flex-1 items-center justify-center rounded-[20px] border border-dashed border-border/70 bg-muted/15 px-6 text-center">
              <p className="text-sm text-muted-foreground">{t('settings.loadingPipeline')}</p>
            </div>
          ) : !activePipeline || activePipeline.types.length === 0 ? (
            <div className="flex min-h-[240px] flex-1 items-center justify-center rounded-[20px] border border-dashed border-border/70 bg-muted/15 px-6 text-center">
              <p className="text-sm text-muted-foreground">{t('settings.noTypeConfig')}</p>
            </div>
          ) : (
            <div className="grid h-full min-h-0 w-full flex-1 grid-cols-1 grid-rows-3 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {visibleTypes.map((type) => (
                <article
                  key={`${type.pipelineMode}-${type.id}`}
                  className="flex h-full min-h-0 overflow-hidden rounded-[20px] border border-border/70 bg-[var(--surface-control)] px-3.5 py-3.5 shadow-[var(--shadow-sm)] transition-colors hover:border-border"
                >
                  <div className="flex min-w-0 flex-1 flex-col gap-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <span className="line-clamp-2 text-sm font-semibold leading-5 text-foreground">
                          {type.name}
                        </span>
                      </div>
                      <div className="flex shrink-0 items-center gap-0.5">
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6"
                          onClick={() => openEdit(type.pipelineMode, type)}
                          aria-label={t('common.edit')}
                          data-testid={`edit-pipeline-${type.id}`}
                        >
                          <PencilIcon />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-6 text-destructive hover:text-destructive"
                          onClick={() => onDeleteType(type.pipelineMode, type.id)}
                          aria-label={t('common.delete')}
                          data-testid={`delete-pipeline-${type.id}`}
                        >
                          <TrashIcon />
                        </Button>
                      </div>
                    </div>

                    <div className="min-h-0 flex-1 rounded-xl border border-border/70 bg-muted/25 px-3 py-2.5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {t('settings.cardDescriptionLabel')}
                      </p>
                      <p className="mt-1 line-clamp-4 text-xs leading-4 text-foreground">
                        {type.description || t('settings.semanticDescriptionPlaceholder')}
                      </p>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        {activeCount > 0 && (
          <div className="page-surface-footer">
            <PaginationRail
              page={page}
              pageSize={RECOGNITION_PAGE_SIZE}
              totalItems={activeCount}
              totalPages={totalPages}
              onPageChange={setPage}
              compact
            />
          </div>
        )}
      </div>

      <Dialog
        open={dialogMode !== null}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setDialogMode(null);
            setEditing(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle>{editing ? t('settings.editType') : t('settings.addType')}</DialogTitle>
            <DialogDescription>
              {dialogMode === 'ocr_has'
                ? t('settings.pipelineTypeDescOcr')
                : t('settings.pipelineTypeDescImg')}
            </DialogDescription>
          </DialogHeader>

          <div className="flex max-h-[72vh] flex-col gap-4 overflow-y-auto py-2 pr-1">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={nameInputId}>{t('settings.nameLabel')} *</Label>
              <Input
                id={nameInputId}
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, name: event.target.value }))
                }
                placeholder={
                  dialogMode === 'ocr_has'
                    ? t('settings.pipelineNamePlaceholder.ocr')
                    : t('settings.pipelineNamePlaceholder.image')
                }
                data-testid="pipeline-type-name"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor={descriptionInputId}>{t('settings.descLabel')}</Label>
              <Textarea
                id={descriptionInputId}
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({ ...current, description: event.target.value }))
                }
                rows={3}
                data-testid="pipeline-type-desc"
              />
            </div>

            <p className="text-xs text-muted-foreground">{t('settings.saveHint')}</p>
            {visualChecklistDialog && (
              <>
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-3">
                    <Label>{t('settings.visualFeaturePositivePromptsLabel')}</Label>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-8 gap-1.5 whitespace-nowrap"
                      onClick={() => addPromptRow('positivePrompts')}
                      data-testid="pipeline-add-positive-row"
                    >
                      <Plus className="size-3.5" />
                      {t('settings.visualFeaturePromptAdd')}
                    </Button>
                  </div>
                  <div className="grid gap-2" data-testid="pipeline-type-positive-prompts">
                    {form.positivePrompts.map((row, index) => (
                      <div
                        key={row.id}
                        className="grid gap-2 rounded-xl border border-border/70 bg-muted/15 p-2 md:grid-cols-[minmax(0,1fr)_2rem]"
                      >
                        <Input
                          value={row.text}
                          onChange={(event) =>
                            updatePromptRow('positivePrompts', row.id, event.target.value)
                          }
                          placeholder={t('settings.visualFeaturePositivePromptPlaceholder')}
                          aria-label={`${t('settings.visualFeaturePositivePrompt')} ${index + 1}`}
                          data-testid={`pipeline-positive-prompt-${index}`}
                        />
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="size-8 self-start text-muted-foreground hover:text-destructive"
                          onClick={() => removePromptRow('positivePrompts', row.id)}
                          aria-label={t('settings.visualFeaturePromptRemove')}
                        >
                          <X className="size-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-3">
                    <Label>{t('settings.visualFeatureNegativePromptsLabel')}</Label>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-8 gap-1.5 whitespace-nowrap"
                      onClick={() => addPromptRow('negativePrompts')}
                      data-testid="pipeline-add-negative-row"
                    >
                      <Plus className="size-3.5" />
                      {t('settings.visualFeaturePromptAdd')}
                    </Button>
                  </div>
                  <div className="grid gap-2" data-testid="pipeline-type-negative-prompts">
                    {form.negativePrompts.map((row, index) => (
                      <div
                        key={row.id}
                        className="grid gap-2 rounded-xl border border-border/70 bg-muted/15 p-2 md:grid-cols-[minmax(0,1fr)_2rem]"
                      >
                        <Input
                          value={row.text}
                          onChange={(event) =>
                            updatePromptRow('negativePrompts', row.id, event.target.value)
                          }
                          placeholder={t('settings.visualFeatureNegativePromptPlaceholder')}
                          aria-label={`${t('settings.visualFeatureNegativePrompt')} ${index + 1}`}
                          data-testid={`pipeline-negative-prompt-${index}`}
                        />
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className="size-8 self-start text-muted-foreground hover:text-destructive"
                          onClick={() => removePromptRow('negativePrompts', row.id)}
                          aria-label={t('settings.visualFeaturePromptRemove')}
                        >
                          <X className="size-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                      <Label>{t('settings.visualFeatureSamplesLabel')}</Label>
                      <p className="text-xs text-muted-foreground">
                        {t('settings.visualFeatureSamplesHint')}
                      </p>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-8 gap-1.5 whitespace-nowrap"
                      onClick={() => sampleInputRef.current?.click()}
                      disabled={form.samples.length >= MAX_VisualFeature_SAMPLES}
                      data-testid="pipeline-upload-sample"
                    >
                      <Upload className="size-3.5" />
                      {t('settings.visualFeatureSamplesUpload')}
                    </Button>
                    <input
                      ref={sampleInputRef}
                      type="file"
                      accept="image/*"
                      multiple
                      className="hidden"
                      onChange={(event) => void handleSampleUpload(event.target.files)}
                    />
                  </div>
                  {form.samples.length > 0 && (
                    <div className="grid gap-2 sm:grid-cols-2" data-testid="pipeline-sample-list">
                      {form.samples.map((sample) => (
                        <div
                          key={sample.id}
                          className="grid grid-cols-[4.5rem_minmax(0,1fr)_2rem] gap-2 rounded-xl border border-border/70 bg-muted/15 p-2"
                        >
                          <img
                            src={sample.image}
                            alt={sample.filename || t('settings.visualFeatureSampleAlt')}
                            className="h-[4.5rem] w-[4.5rem] rounded-lg border border-border/70 object-cover"
                          />
                          <div className="grid min-w-0 gap-2">
                            <Select
                              value={sample.type}
                              onValueChange={(value) =>
                                updateSample(sample.id, {
                                  type: value === 'negative' ? 'negative' : 'positive',
                                })
                              }
                            >
                              <SelectTrigger className="h-8 text-xs">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="positive">
                                  {t('settings.visualFeatureSamplePositive')}
                                </SelectItem>
                                <SelectItem value="negative">
                                  {t('settings.visualFeatureSampleNegative')}
                                </SelectItem>
                              </SelectContent>
                            </Select>
                            <Input
                              value={sample.label}
                              onChange={(event) =>
                                updateSample(sample.id, { label: event.target.value })
                              }
                              placeholder={t('settings.visualFeatureSampleLabelPlaceholder')}
                              className="h-8 text-xs"
                            />
                          </div>
                          <Button
                            type="button"
                            size="icon"
                            variant="ghost"
                            className="size-8 text-muted-foreground hover:text-destructive"
                            onClick={() => removeSample(sample.id)}
                            aria-label={t('settings.visualFeatureSampleRemove')}
                          >
                            <X className="size-4" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setDialogMode(null);
                setEditing(null);
              }}
              data-testid="pipeline-type-cancel"
            >
              {t('settings.cancel')}
            </Button>
            <Button
              disabled={!form.name.trim()}
              onClick={() => void handleSave()}
              data-testid="pipeline-type-save"
            >
              {editing ? t('settings.save') : t('settings.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PencilIcon() {
  return (
    <svg className="size-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="size-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
      />
    </svg>
  );
}
