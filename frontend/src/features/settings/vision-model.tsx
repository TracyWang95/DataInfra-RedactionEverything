// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useMemo, useState } from 'react';
import { CheckCircle2, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { InteractionLockOverlay } from '@/components/InteractionLockOverlay';
import {
  BUILTIN_MODEL_IDS,
  type ModelConfig,
  type ModelTaskType,
  useVisionModelConfig,
} from './hooks/use-model-config';
import { useVisionModelForm } from './use-vision-model-form';
import { tonePanelClass } from '@/utils/toneClasses';
import { VisionModelDialog } from './vision-model-dialog';
import { VisionModelTestResult } from './vision-model-test-result';

const TASKS: Array<{
  id: ModelTaskType;
  titleKey: string;
  descKey: string;
}> = [
  {
    id: 'text_ner',
    titleKey: 'settings.modelConfig.task.text_ner',
    descKey: 'settings.modelConfig.taskDesc.text_ner',
  },
  {
    id: 'ocr',
    titleKey: 'settings.modelConfig.task.ocr',
    descKey: 'settings.modelConfig.taskDesc.ocr',
  },
  {
    id: 'visual_feature',
    titleKey: 'settings.modelConfig.task.visual_feature',
    descKey: 'settings.modelConfig.taskDesc.visual_feature',
  },
];

export function VisionModel() {
  const t = useT();
  const {
    modelConfigs,
    presets,
    loading,
    builtinLive,
    testingModelId,
    testResult,
    saveModelConfig,
    deleteModelConfig,
    testModelConfig,
    resetModelConfigs,
    applyPreset,
    setActiveModelConfig,
    settingActiveModelId,
    liveForBuiltin,
    getProviderLabel,
  } = useVisionModelConfig();

  const {
    showModal,
    editingId,
    form,
    confirmState,
    openAdd,
    openEdit,
    handleSave,
    closeModal,
    updateForm,
    requestConfirm,
    cancelConfirm,
  } = useVisionModelForm(saveModelConfig);
  const [operationLoading, setOperationLoading] = useState(false);
  const [applyingPresetId, setApplyingPresetId] = useState<string | null>(null);

  const configsByTask = useMemo(() => {
    const groups: Record<ModelTaskType, ModelConfig[]> = {
      text_ner: [],
      ocr: [],
      visual_feature: [],
    };
    for (const config of modelConfigs.configs) {
      groups[config.task_type ?? 'visual_feature'].push(config);
    }
    return groups;
  }, [modelConfigs.configs]);

  const runLocked = async (action: () => void | Promise<void>) => {
    if (operationLoading) return;
    setOperationLoading(true);
    try {
      await action();
    } finally {
      setOperationLoading(false);
    }
  };

  const activeIdFor = (taskType: ModelTaskType) =>
    modelConfigs.active_by_task?.[taskType] ??
    (taskType === 'visual_feature' ? modelConfigs.active_id : undefined);

  const handleApplyPreset = async (presetId: string) => {
    setApplyingPresetId(presetId);
    try {
      await applyPreset(presetId);
    } finally {
      setApplyingPresetId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-muted border-t-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
        <div className="page-stack gap-3">
          <section className="surface-subtle flex shrink-0 flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight text-foreground">
                {t('settings.modelConfig.title')}
              </h1>
              <p className="mt-0.5 max-w-5xl text-xs leading-5 text-muted-foreground">
                {t('settings.modelConfig.infoDesc')}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-1.5">
              <Badge variant="outline" className="whitespace-nowrap">
                {t('settings.visionModel.tag.local')}
              </Badge>
              <Badge variant="outline" className="whitespace-nowrap">
                {t('settings.visionModel.tag.openai')}
              </Badge>
              <Badge variant="outline" className="whitespace-nowrap">
                {t('settings.visionModel.tag.custom')}
              </Badge>
            </div>
          </section>

          <Card className="overflow-hidden border-border/70 shadow-[var(--shadow-control)]">
            <CardHeader className="px-4 pb-2 pt-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-1">
                  <CardTitle className="text-base">
                    {t('settings.modelConfig.presetsTitle')}
                  </CardTitle>
                  <CardDescription className="text-xs leading-5">
                    {t('settings.modelConfig.presetsDesc')}
                  </CardDescription>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 whitespace-nowrap"
                  onClick={() =>
                    requestConfirm({
                      title: t('settings.visionModel.reset'),
                      message: t('settings.visionModel.confirmReset'),
                      danger: true,
                      onConfirm: () => resetModelConfigs(),
                    })
                  }
                  data-testid="reset-model-configs"
                >
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                  {t('settings.visionModel.reset')}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="grid gap-2 px-4 pb-4 pt-0 lg:grid-cols-3">
              {presets.map((preset) => {
                const active = modelConfigs.preset_id === preset.id;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    className={cn(
                      'min-h-[104px] rounded-lg border border-border/70 bg-background p-3 text-left shadow-[var(--shadow-control)] transition hover:border-primary/50',
                      active && 'border-primary/60 bg-primary/5',
                    )}
                    disabled={applyingPresetId === preset.id || operationLoading}
                    onClick={() => void handleApplyPreset(preset.id)}
                    data-testid={`apply-model-preset-${preset.id}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-sm font-semibold text-foreground">{preset.name}</span>
                      {active && <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden="true" />}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                      {preset.description}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {preset.recommended_chips.slice(0, 2).map((chip) => (
                        <Badge key={chip} variant="outline" className="whitespace-nowrap text-[10px]">
                          {chip}
                        </Badge>
                      ))}
                    </div>
                  </button>
                );
              })}
            </CardContent>
          </Card>

          <div className="grid min-h-0 gap-3 xl:grid-cols-3">
            {TASKS.map((task) => (
              <ModelTaskPanel
                key={task.id}
                taskType={task.id}
                title={t(task.titleKey)}
                description={t(task.descKey)}
                configs={configsByTask[task.id]}
                activeId={activeIdFor(task.id)}
                builtinLive={builtinLive}
                testingModelId={testingModelId}
                settingActiveModelId={settingActiveModelId}
                getProviderLabel={getProviderLabel}
                liveForBuiltin={liveForBuiltin}
                onAdd={() => openAdd(task.id)}
                onEdit={openEdit}
                onTest={testModelConfig}
                onSetActive={(config) => void setActiveModelConfig(config.id, task.id)}
                onDelete={(config) =>
                  requestConfirm({
                    title: t('common.delete'),
                    message: t('settings.visionModel.confirmDelete'),
                    danger: true,
                    onConfirm: () => deleteModelConfig(config.id),
                  })
                }
              />
            ))}
          </div>

          {testResult && <VisionModelTestResult testResult={testResult} />}
        </div>
      </div>

      <VisionModelDialog
        open={showModal}
        editingId={editingId}
        form={form}
        onClose={closeModal}
        onSave={() => void handleSave()}
        onUpdateForm={updateForm}
      />
      {confirmState && (
        <ConfirmDialog
          open
          title={confirmState.title}
          message={confirmState.message}
          danger={confirmState.danger}
          onConfirm={() =>
            void runLocked(async () => {
              const action = confirmState.onConfirm;
              cancelConfirm();
              await action();
            })
          }
          onCancel={cancelConfirm}
        />
      )}
      <InteractionLockOverlay
        active={
          operationLoading ||
          Boolean(testingModelId) ||
          Boolean(settingActiveModelId) ||
          Boolean(showModal) ||
          Boolean(applyingPresetId)
        }
      />
    </div>
  );
}

function ModelTaskPanel({
  taskType,
  title,
  description,
  configs,
  activeId,
  builtinLive,
  testingModelId,
  settingActiveModelId,
  getProviderLabel,
  liveForBuiltin,
  onAdd,
  onEdit,
  onTest,
  onSetActive,
  onDelete,
}: {
  taskType: ModelTaskType;
  title: string;
  description: string;
  configs: ModelConfig[];
  activeId?: string;
  builtinLive: unknown;
  testingModelId: string | null;
  settingActiveModelId: string | null;
  getProviderLabel: (provider: string) => string;
  liveForBuiltin: (configId: string) => 'online' | 'offline' | undefined;
  onAdd: () => void;
  onEdit: (config: ModelConfig) => void;
  onTest: (configId: string) => void;
  onSetActive: (config: ModelConfig) => void;
  onDelete: (config: ModelConfig) => void;
}) {
  const t = useT();

  return (
    <Card className="min-h-0 overflow-hidden border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 pb-2 pt-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <CardTitle className="text-base">{title}</CardTitle>
            <CardDescription className="text-xs leading-5">{description}</CardDescription>
          </div>
          <Button size="sm" className="h-8 shrink-0 whitespace-nowrap" onClick={onAdd}>
            <Plus className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
            {t('settings.visionModel.add')}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y divide-border/70">
          {configs.map((config) => {
            const isActive = activeId === config.id;
            const canSetActive = config.enabled && !isActive;
            const builtin = BUILTIN_MODEL_IDS.has(config.id);
            const live = liveForBuiltin(config.id);

            return (
              <div key={config.id} className="px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="truncate text-sm font-medium">{config.name}</span>
                      {isActive && (
                        <Badge className={`whitespace-nowrap ${tonePanelClass.success}`}>
                          {t('settings.visionModel.active')}
                        </Badge>
                      )}
                      <Badge
                        variant={config.enabled ? 'secondary' : 'outline'}
                        className="whitespace-nowrap"
                      >
                        {config.enabled ? t('common.enabled') : t('common.disabled')}
                      </Badge>
                      {builtin &&
                        (live === 'online' ? (
                          <Badge className={`whitespace-nowrap ${tonePanelClass.success}`}>
                            {t('common.online')}
                          </Badge>
                        ) : live === 'offline' ? (
                          <Badge variant="destructive" className="whitespace-nowrap">
                            {t('common.offline')}
                          </Badge>
                        ) : builtinLive === null ? (
                          <Badge variant="outline" className="whitespace-nowrap">
                            {t('common.checking')}
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="whitespace-nowrap">
                            {t('common.unknown')}
                          </Badge>
                        ))}
                    </div>
                    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      <Badge variant="outline" className="whitespace-nowrap">
                        {getProviderLabel(config.provider)}
                      </Badge>
                      <span className="text-border">/</span>
                      <span className="truncate font-mono">{config.model_name}</span>
                    </div>
                    {config.base_url && (
                      <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                        {config.base_url}
                      </p>
                    )}
                    {config.description && (
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                        {config.description}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-col gap-1.5">
                    <Button
                      size="sm"
                      variant={isActive ? 'secondary' : 'outline'}
                      className="h-8 min-w-20 whitespace-nowrap px-2.5"
                      disabled={!canSetActive || settingActiveModelId === config.id}
                      onClick={() => onSetActive(config)}
                      data-testid={`set-active-model-${taskType}-${config.id}`}
                    >
                      {settingActiveModelId === config.id
                        ? t('settings.visionModel.settingActive')
                        : isActive
                          ? t('settings.visionModel.active')
                          : t('settings.visionModel.setActive')}
                    </Button>
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8 whitespace-nowrap px-2.5"
                        disabled={testingModelId === config.id}
                        onClick={() => onTest(config.id)}
                        data-testid={`test-model-${config.id}`}
                      >
                        {testingModelId === config.id ? t('common.testing') : t('common.test')}
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8"
                        onClick={() => onEdit(config)}
                        data-testid={`edit-model-${config.id}`}
                        aria-label={t('common.edit')}
                      >
                        <Pencil aria-hidden="true" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        disabled={builtin}
                        className={cn('h-8 w-8', builtin && 'cursor-not-allowed opacity-20')}
                        onClick={() => onDelete(config)}
                        aria-label={t('common.delete')}
                        data-testid={`delete-model-${config.id}`}
                      >
                        <Trash2 aria-hidden="true" />
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}

          {configs.length === 0 && (
            <p className="px-4 py-5 text-center text-sm text-muted-foreground">
              {t('settings.visionModel.empty')}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
