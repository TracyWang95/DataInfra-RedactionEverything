// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import {
  BUILTIN_VISION_IDS,
  useVisionModelConfig,
} from './hooks/use-model-config';
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
    confirmAndClose,
    cancelConfirm,
  } = useVisionModelForm(saveModelConfig);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-7 w-7 animate-spin rounded-full border-2 border-muted border-t-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background">
      <div className="page-shell-narrow overflow-auto overscroll-contain">
        <div className="page-stack">
          <Card className="rounded-[24px] border-border/70 bg-muted/30 shadow-[var(--shadow-control)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-base tracking-[-0.03em]">{t('settings.visionModel.infoTitle')}</CardTitle>
              <CardDescription className="mt-2 text-sm leading-relaxed">
                {t('settings.visionModel.infoDesc')}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="flex flex-wrap gap-2 border-t pt-3">
                <Badge variant="outline">{t('settings.visionModel.tag.local')}</Badge>
                <Badge variant="outline">{t('settings.visionModel.tag.openai')}</Badge>
                <Badge variant="outline">{t('settings.visionModel.tag.custom')}</Badge>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-[24px] border-border/70 shadow-[var(--shadow-control)]">
            <CardHeader className="pb-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-1">
                  <CardTitle className="text-base">{t('settings.visionModel.listTitle')}</CardTitle>
                  <CardDescription className="text-xs">
                    {t('settings.visionModel.listDesc')}
                  </CardDescription>
                </div>
                <Button size="sm" onClick={openAdd} data-testid="add-vision-backend">
                  {t('settings.visionModel.add')}
                </Button>
              </div>
            </CardHeader>

            <CardContent className="p-0">
              <div className="divide-y divide-border/70">
                {modelConfigs.configs.map(config => (
                  <div key={config.id} className="flex items-center gap-4 px-5 py-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{config.name}</span>
                        <Badge
                          variant={BUILTIN_VISION_IDS.has(config.id) || config.enabled ? 'secondary' : 'outline'}
                          className="text-xs"
                        >
                          {BUILTIN_VISION_IDS.has(config.id) || config.enabled
                            ? t('common.enabled')
                            : t('common.disabled')}
                        </Badge>
                        {BUILTIN_VISION_IDS.has(config.id) && (() => {
                          const live = liveForBuiltin(config.id);
                          return live === 'online'
                            ? (
                              <Badge className={`text-xs ${tonePanelClass.success}`}>
                                {t('common.online')}
                              </Badge>
                            )
                            : live === 'offline'
                              ? (
                                <Badge variant="destructive" className="text-xs">
                                  {t('common.offline')}
                                </Badge>
                              )
                              : builtinLive === null
                                ? (
                                  <Badge variant="outline" className="text-xs">
                                    {t('common.checking')}
                                  </Badge>
                                )
                                : (
                                  <Badge variant="outline" className="text-xs">
                                    {t('common.unknown')}
                                  </Badge>
                                );
                        })()}
                      </div>

                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <Badge variant="outline" className="text-[10px]">
                          {getProviderLabel(config.provider)}
                        </Badge>
                        <span>|</span>
                        <span className="font-mono">{config.model_name}</span>
                        {config.base_url && (
                          <>
                            <span>|</span>
                            <span className="max-w-[200px] truncate">{config.base_url}</span>
                          </>
                        )}
                      </div>

                      {config.description && (
                        <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{config.description}</p>
                      )}
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={testingModelId === config.id}
                        onClick={() => void testModelConfig(config.id)}
                        data-testid={`test-model-${config.id}`}
                      >
                        {testingModelId === config.id ? t('common.testing') : t('common.test')}
                      </Button>
                      <Button size="icon" variant="ghost" onClick={() => openEdit(config)} data-testid={`edit-model-${config.id}`} aria-label={t('common.edit')}>
                        <PencilIcon />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        disabled={BUILTIN_VISION_IDS.has(config.id)}
                        className={cn(BUILTIN_VISION_IDS.has(config.id) && 'cursor-not-allowed opacity-20')}
                        onClick={() => requestConfirm({
                          title: t('common.delete'),
                          message: t('settings.visionModel.confirmDelete'),
                          danger: true,
                          onConfirm: () => void deleteModelConfig(config.id),
                        })}
                        aria-label={t('common.delete')}
                        data-testid={`delete-model-${config.id}`}
                      >
                        <TrashIcon />
                      </Button>
                    </div>
                  </div>
                ))}

                {modelConfigs.configs.length === 0 && (
                  <p className="px-5 py-6 text-center text-sm text-muted-foreground">
                    {t('settings.visionModel.empty')}
                  </p>
                )}
              </div>

              {testResult && <VisionModelTestResult testResult={testResult} />}
            </CardContent>
          </Card>

          <div className="flex justify-end">
            <Button
              variant="outline"
              onClick={() => requestConfirm({
                title: t('settings.visionModel.reset'),
                message: t('settings.visionModel.confirmReset'),
                danger: true,
                onConfirm: () => void resetModelConfigs(),
              })}
              data-testid="reset-vision-models"
            >
              {t('settings.visionModel.reset')}
            </Button>
          </div>
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
          onConfirm={confirmAndClose}
          onCancel={cancelConfirm}
        />
      )}
    </div>
  );
}

function PencilIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
      />
    </svg>
  );
}
