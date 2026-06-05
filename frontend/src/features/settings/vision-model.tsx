// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { useState } from 'react';
import { cn } from '@/lib/utils';
import { Pencil, Trash2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { InteractionLockOverlay } from '@/components/InteractionLockOverlay';
import { BUILTIN_VISION_IDS, useVisionModelConfig } from './hooks/use-model-config';
import { useVisionModelForm } from './use-vision-model-form';
import { tonePanelClass } from '@/utils/toneClasses';
import { VisionModelDialog } from './vision-model-dialog';
import { VisionModelTestResult } from './vision-model-test-result';

export function VisionModel() {
  const t = useT();
  const {
    modelConfigs,
    loading,
    builtinLive,
    testingModelId,
    testResult,
    saveModelConfig,
    deleteModelConfig,
    testModelConfig,
    resetModelConfigs,
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

  const runLocked = async (action: () => void | Promise<void>) => {
    if (operationLoading) return;
    setOperationLoading(true);
    try {
      await action();
    } finally {
      setOperationLoading(false);
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
        <div className="page-stack gap-2.5">
          <section className="surface-subtle flex shrink-0 flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h1 className="text-base font-semibold tracking-normal">{t('nav.visionModel')}</h1>
              <p className="mt-0.5 max-w-5xl text-xs leading-5 text-muted-foreground">
                {t('settings.visionModel.infoDesc')}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-1.5">
              <Badge variant="outline" className="whitespace-nowrap text-[10px] leading-4">
                {t('settings.visionModel.tag.local')}
              </Badge>
              <Badge variant="outline" className="whitespace-nowrap text-[10px] leading-4">
                {t('settings.visionModel.tag.openai')}
              </Badge>
              <Badge variant="outline" className="whitespace-nowrap text-[10px] leading-4">
                {t('settings.visionModel.tag.custom')}
              </Badge>
            </div>
          </section>

          <Card className="min-h-0 overflow-hidden rounded-2xl border-border/70 shadow-[var(--shadow-control)]">
            <CardHeader className="px-4 pb-2 pt-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-1">
                  <CardTitle className="text-base">{t('settings.visionModel.listTitle')}</CardTitle>
                  <CardDescription className="text-xs leading-5">
                    {t('settings.visionModel.listDesc')}
                  </CardDescription>
                </div>
                <div className="flex shrink-0 flex-wrap justify-end gap-2">
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
                    data-testid="reset-vision-models"
                  >
                    {t('settings.visionModel.reset')}
                  </Button>
                  <Button
                    size="sm"
                    className="h-8 whitespace-nowrap"
                    onClick={openAdd}
                    data-testid="add-vision-backend"
                  >
                    {t('settings.visionModel.add')}
                  </Button>
                </div>
              </div>
            </CardHeader>

            <CardContent className="p-0">
              <div className="divide-y divide-border/70">
                {modelConfigs.configs.map((config) => {
                  const isActive = modelConfigs.active_id === config.id;
                  const canSetActive =
                    config.enabled &&
                    config.provider === 'local' &&
                    config.id !== 'paddle_ocr_service' &&
                    !isActive;

                  return (
                    <div key={config.id} className="flex items-center gap-3 px-4 py-2.5">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-sm font-medium">{config.name}</span>
                          {isActive && (
                            <Badge
                              className={`whitespace-nowrap text-[10px] leading-4 ${tonePanelClass.success}`}
                            >
                              {t('settings.visionModel.active')}
                            </Badge>
                          )}
                          <Badge
                            variant={
                              BUILTIN_VISION_IDS.has(config.id) || config.enabled
                                ? 'secondary'
                                : 'outline'
                            }
                            className="whitespace-nowrap text-[10px] leading-4"
                          >
                            {BUILTIN_VISION_IDS.has(config.id) || config.enabled
                              ? t('common.enabled')
                              : t('common.disabled')}
                          </Badge>
                          {BUILTIN_VISION_IDS.has(config.id) &&
                            (() => {
                              const live = liveForBuiltin(config.id);
                              return live === 'online' ? (
                                <Badge
                                  className={`whitespace-nowrap text-[10px] leading-4 ${tonePanelClass.success}`}
                                >
                                  {t('common.online')}
                                </Badge>
                              ) : live === 'offline' ? (
                                <Badge
                                  variant="destructive"
                                  className="whitespace-nowrap text-[10px] leading-4"
                                >
                                  {t('common.offline')}
                                </Badge>
                              ) : builtinLive === null ? (
                                <Badge
                                  variant="outline"
                                  className="whitespace-nowrap text-[10px] leading-4"
                                >
                                  {t('common.checking')}
                                </Badge>
                              ) : (
                                <Badge
                                  variant="outline"
                                  className="whitespace-nowrap text-[10px] leading-4"
                                >
                                  {t('common.unknown')}
                                </Badge>
                              );
                            })()}
                        </div>

                        <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                          <Badge
                            variant="outline"
                            className="whitespace-nowrap text-[10px] leading-4"
                          >
                            {getProviderLabel(config.provider)}
                          </Badge>
                          <span className="text-border">/</span>
                          <span className="truncate font-mono">{config.model_name}</span>
                          {config.base_url && (
                            <>
                              <span className="text-border">/</span>
                              <span className="max-w-[240px] truncate">{config.base_url}</span>
                            </>
                          )}
                        </div>

                        {config.description && (
                          <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                            {config.description}
                          </p>
                        )}
                      </div>

                      <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
                        <Button
                          size="sm"
                          variant={isActive ? 'secondary' : 'outline'}
                          className="h-8 whitespace-nowrap px-2.5"
                          disabled={!canSetActive || settingActiveModelId === config.id}
                          onClick={() => void setActiveModelConfig(config.id)}
                          data-testid={`set-active-model-${config.id}`}
                        >
                          {settingActiveModelId === config.id
                            ? t('settings.visionModel.settingActive')
                            : isActive
                              ? t('settings.visionModel.active')
                              : t('settings.visionModel.setActive')}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-8 whitespace-nowrap px-2.5"
                          disabled={testingModelId === config.id}
                          onClick={() => void testModelConfig(config.id)}
                          data-testid={`test-model-${config.id}`}
                        >
                          {testingModelId === config.id ? t('common.testing') : t('common.test')}
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8"
                          onClick={() => openEdit(config)}
                          data-testid={`edit-model-${config.id}`}
                          aria-label={t('common.edit')}
                        >
                          <Pencil aria-hidden="true" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          disabled={BUILTIN_VISION_IDS.has(config.id)}
                          className={cn(
                            'h-8 w-8',
                            BUILTIN_VISION_IDS.has(config.id) && 'cursor-not-allowed opacity-20',
                          )}
                          onClick={() =>
                            requestConfirm({
                              title: t('common.delete'),
                              message: t('settings.visionModel.confirmDelete'),
                              danger: true,
                              onConfirm: () => deleteModelConfig(config.id),
                            })
                          }
                          aria-label={t('common.delete')}
                          data-testid={`delete-model-${config.id}`}
                        >
                          <Trash2 aria-hidden="true" />
                        </Button>
                      </div>
                    </div>
                  );
                })}

                {modelConfigs.configs.length === 0 && (
                  <p className="px-4 py-5 text-center text-sm text-muted-foreground">
                    {t('settings.visionModel.empty')}
                  </p>
                )}
              </div>

              {testResult && <VisionModelTestResult testResult={testResult} />}
            </CardContent>
          </Card>
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
          Boolean(showModal)
        }
      />
    </div>
  );
}
