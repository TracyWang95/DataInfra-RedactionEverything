// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useMemo, useState } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PaginationRail } from '@/components/PaginationRail';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { getSelectionToneClasses, type SelectionTone } from '@/ui/selectionPalette';
import {
  getPipelineTone,
  getToneColor,
  type PipelineConfig,
  type PipelineTypeConfig,
  type VisualFeatureFewShotSample,
} from '../hooks/use-entity-types';
import type { PipelineMode } from '@/services/defaultRedactionPreset';
import {
  emptyForm,
  emptyPromptRow,
  negativePromptsFromType,
  positivePromptsFromType,
  samplesFromType,
  type PipelineTypeForm,
} from './pipeline-type-form';
import { PipelineTypeCard } from './pipeline-type-card';
import { PipelineTypeDialog } from './pipeline-type-dialog';

const RECOGNITION_PAGE_SIZE = 9;

type SettingsPipelineTab = Extract<PipelineMode, 'ocr_has' | 'visual_features'>;
type DisplayPipelineType = PipelineTypeConfig & { pipelineMode: PipelineMode };
type DisplayPipeline = Omit<PipelineConfig, 'mode' | 'types'> & {
  mode: SettingsPipelineTab;
  types: DisplayPipelineType[];
};

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

  const imageModeActive = activeSub === 'visual_features';
  const tone: SelectionTone = imageModeActive ? 'visual' : 'semantic';
  const toneClasses = getSelectionToneClasses(tone);
  const displayName = imageModeActive ? imageLabel : ocrLabel;
  const activeCount = activePipeline?.types.length ?? 0;
  const totalPages = Math.max(1, Math.ceil(activeCount / RECOGNITION_PAGE_SIZE));

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
                <PipelineTypeCard
                  key={`${type.pipelineMode}-${type.id}`}
                  type={type}
                  onEdit={() => openEdit(type.pipelineMode, type)}
                  onDelete={() => onDeleteType(type.pipelineMode, type.id)}
                />
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

      <PipelineTypeDialog
        mode={dialogMode}
        isEditing={editing !== null}
        form={form}
        setForm={setForm}
        onClose={() => {
          setDialogMode(null);
          setEditing(null);
        }}
        onSave={handleSave}
      />
    </div>
  );
}
