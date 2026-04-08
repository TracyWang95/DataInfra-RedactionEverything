// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useRedactionPresets } from './hooks/use-redaction-presets';
import { PresetColumn } from './components/preset-column';
import { RedactionBridgeConfig } from './redaction-bridge-config';
import { RedactionPresetDialog } from './redaction-preset-dialog';

export function RedactionList() {
  const t = useT();
  const state = useRedactionPresets();

  if (state.loading) {
    return (
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
        <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
          <Card className="overflow-hidden">
            <CardHeader className="pb-3">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-80 max-w-full" />
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <Skeleton className="h-20 w-full rounded-xl" />
              <div className="grid gap-2 md:grid-cols-2">
                <Skeleton className="h-16 w-full rounded-xl" />
                <Skeleton className="h-16 w-full rounded-xl" />
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                <Skeleton className="h-[22rem] w-full rounded-xl" />
                <Skeleton className="h-[22rem] w-full rounded-xl" />
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
        {state.loadError && (
          <Alert variant="destructive">
            <AlertDescription>{state.loadError}</AlertDescription>
          </Alert>
        )}

        <Card className="page-surface overflow-hidden">
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="text-sm">{t('settings.redaction.configTitle')}</CardTitle>
                <CardDescription className="mt-0.5 text-xs">
                  {t('settings.redaction.configDesc')}
                </CardDescription>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant="outline" onClick={() => state.openNew('text')} data-testid="new-text-preset">
                  {t('settings.redaction.newText')}
                </Button>
                <Button size="sm" variant="outline" onClick={() => state.openNew('vision')} data-testid="new-vision-preset">
                  {t('settings.redaction.newVision')}
                </Button>
              </div>
            </div>
          </CardHeader>

          <CardContent className="page-surface-body flex flex-col gap-4 p-6">
            <RedactionBridgeConfig
              bridgeText={state.bridgeText}
              bridgeVision={state.bridgeVision}
              textPresets={state.textPresets}
              visionPresets={state.visionPresets}
              summaryTextLabel={state.summaryTextLabel}
              summaryVisionLabel={state.summaryVisionLabel}
              setBridgeText={state.setBridgeText}
              setBridgeVision={state.setBridgeVision}
            />

            <div className="grid gap-2 md:grid-cols-2">
              <PresetColumn
                title={t('settings.redaction.textColumn')}
                defaultPreset={state.defaultTextPreset}
                presets={state.textPresets}
                entityTypes={state.effectiveEntityTypes}
                pipelines={state.effectivePipelines}
                expanded={state.expanded}
                setExpanded={state.setExpanded}
                colPrefix="text"
                onEdit={state.openEdit}
                    onDelete={(id) => state.setConfirmState({
                      title: t('common.delete'),
                      message: t('settings.redaction.confirmDelete'),
                      danger: true,
                      onConfirm: () => void state.removePreset(id),
                    })}
              />
              <PresetColumn
                title={t('settings.redaction.visionColumn')}
                defaultPreset={state.defaultVisionPreset}
                presets={state.visionPresets}
                entityTypes={state.effectiveEntityTypes}
                pipelines={state.effectivePipelines}
                expanded={state.expanded}
                setExpanded={state.setExpanded}
                colPrefix="vision"
                onEdit={state.openEdit}
                    onDelete={(id) => state.setConfirmState({
                      title: t('common.delete'),
                      message: t('settings.redaction.confirmDelete'),
                      danger: true,
                      onConfirm: () => void state.removePreset(id),
                    })}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      <RedactionPresetDialog
        modalOpen={state.modalOpen}
        editingPresetId={state.editingPresetId}
        presetForm={state.presetForm}
        saving={state.saving}
        regexTypes={state.regexTypes}
        semanticTypes={state.semanticTypes}
        effectivePipelines={state.effectivePipelines}
        presetKindLabel={state.presetKindLabel}
        setPresetForm={state.setPresetForm}
        setModalOpen={state.setModalOpen}
        saveModal={state.saveModal}
      />
      {state.confirmState && (
        <ConfirmDialog
          open
          title={state.confirmState.title}
          message={state.confirmState.message}
          danger={state.confirmState.danger}
          onConfirm={() => {
            state.confirmState!.onConfirm();
            state.setConfirmState(null);
          }}
          onCancel={() => state.setConfirmState(null)}
        />
      )}
    </div>
  );
}
