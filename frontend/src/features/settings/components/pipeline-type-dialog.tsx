// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useId, useRef } from 'react';
import { Plus, Upload, X } from 'lucide-react';
import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
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
import type { PipelineMode } from '@/services/defaultRedactionPreset';
import {
  MAX_VisualFeature_SAMPLES,
  emptyPromptRow,
  localId,
  readImageAsDataUrl,
  type PipelineTypeForm,
  type SampleForm,
} from './pipeline-type-form';

interface PipelineTypeDialogProps {
  mode: PipelineMode | null;
  isEditing: boolean;
  form: PipelineTypeForm;
  setForm: React.Dispatch<React.SetStateAction<PipelineTypeForm>>;
  onClose: () => void;
  onSave: () => Promise<void>;
}

export function PipelineTypeDialog({
  mode,
  isEditing,
  form,
  setForm,
  onClose,
  onSave,
}: PipelineTypeDialogProps) {
  const t = useT();
  const sampleInputRef = useRef<HTMLInputElement>(null);
  const nameInputId = useId();
  const descriptionInputId = useId();

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

  const visualChecklistDialog = mode === 'visual_features';

  return (
    <Dialog
      open={mode !== null}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
    >
      <DialogContent className="sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{isEditing ? t('settings.editType') : t('settings.addType')}</DialogTitle>
          <DialogDescription>
            {mode === 'ocr_has'
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
                mode === 'ocr_has'
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
          <Button variant="outline" onClick={onClose} data-testid="pipeline-type-cancel">
            {t('settings.cancel')}
          </Button>
          <Button
            disabled={!form.name.trim()}
            onClick={() => void onSave()}
            data-testid="pipeline-type-save"
          >
            {isEditing ? t('settings.save') : t('settings.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
